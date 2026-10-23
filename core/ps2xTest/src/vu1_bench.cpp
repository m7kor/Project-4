// VU1 microprogram benchmark and equivalence probe.
//
// Replays the VU1 MSCAL snapshots written by the runner with
// PS2X_VU1_SNAPSHOT=<dir>: each file holds [header][VU1State][code][data].
// For every snapshot the program is run from its start PC on a real
// PS2Memory (so the decoded-code cache behaves as in the game), and the run
// reports host nanoseconds per VU1 cycle plus a hash of the final registers
// and data memory. Comparing the hash between interpreter modes (environment
// switches such as PS2X_VU1_DIRECT=0) checks that an optimisation does not
// change results.
//
// Timing covers only VU1 execution. --no-status leaves the status register out
// of the hash (its sticky bits are unobservable when no FSEQ/FSAND/FSOR exists
// and the interpreter then skips dead flag work).
//
// --worker runs isolated replay on PS2VifWorkQueue; it does not enable game
// MTVU. --gif-hash additionally parses emitted GIF on CPU and hashes packet
// path, size and bytes. It changes the diagnostic workload, not game code.
//   ps2x_vu1_bench <snapshot dir> [--repeat N] [--limit N] [--no-status] [--worker] [--gif-hash]
#include "runtime/ps2_memory.h"
#include "runtime/gs/gs_frontend.h"
#include "runtime/ps2_vu1.h"
#include "runtime/ps2_vif_work_queue.h"
#include "runtime/gs/ps2_gif_arbiter.h"

#include <algorithm>
#include <chrono>
#include <charconv>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <stdexcept>
#include <vector>

namespace
{
    struct SnapshotHeader
    {
        uint32_t magic;
        uint32_t version;
        uint32_t startPc, top, itop;
        uint32_t stateBytes, codeBytes, dataBytes;
        uint64_t vsync;
    };

    struct Snapshot
    {
        SnapshotHeader header{};
        VU1State state{};
        std::vector<uint8_t> code, data;
    };

    bool load(const std::filesystem::path &path, Snapshot &out)
    {
        std::ifstream file(path, std::ios::binary);
        if (!file.read(reinterpret_cast<char *>(&out.header), sizeof(out.header)))
            return false;
        // Validate before allocating or replaying: snapshots are complete
        // VU1 images, not partial overlays of the previous run's buffers.
        if (out.header.magic != 0x53315556u || out.header.version != 1u ||
            out.header.stateBytes != sizeof(VU1State) ||
            out.header.codeBytes != PS2_VU1_CODE_SIZE || out.header.dataBytes != PS2_VU1_DATA_SIZE ||
            out.header.startPc >= PS2_VU1_CODE_SIZE || (out.header.startPc & 7u) != 0u ||
            std::filesystem::file_size(path) != sizeof(SnapshotHeader) + sizeof(VU1State) +
                                                PS2_VU1_CODE_SIZE + PS2_VU1_DATA_SIZE)
            return false;
        out.code.resize(out.header.codeBytes);
        out.data.resize(out.header.dataBytes);
        return file.read(reinterpret_cast<char *>(&out.state), sizeof(out.state)) &&
               file.read(reinterpret_cast<char *>(out.code.data()), out.code.size()) &&
               file.read(reinterpret_cast<char *>(out.data.data()), out.data.size());
    }

    uint64_t fnv(uint64_t hash, const void *bytes, size_t size)
    {
        const auto *p = static_cast<const uint8_t *>(bytes);
        for (size_t i = 0; i < size; ++i)
            hash = (hash ^ p[i]) * 0x100000001B3ull;
        return hash;
    }
}

extern uint64_t g_vu1QueueCounts[7];
extern uint64_t g_vu1CompiledBlockEntries, g_vu1CompiledBlockSteps, g_vu1CompiledDeadFmac;

#include "vu1_command_replay.inl"
#include "dma_chain_bench.inl"
#include "vif1_unpack_bench.inl"

int main(int argc, char **argv)
{
    if (argc >= 2 && std::string(argv[1]) == "--vif-unpack")
    {
        try { return benchmarkVifUnpack(argc, argv); }
        catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
    }
    if (argc >= 2 && std::string(argv[1]) == "--dma-buffers")
    {
        try { return benchmarkDmaBuffers(argc, argv); }
        catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
    }
    if (argc >= 2 && std::string(argv[1]) == "--commands")
    {
        try { return replayVuCommands(argc, argv); }
        catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
    }
    if (argc < 2)
    {
        std::cerr << "usage: ps2x_vu1_bench <snapshot dir> [--repeat N] [--limit N] [--no-status] [--worker] [--gif-hash]\n";
        return 2;
    }
    int repeat = 3;
    uint32_t budget = 65536, resumes = 0;
    size_t limit = SIZE_MAX;
    bool hashStatus = true;
    bool workerReplay = false, hashGif = false, detachedExecutor = false;
    for (int i = 2; i < argc; ++i)
    {
        const std::string option = argv[i];
        if (option == "--executor")
        {
            detachedExecutor = true;
            continue;
        }
        if (option == "--gif-hash")
        {
            hashGif = true;
            continue;
        }
        if (option == "--worker")
        {
            workerReplay = true;
            continue;
        }
        if (option == "--no-status")
        {
            hashStatus = false;
            continue;
        }
        uint32_t value = 0;
        if ((option != "--repeat" && option != "--limit" && option != "--budget" && option != "--resumes") || i + 1 >= argc)
        {
            std::cerr << "invalid or incomplete option: " << option << "\n";
            return 2;
        }
        const std::string input = argv[++i];
        const auto parsed = std::from_chars(input.data(), input.data() + input.size(), value);
        if (parsed.ec != std::errc{} || parsed.ptr != input.data() + input.size() ||
            (value == 0 && option != "--resumes") ||
            (option == "--repeat" && value > static_cast<uint32_t>(INT32_MAX)) ||
            (option == "--budget" && value > 65536) || (option == "--resumes" && value > 64))
        {
            std::cerr << option << " requires a positive integer\n";
            return 2;
        }
        if (option == "--repeat")
            repeat = static_cast<int>(value);
        else if (option == "--budget")
            budget = value;
        else if (option == "--resumes")
            resumes = value;
        else
            limit = value;
    }

    std::vector<std::filesystem::path> files;
    std::error_code directoryError;
    std::filesystem::directory_iterator directory(argv[1], directoryError);
    if (directoryError)
    {
        std::cerr << "cannot read snapshot directory: " << directoryError.message() << "\n";
        return 1;
    }
    for (const auto &entry : directory)
        if (entry.is_regular_file() && entry.path().extension() == ".bin" &&
            entry.path().filename().string().rfind("vu1snap_", 0) == 0)
            files.push_back(entry.path());
    std::sort(files.begin(), files.end());
    if (files.size() > limit)
        files.resize(limit);
    std::vector<Snapshot> snapshots;
    for (const auto &path : files)
    {
        Snapshot snapshot;
        if (!load(path, snapshot))
        {
            std::cerr << "invalid snapshot: " << path << "\n";
            return 1;
        }
        snapshots.push_back(std::move(snapshot));
    }
    if (snapshots.empty())
    {
        std::cerr << "no snapshots in " << argv[1] << "\n";
        return 1;
    }

    PS2Memory memory;
    if (!memory.initialize())
    {
        std::cerr << "PS2Memory initialisation failed\n";
        return 1;
    }
    GS gs;
    gs.init(memory.getGSVRAM(), static_cast<uint32_t>(PS2_GS_VRAM_SIZE), &memory.gs());
    uint64_t gifHash = 0xCBF29CE484222325ull, gifPackets = 0;
    GifArbiter arbiter;
    if (hashGif)
    {
        arbiter.setProcessPathPacketFn([&](GifPathId path, const uint8_t *data, uint32_t bytes) {
            const uint8_t pathId = static_cast<uint8_t>(path);
            gifHash = fnv(gifHash, &pathId, sizeof(pathId));
            gifHash = fnv(gifHash, &bytes, sizeof(bytes));
            gifHash = fnv(gifHash, data, bytes);
            ++gifPackets;
            gs.processGIFPacket(data, bytes, path);
        });
        memory.setGifArbiter(&arbiter);
    }

    uint64_t totalCycles = 0, resultHash = 0xCBF29CE484222325ull;
    double bestSeconds = 1e30;
    size_t compiledSnapshots = 0;
    uint64_t codeImageUpdates = 0;
    uint64_t expectedGifHash = 0, expectedGifPackets = 0;
    for (int pass = 0; pass < repeat; ++pass)
    {
        gifHash = 0xCBF29CE484222325ull;
        gifPackets = 0;
        VU1Interpreter vu1(VU1Interpreter::Unit::VU1);
        uint64_t cycles = 0;
        uint64_t hash = 0xCBF29CE484222325ull;
        double seconds = 0.0;
        size_t compiled = 0;
        // In worker mode every access to replay memory, VU state and GS stays
        // on that worker until stop joins it. The producer publishes owned
        // snapshot indices only; this is not concurrent EE/game execution.
        const auto replay = [&](const Snapshot &snapshot) {
            // reset() resets state/scheduling, not the decoded-code cache.
            // Publish every changed image just as MPG does in the game.
            if (std::memcmp(memory.getVU1Code(), snapshot.code.data(), snapshot.code.size()) != 0)
            {
                std::memcpy(memory.getVU1Code(), snapshot.code.data(), snapshot.code.size());
                memory.markVU1CodeModified();
                ++codeImageUpdates;
            }
            std::memcpy(memory.getVU1Data(), snapshot.data.data(), snapshot.data.size());
            vu1.reset();
            vu1.state() = snapshot.state;
            vu1.state().cycles = 0; // the interpreter's own clock starts at 0 after reset
            const uint64_t before = 0;
            const auto start = std::chrono::steady_clock::now();
            const PS2Vu1RunControl control{(snapshot.state.dBitEnabled ? 0x400u : 0u) |
                                           (snapshot.state.tBitEnabled ? 0x800u : 0u), snapshot.header.vsync};
            if (detachedExecutor)
                executePS2Vu1Command(vu1, memory, gs, PS2Vu1Command::Start, control,
                                     snapshot.header.startPc, snapshot.header.top, snapshot.header.itop, budget);
            else
                vu1.execute(memory.getVU1Code(), PS2_VU1_CODE_SIZE, memory.getVU1Data(), PS2_VU1_DATA_SIZE, gs,
                            &memory, snapshot.header.startPc, snapshot.header.top, snapshot.header.itop, budget);
            // Exercise separate run/resume cache validation at small budgets.
            // Fixed resumes are a reference comparison of the API sequence,
            // not an assertion that every captured program remains running.
            for (uint32_t resumed = 0; resumed < resumes; ++resumed)
                if (detachedExecutor)
                    executePS2Vu1Command(vu1, memory, gs, PS2Vu1Command::Continue, control,
                                         0, snapshot.header.top, snapshot.header.itop, budget);
                else
                    vu1.resume(memory.getVU1Code(), PS2_VU1_CODE_SIZE, memory.getVU1Data(), PS2_VU1_DATA_SIZE,
                               gs, &memory, snapshot.header.top, snapshot.header.itop, budget);
            seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
            cycles += vu1.state().cycles - before;
            compiled += vu1.usesCompiledProgram() ? 1u : 0u;
            const VU1State &s = vu1.state();
            hash = fnv(hash, s.vf, sizeof(s.vf));
            hash = fnv(hash, s.vi, sizeof(s.vi));
            hash = fnv(hash, s.acc, sizeof(s.acc));
            hash = fnv(hash, &s.mac, sizeof(s.mac));
            if (hashStatus)
                hash = fnv(hash, &s.status, sizeof(s.status));
            hash = fnv(hash, &s.clip, sizeof(s.clip));
            // These scalar/control results and elapsed guest cycles are just
            // as observable as VF/VI. Never hash struct padding.
            hash = fnv(hash, &s.q, sizeof(s.q));
            hash = fnv(hash, &s.p, sizeof(s.p));
            hash = fnv(hash, &s.i, sizeof(s.i));
            hash = fnv(hash, &s.r, sizeof(s.r));
            hash = fnv(hash, &s.pc, sizeof(s.pc));
            hash = fnv(hash, &s.cycles, sizeof(s.cycles));
            hash = fnv(hash, &s.ebit, sizeof(s.ebit));
            hash = fnv(hash, &s.haltAfterDelaySlot, sizeof(s.haltAfterDelaySlot));
            hash = fnv(hash, &s.dBitEnabled, sizeof(s.dBitEnabled));
            hash = fnv(hash, &s.tBitEnabled, sizeof(s.tBitEnabled));
            hash = fnv(hash, &s.stoppedByD, sizeof(s.stoppedByD));
            hash = fnv(hash, &s.stoppedByT, sizeof(s.stoppedByT));
            hash = fnv(hash, &s.top, sizeof(s.top));
            hash = fnv(hash, &s.itop, sizeof(s.itop));
            hash = fnv(hash, &s.branchPending, sizeof(s.branchPending));
            if (s.branchPending)
            {
                hash = fnv(hash, &s.branchTarget, sizeof(s.branchTarget));
                hash = fnv(hash, &s.branchDelay, sizeof(s.branchDelay));
            }
            hash = fnv(hash, memory.getVU1Data(), PS2_VU1_DATA_SIZE);
        };
        if (workerReplay)
        {
            PS2VifWorkQueue queue([&](const PS2VifWorkQueue::Item &item) {
                uint64_t index = 0;
                if (item.bytes.size() != sizeof(index))
                    throw std::runtime_error("invalid worker replay index");
                std::memcpy(&index, item.bytes.data(), sizeof(index));
                replay(snapshots.at(static_cast<size_t>(index)));
            }, 1024, 128);
            for (uint64_t index = 0; index < snapshots.size(); ++index)
                queue.enqueue(PS2VifWorkQueue::Kind::Vif1,
                              reinterpret_cast<const uint8_t *>(&index), sizeof(index), {});
            queue.drain(); // Propagate execution failures before reading results.
            queue.stop();
        }
        else
            for (const Snapshot &snapshot : snapshots) replay(snapshot);
        if (pass && (resultHash != hash || totalCycles != cycles || compiledSnapshots != compiled ||
                     expectedGifHash != gifHash || expectedGifPackets != gifPackets))
        {
            std::cerr << "replay results differ between passes\n";
            return 1;
        }
        bestSeconds = std::min(bestSeconds, seconds);
        totalCycles = cycles;
        resultHash = hash;
        compiledSnapshots = compiled;
        expectedGifHash = gifHash;
        expectedGifPackets = gifPackets;
    }
    std::printf("snapshots=%zu vu1_cycles=%llu best=%.3f s  ns/cycle=%.1f  result=%016llx\n", snapshots.size(),
                static_cast<unsigned long long>(totalCycles), bestSeconds,
                1e9 * bestSeconds / static_cast<double>(std::max<uint64_t>(totalCycles, 1)),
                static_cast<unsigned long long>(resultHash));
    std::printf("compiled=%zu/%zu status_hashed=%s\n", compiledSnapshots, snapshots.size(), hashStatus ? "yes" : "no");
    std::printf("code_image_updates=%llu code_cache_publication=yes\n",
                static_cast<unsigned long long>(codeImageUpdates));
    std::printf("budget=%u resumes=%u\n", budget, resumes);
    std::printf("execution_thread=%s game_mtvu_enabled=no\n", workerReplay ? "worker" : "caller");
    std::printf("executor=%s\n", detachedExecutor ? "detached" : "direct");
    std::printf("compiled_block_entries=%llu compiled_block_steps=%llu\n",
                static_cast<unsigned long long>(g_vu1CompiledBlockEntries),
                static_cast<unsigned long long>(g_vu1CompiledBlockSteps));
    if (hashGif)
        std::printf("gif_packets=%llu gif_result=%016llx\n",
                    static_cast<unsigned long long>(expectedGifPackets),
                    static_cast<unsigned long long>(expectedGifHash));
    std::printf("per pass: flag=%llu efu=%llu store=%llu vf=%llu vi=%llu acc=%llu commits(non-early)=%llu\n",
                (unsigned long long)(g_vu1QueueCounts[0] / repeat), (unsigned long long)(g_vu1QueueCounts[1] / repeat),
                (unsigned long long)(g_vu1QueueCounts[2] / repeat), (unsigned long long)(g_vu1QueueCounts[3] / repeat),
                (unsigned long long)(g_vu1QueueCounts[4] / repeat), (unsigned long long)(g_vu1QueueCounts[5] / repeat),
                (unsigned long long)(g_vu1QueueCounts[6] / repeat));
    return 0;
}

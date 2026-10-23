// Private command-sequence mode of ps2x_vu1_bench. Captured game data stays local.
#include <array>
#include <regex>
#include <limits>
#include <iomanip>
#include <memory>
#include <cstddef>
#include "runtime/ps2_vu1_execution.h"

extern thread_local bool g_vu1CommandGifCollect;
extern thread_local uint64_t g_vu1CommandGifHash, g_vu1CommandGifPackets;

namespace
{
    uint64_t commandStateHash(const VU1State &s)
    {
        uint64_t hash = 0xCBF29CE484222325ull;
        hash = fnv(hash, s.vf, sizeof(s.vf));
        hash = fnv(hash, s.vi, sizeof(s.vi));
        hash = fnv(hash, s.acc, sizeof(s.acc));
        const auto add = [&](const auto &value) { hash = fnv(hash, &value, sizeof(value)); };
        add(s.q); add(s.p); add(s.i); add(s.r); add(s.pc); add(s.mac); add(s.clip); add(s.status);
        add(s.cycles); add(s.ebit); add(s.haltAfterDelaySlot); add(s.dBitEnabled); add(s.tBitEnabled);
        add(s.stoppedByD); add(s.stoppedByT); add(s.top); add(s.itop);
        add(s.branchPending); add(s.branchTarget); add(s.branchDelay);
        return hash;
    }

    struct VuCommandRecord {
        std::array<uint64_t, 16> header{};
        VU1State before{}, after{};
        std::array<uint8_t, PS2_VU1_CODE_SIZE> code{};
        std::array<uint8_t, PS2_VU1_DATA_SIZE> data{}, result{};
    };

    std::vector<VuCommandRecord> loadVuCommands(const std::filesystem::path &directory)
    {
        if (std::filesystem::file_size(directory / "manifest.jsonl") > 2 * 1024 * 1024)
            throw std::runtime_error("oversized VU1 command manifest");
        std::ifstream manifest(directory / "manifest.jsonl");
        if (!manifest) throw std::runtime_error("missing VU1 command manifest");
        const std::regex meta(R"(\{"kind":"meta","schema":1,"state_bytes":([0-9]+),"from_ee":([0-9]+),"max_sequences":([0-9]+),"max_commands":([0-9]+)\})");
        const std::regex command(R"(\{"kind":"command","file":"command-([0-9]{8})\.bin","index":([0-9]+),"sequence":([0-9]+),"command":([0-9]+)\})");
        const std::regex end(R"rx(\{"kind":"complete","commands":([0-9]+),"sequences":([0-9]+),"reason":"(sequence-limit|command-prefix-limit)"\})rx");
        std::string line;
        std::smatch match;
        if (!std::getline(manifest, line) || !std::regex_match(line, match, meta) || std::stoull(match[1]) != sizeof(VU1State))
            throw std::runtime_error("unsupported VU1 command metadata or state ABI");
        const uint64_t maxSequences = std::stoull(match[3]), maxCommands = std::stoull(match[4]);
        if (!maxSequences || maxSequences > 256 || !maxCommands || maxCommands > 4096)
            throw std::runtime_error("invalid VU1 command capture bounds");
        std::vector<VuCommandRecord> records;
        bool complete = false;
        uint64_t sequences = 0, inSequence = 0;
        while (std::getline(manifest, line))
        {
            if (line.size() > 512 || complete) throw std::runtime_error("unexpected trailing VU1 command record");
            if (std::regex_match(line, match, end))
            {
                if (std::stoull(match[1]) != records.size() || std::stoull(match[2]) != sequences)
                    throw std::runtime_error("VU1 command footer counts disagree");
                if ((match[3] == "sequence-limit" && sequences != maxSequences) ||
                    (match[3] == "command-prefix-limit" && records.size() != maxCommands))
                    throw std::runtime_error("VU1 footer does not reach its declared limit");
                complete = true;
                continue;
            }
            if (!std::regex_match(line, match, command) || records.size() >= maxCommands ||
                std::stoull(match[1]) != records.size() || std::stoull(match[2]) != records.size())
                throw std::runtime_error("invalid or nonsequential VU1 command manifest");
            char name[48];
            std::snprintf(name, sizeof(name), "command-%08llu.bin", static_cast<unsigned long long>(records.size()));
            const auto path = directory / name;
            constexpr size_t bytes = 16 * sizeof(uint64_t) + 2 * sizeof(VU1State) + PS2_VU1_CODE_SIZE + 2 * PS2_VU1_DATA_SIZE;
            if (std::filesystem::file_size(path) != bytes) throw std::runtime_error("truncated or oversized VU1 command file");
            VuCommandRecord record;
            std::ifstream input(path, std::ios::binary);
            const auto read = [&](void *data, size_t size) {
                if (!input.read(static_cast<char *>(data), static_cast<std::streamsize>(size)))
                    throw std::runtime_error("could not read a complete VU1 command");
            };
            read(record.header.data(), sizeof(record.header));
            read(&record.before, sizeof(record.before)); read(record.code.data(), record.code.size());
            read(record.data.data(), record.data.size()); read(&record.after, sizeof(record.after));
            read(record.result.data(), record.result.size());
            for (const VU1State *state : {&record.before, &record.after})
                for (size_t offset : {offsetof(VU1State, ebit), offsetof(VU1State, haltAfterDelaySlot),
                     offsetof(VU1State, dBitEnabled), offsetof(VU1State, tBitEnabled),
                     offsetof(VU1State, stoppedByD), offsetof(VU1State, stoppedByT), offsetof(VU1State, branchPending)})
                    if (reinterpret_cast<const uint8_t *>(state)[offset] > 1u)
                        throw std::runtime_error("invalid VU1 state boolean representation");
            const auto &h = record.header;
            if (h[0] != 0x3151455355315650ull || h[1] != 1 || h[11] != sizeof(VU1State) ||
                h[14] != PS2_VU1_CODE_SIZE || h[15] != PS2_VU1_DATA_SIZE || h[4] > 1 ||
                h[8] == 0 || h[8] > 65536 || h[2] != std::stoull(match[3]) || h[3] != std::stoull(match[4]))
                throw std::runtime_error("VU1 command header/manifest mismatch");
            for (size_t field : {5u, 6u, 7u, 9u})
                if (h[field] > UINT32_MAX) throw std::runtime_error("VU1 command argument exceeds 32 bits");
            if (h[4] == 0)
            {
                if (h[2] != sequences || h[3] != 0 || sequences == maxSequences)
                    throw std::runtime_error("VU1 sequence must begin with its ordered Start");
                ++sequences;
                inSequence = 0;
            }
            else if (!sequences || h[2] != sequences - 1 || h[3] != inSequence)
                throw std::runtime_error("VU1 Continue is missing its prefix");
            ++inSequence;
            records.push_back(std::move(record));
        }
        if (!complete || records.empty()) throw std::runtime_error("VU1 command capture is not sealed");
        return records;
    }

    int replayVuCommands(int argc, char **argv)
    {
        if (argc < 3) throw std::runtime_error("--commands needs a capture directory");
        uint32_t repeats = 1;
        bool timing = false;
        for (int i = 3; i < argc; ++i)
        {
            const std::string argument = argv[i];
            if (argument == "--timing-after-verify") timing = true;
            else if (argument == "--repeat" && i + 1 < argc)
            {
                const std::string value = argv[++i];
                const auto parsed = std::from_chars(value.data(), value.data() + value.size(), repeats);
                if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || !repeats || repeats > 1000)
                    throw std::runtime_error("command repeats must be 1..1000");
            }
            else throw std::runtime_error("invalid VU1 command replay option");
        }
        if (timing && repeats < 2) throw std::runtime_error("timing-after-verify needs at least two passes");
        const auto records = loadVuCommands(argv[2]);
        PS2Memory memory;
        if (!memory.initialize()) throw std::runtime_error("command replay memory initialization failed");
        GS gs;
        gs.init(memory.getGSVRAM(), static_cast<uint32_t>(PS2_GS_VRAM_SIZE), &memory.gs());
        GifArbiter arbiter;
        arbiter.setProcessPathPacketFn([](GifPathId, const uint8_t *, uint32_t) {});
        memory.setGifArbiter(&arbiter);
        auto vu = std::make_unique<VU1Interpreter>();
        uint64_t expectedHash = 0, expectedCycles = 0, expectedPackets = 0, expectedCompiled = 0;
        double bestSeconds = std::numeric_limits<double>::infinity();
        uint64_t continuations = 0, sequences = 0;
        for (const auto &record : records) { if (record.header[4]) ++continuations; else ++sequences; }
        const bool previousCollect = g_vu1CommandGifCollect;
        struct Restore { bool previous; ~Restore() { g_vu1CommandGifCollect = previous; } } restore{previousCollect};
        for (uint32_t pass = 0; pass < repeats; ++pass)
        {
            const bool verifyGif = !timing || pass == 0;
            uint64_t baseCycle = 0, cycles = 0, hash = 0xCBF29CE484222325ull, packets = 0, compiled = 0;
            double seconds = 0;
            for (size_t index = 0; index < records.size(); ++index)
            {
                const auto &record = records[index];
                const auto &h = record.header;
                if (h[4] == 0)
                {
                    vu->reset(); // Never reset on Continue: keep private pipelines and scoreboards.
                    vu->state() = record.before;
                    baseCycle = record.before.cycles;
                    vu->state().cycles = 0;
                }
                if (record.before.cycles < baseCycle || record.after.cycles < record.before.cycles)
                    throw std::runtime_error("recorded VU1 command cycles regress");
                VU1State before = record.before, after = record.after;
                before.cycles -= baseCycle;
                after.cycles -= baseCycle;
                vu->state().dBitEnabled = (h[9] & 0x400u) != 0;
                vu->state().tBitEnabled = (h[9] & 0x800u) != 0;
                if (commandStateHash(vu->state()) != commandStateHash(before))
                    throw std::runtime_error("VU1 pre-state differs at command " + std::to_string(index));
                if (std::memcmp(memory.getVU1Code(), record.code.data(), record.code.size()) != 0)
                {
                    std::memcpy(memory.getVU1Code(), record.code.data(), record.code.size());
                    memory.markVU1CodeModified();
                }
                std::memcpy(memory.getVU1Data(), record.data.data(), record.data.size());
                g_vu1CommandGifCollect = verifyGif;
                const auto start = std::chrono::steady_clock::now();
                executePS2Vu1Command(*vu, memory, gs, static_cast<PS2Vu1Command>(h[4]),
                                     {static_cast<uint32_t>(h[9]), h[10]}, static_cast<uint32_t>(h[5]),
                                     static_cast<uint32_t>(h[6]), static_cast<uint32_t>(h[7]), static_cast<uint32_t>(h[8]));
                seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
                compiled += vu->usesCompiledProgram() ? 1u : 0u;
                if (commandStateHash(vu->state()) != commandStateHash(after) ||
                    std::memcmp(memory.getVU1Data(), record.result.data(), record.result.size()) != 0)
                    throw std::runtime_error("VU1 recorded result differs at command " + std::to_string(index));
                if (verifyGif && (g_vu1CommandGifHash != h[12] || g_vu1CommandGifPackets != h[13]))
                    throw std::runtime_error("VU1 recorded GIF differs at command " + std::to_string(index));
                cycles += after.cycles - before.cycles;
                packets += h[13];
                const uint64_t stateHash = commandStateHash(vu->state());
                hash = fnv(hash, &stateHash, sizeof(stateHash));
                hash = fnv(hash, memory.getVU1Data(), PS2_VU1_DATA_SIZE);
            }
            if (pass && (hash != expectedHash || cycles != expectedCycles || packets != expectedPackets || compiled != expectedCompiled))
                throw std::runtime_error("VU1 command results differ between passes");
            expectedHash = hash; expectedCycles = cycles; expectedPackets = packets; expectedCompiled = compiled;
            if (!timing || pass) bestSeconds = std::min(bestSeconds, seconds);
        }
        if (!expectedCycles) throw std::runtime_error("VU1 command trace executed no cycles");
        std::printf("{\"mode\":\"command-sequence\",\"commands\":%llu,\"sequences\":%llu,\"continues\":%llu,\"repeats\":%u,\"cycles\":%llu,\"state_result\":\"%016llx\",\"gif_packets\":%llu,\"compiled_commands\":%llu,\"gif_verified_passes\":%u,\"best_seconds\":%.9f,\"ns_per_cycle\":%.3f,\"timing_excludes_gif_hash\":%s,\"traced_block_entries\":%llu,\"traced_clean_upper_calls\":%llu,\"traced_dead_fmac_finishes\":%llu}\n",
                    static_cast<unsigned long long>(records.size()), static_cast<unsigned long long>(sequences),
                    static_cast<unsigned long long>(continuations), repeats, static_cast<unsigned long long>(expectedCycles),
                    static_cast<unsigned long long>(expectedHash), static_cast<unsigned long long>(expectedPackets),
                    static_cast<unsigned long long>(expectedCompiled),
                    timing ? 1u : repeats, bestSeconds, bestSeconds * 1e9 / expectedCycles, timing ? "true" : "false",
                    static_cast<unsigned long long>(g_vu1CompiledBlockEntries),
                    static_cast<unsigned long long>(g_vu1CompiledBlockSteps),
                    static_cast<unsigned long long>(g_vu1CompiledDeadFmac));
        return 0;
    }
}

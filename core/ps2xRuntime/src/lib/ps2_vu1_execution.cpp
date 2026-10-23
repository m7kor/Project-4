// SPDX-License-Identifier: GPL-3.0-or-later
#include "runtime/ps2_vu1_execution.h"
#include "runtime/ps2_vu1.h"
#include "runtime/ps2_memory.h"
#include "runtime/gs/gs_frontend.h"
#include <array>
#include <atomic>
#include <bit>
#include <charconv>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <locale>
#include <mutex>
#include <memory>
#include <cstdio>
#include <stdexcept>

thread_local bool g_vu1CommandGifCollect = false;
thread_local uint64_t g_vu1CommandGifHash = 0xCBF29CE484222325ull;
thread_local uint64_t g_vu1CommandGifPackets = 0;

#include "vu/ps2_vu1_command_trace.inl"

namespace
{
    // Opt-in live workload census. Identity and reporting are outside the
    // measured execution interval; this diagnostic is not a game speed test.
    class Vu1CallProfile
    {
    public:
        using Clock = std::chrono::steady_clock;
        struct Sample { uint64_t codeHash, beforeCycles, ee; uint32_t pc; bool resume; };

        Vu1CallProfile()
            : fromEe(setting("PS2X_PROFILE_VU1_FROM", 0)),
              interval(setting("PS2X_PROFILE_VU1_INTERVAL", 30))
        {
            if (!interval) throw std::invalid_argument("VU1 profile interval must be positive");
            const std::filesystem::path directory(std::getenv("PS2X_PROFILE_VU1_DIR"));
            // Atomic ownership of a new directory: never overwrite evidence.
            if (!std::filesystem::create_directory(directory))
                throw std::runtime_error("VU1 profile requires a fresh output directory");
            output.exceptions(std::ios::badbit | std::ios::failbit);
            output.open(directory / "profile.jsonl", std::ios::out | std::ios::binary);
            output.imbue(std::locale::classic());
            output << "{\"kind\":\"meta\",\"schema\":1,\"from_ee\":" << fromEe
                   << ",\"interval_ee\":" << interval
                   << ",\"clock\":\"steady_clock_ns\",\"scope\":\"VU1 command execution, including GIF submission; identity and reporting excluded; not game FPS\"}\n";
            output.flush();
        }

        ~Vu1CallProfile()
        {
            // A forced diagnostic process stop can omit the last partial
            // window. Only windows with an end marker are accepted by tools.
            try { std::lock_guard lock(mutex); flush(); } catch (...) {}
        }

        Sample prepare(const VU1Interpreter &vu1, PS2Memory &memory,
                       PS2Vu1Command command, uint32_t startPc, uint64_t ee)
        {
            std::lock_guard lock(mutex);
            const auto *code = memory.getVU1Code();
            // Compare bytes as well as identity: a memory object can be
            // destroyed and recreated at the same address/generation.
            if (!haveCode || std::memcmp(cachedCode.data(), code, cachedCode.size()) != 0)
            {
                std::memcpy(cachedCode.data(), code, cachedCode.size());
                codeHash = 0xCBF29CE484222325ull;
                for (uint8_t byte : cachedCode)
                    codeHash = (codeHash ^ byte) * 0x100000001B3ull;
                haveCode = true;
            }
            return {codeHash, vu1.state().cycles, ee,
                    command == PS2Vu1Command::Start ? startPc & 0x3FFFu : vu1.state().pc,
                    command == PS2Vu1Command::Continue};
        }

        void finish(Sample sample, const VU1Interpreter &vu1, Clock::duration elapsed)
        {
            std::lock_guard lock(mutex);
            if (vu1.state().cycles < sample.beforeCycles)
                throw std::runtime_error("VU1 profile observed a regressing cycle counter");
            if (count && (sample.ee < lastEe || sample.ee - firstEe >= interval)) flush();
            size_t index = 0;
            for (; index < count; ++index)
                if (rows[index].hash == sample.codeHash && rows[index].pc == sample.pc &&
                    rows[index].resume == sample.resume) break;
            // Fragment a window instead of dropping unbounded new identities.
            if (index == count && count == rows.size()) { flush(); index = 0; }
            if (!count) firstEe = sample.ee;
            lastEe = sample.ee;
            if (index == count)
            {
                rows[count++] = {};
                rows[index].hash = sample.codeHash;
                rows[index].pc = sample.pc;
                rows[index].resume = sample.resume;
            }
            Row &row = rows[index];
            const auto signedNs = std::chrono::duration_cast<std::chrono::nanoseconds>(elapsed).count();
            if (signedNs < 0) throw std::runtime_error("VU1 profile clock regressed");
            const auto ns = static_cast<uint64_t>(signedNs);
            ++row.calls;
            row.cycles += vu1.state().cycles - sample.beforeCycles;
            row.ns += ns;
            if (ns > row.maxNs) row.maxNs = ns;
            row.compiled += vu1.usesCompiledProgram() ? 1u : 0u;
        }

        const uint64_t fromEe;

    private:
        struct Row {
            uint64_t hash = 0, calls = 0, cycles = 0, ns = 0, maxNs = 0, compiled = 0;
            uint32_t pc = 0;
            bool resume = false;
        };
        static uint64_t setting(const char *name, uint64_t fallback)
        {
            const char *text = std::getenv(name);
            if (!text) return fallback;
            uint64_t value = 0;
            const auto end = text + std::strlen(text);
            const auto parsed = std::from_chars(text, end, value);
            if (text == end || parsed.ec != std::errc{} || parsed.ptr != end)
                throw std::invalid_argument("invalid VU1 profile numeric setting");
            return value;
        }
        void flush()
        {
            if (!count) return;
            uint64_t calls = 0, cycles = 0, ns = 0;
            for (size_t i = 0; i < count; ++i)
            { calls += rows[i].calls; cycles += rows[i].cycles; ns += rows[i].ns; }
            output << "{\"kind\":\"window\",\"index\":" << window
                   << ",\"first_ee\":" << firstEe << ",\"last_ee\":" << lastEe
                   << ",\"groups\":" << count << ",\"calls\":" << calls
                   << ",\"cycles\":" << cycles << ",\"nanoseconds\":" << ns << "}\n";
            for (size_t i = 0; i < count; ++i)
            {
                const Row &row = rows[i];
                output << "{\"kind\":\"group\",\"window\":" << window
                       << ",\"code_fnv1a64\":\"" << std::hex << std::setw(16) << std::setfill('0') << row.hash << std::dec
                       << "\",\"start_pc\":" << row.pc << ",\"resume\":" << (row.resume ? "true" : "false")
                       << ",\"calls\":" << row.calls << ",\"cycles\":" << row.cycles
                       << ",\"nanoseconds\":" << row.ns << ",\"max_nanoseconds\":" << row.maxNs
                       << ",\"compiled_calls\":" << row.compiled << "}\n";
            }
            output << "{\"kind\":\"end\",\"index\":" << window++ << "}\n";
            output.flush();
            count = 0;
        }
        std::mutex mutex;
        std::ofstream output;
        const uint64_t interval;
        std::array<uint8_t, PS2_VU1_CODE_SIZE> cachedCode{};
        bool haveCode = false;
        uint64_t codeHash = 0, firstEe = 0, lastEe = 0, window = 0;
        std::array<Row, 128> rows{};
        size_t count = 0;
    };
}

PS2Vu1Completion executePS2Vu1Command(VU1Interpreter &vu1, PS2Memory &memory, GS &gs,
                                     PS2Vu1Command command, PS2Vu1RunControl control,
                                     uint32_t startPc, uint32_t top, uint32_t itop,
                                     uint32_t budget, const PS2Vu1BeforeStart &beforeStart)
{
    if (command != PS2Vu1Command::Start && command != PS2Vu1Command::Continue)
        throw std::invalid_argument("invalid VU1 execution command");
    static const bool profiling = [] {
        const char *directory = std::getenv("PS2X_PROFILE_VU1_DIR");
        return directory && *directory;
    }();
    Vu1CallProfile *profile = nullptr;
    // One evidence stream survives sequential worker lifetimes. Only identity
    // and aggregation take its mutex; actual VU execution remains concurrent.
    if (profiling) { static Vu1CallProfile local; profile = &local; }
    const bool sampleEnabled = profile && control.eeVsync >= profile->fromEe;
    Vu1CallProfile::Sample sample{};
    Vu1CallProfile::Clock::time_point started;
    vu1.state().dBitEnabled = (control.fbrst & (1u << 10)) != 0;
    vu1.state().tBitEnabled = (control.fbrst & (1u << 11)) != 0;
    if (command == PS2Vu1Command::Start && beforeStart) beforeStart(vu1.state(), control);
    if (sampleEnabled) sample = profile->prepare(vu1, memory, command, startPc, control.eeVsync);
    static const bool tracing = [] {
        const char *directory = std::getenv("PS2X_VU1_COMMANDS_DIR");
        return directory && *directory;
    }();
    Vu1CommandTrace *trace = nullptr;
    if (tracing) { static Vu1CommandTrace local; trace = &local; }
    auto traceEntry = trace ? trace->begin(vu1, memory, command, control, startPc, top, itop, budget) : nullptr;
    Vu1PacketCaptureScope packetScope(traceEntry != nullptr || g_vu1CommandGifCollect);
    if (sampleEnabled) started = Vu1CallProfile::Clock::now();
    if (command == PS2Vu1Command::Start)
    {
        vu1.execute(memory.getVU1Code(), PS2_VU1_CODE_SIZE, memory.getVU1Data(), PS2_VU1_DATA_SIZE,
                    gs, &memory, startPc, top, itop, budget);
    }
    else
    {
        vu1.resume(memory.getVU1Code(), PS2_VU1_CODE_SIZE, memory.getVU1Data(), PS2_VU1_DATA_SIZE,
                   gs, &memory, top, itop, budget);
    }
    if (sampleEnabled) profile->finish(sample, vu1, Vu1CallProfile::Clock::now() - started);
    if (traceEntry) trace->finish(*traceEntry, vu1, memory);
    return {(vu1.state().stoppedByD ? 0x0200u : 0u) | (vu1.state().stoppedByT ? 0x0400u : 0u)};
}

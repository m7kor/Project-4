#include "GuestPcProfile.h"

#if defined(PS2X_GUEST_PC_PROFILE)

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <vector>

// A guest-side name would be nice, but the runtime does not own the function
// map - the recompiler's register_functions.cpp does, and it is not linked into
// anything that could answer this without a dependency we do not want. So the
// report prints addresses, and `lodestone triage` resolves them offline against
// analysis/functions.csv. Keeping the two halves separate is deliberate: the
// hot path stays free of lookups, and the report stays machine-readable.

namespace lodestone
{
    namespace
    {
        constexpr uint32_t kDefaultReportInterval = 2000000u; // dispatches

        uint32_t reportInterval()
        {
            if (const char *env = std::getenv("PS2X_PC_PROFILE_INTERVAL"))
            {
                const unsigned long value = std::strtoul(env, nullptr, 10);
                if (value > 0 && value < 0xFFFFFFFFul)
                {
                    return static_cast<uint32_t>(value);
                }
            }
            return kDefaultReportInterval;
        }

        struct Row
        {
            uint32_t pc;
            uint32_t window;
            uint32_t lifetime;
        };
    } // namespace

    GuestPcProfile::GuestPcProfile() = default;

    GuestPcProfile &GuestPcProfile::instance()
    {
        static GuestPcProfile profile;
        return profile;
    }

    uint32_t GuestPcProfile::hashPc(uint32_t pc)
    {
        // Fibonacci hashing. Addresses here are 4-byte aligned and clustered,
        // so the low bits alone would collide badly.
        //
        // The mask is part of the hash, not something the caller applies. Doing
        // it here is the only correct option: the shift below leaves 21 bits,
        // and the first probe indexes m_slots[] BEFORE the probe loop's
        // `(index + 1) & (kSlotCount - 1)` gets a chance to run. Getting this
        // wrong is an out-of-bounds write on the first sample of the run —
        // access violation, zero diagnostics, process gone in 1.3 s. Which is
        // exactly what the first build did.
        return ((pc * 2654435761u) >> 11) & (kSlotCount - 1u);
    }

    void GuestPcProfile::sample(uint32_t pc)
    {
        ++m_totalSamples;

        // Read the override ONCE. Calling std::getenv on every sample made the
        // profiler a measurable fraction of what it was measuring: at
        // interval=1 it reported 71 dispatches/second where the same binary at
        // interval=200 reports 126/second. Recorded as dead_ends.jsonl#0067.
        static const uint32_t interval = reportInterval();

        uint32_t index = hashPc(pc);
        bool settled = false;
        for (uint32_t probe = 0; probe < kProbeLimit; ++probe)
        {
            Slot &slot = m_slots[index];
            if (slot.lifetime == 0)
            {
                slot.pc = pc;
                slot.lifetime = 1;
                slot.window = 1;
                ++m_used;
                settled = true;
                break;
            }
            if (slot.pc == pc)
            {
                ++slot.lifetime;
                ++slot.window;
                settled = true;
                break;
            }
            index = (index + 1) & (kSlotCount - 1);
        }
        if (!settled)
        {
            // Never silently: a full or over-clustered table would otherwise
            // make a hot address look cold, which is the one wrong direction.
            ++m_overflow;
        }

        ++m_sinceReport;
        if (m_sinceReport >= interval)
        {
            reportWindow("periodic");
        }
    }

    void GuestPcProfile::reportWindow(const char *label)
    {
        m_sinceReport = 0;

        std::vector<Row> rows;
        rows.reserve(m_used);
        for (uint32_t i = 0; i < kSlotCount; ++i)
        {
            if (m_slots[i].lifetime == 0 || m_slots[i].window == 0)
            {
                continue;
            }
            rows.push_back({m_slots[i].pc, m_slots[i].window, m_slots[i].lifetime});
        }

        // Window counts are the interesting order for a spin: the address that
        // owns this window is the one to look at. Lifetime is printed beside it
        // so a steady state and a slow drift are distinguishable.
        std::sort(rows.begin(), rows.end(), [](const Row &a, const Row &b)
                  { return a.window > b.window; });

        uint64_t windowTotal = 0;
        for (const Row &row : rows)
        {
            windowTotal += row.window;
        }
        if (windowTotal == 0)
        {
            return;
        }

        ++m_window;
        std::cerr << "[pc-profile] window=" << m_window
                  << " label=" << label
                  << " samples=" << windowTotal
                  << " distinct=" << rows.size()
                  << " table_used=" << m_used
                  << " table_overflow=" << m_overflow
                  << " lifetime_samples=" << m_totalSamples
                  << "\n";

        const size_t topN = std::min<size_t>(rows.size(), 12);
        for (size_t i = 0; i < topN; ++i)
        {
            const double pct = 100.0 * static_cast<double>(rows[i].window) /
                               static_cast<double>(windowTotal);
            std::cerr << "[pc-profile]   #" << (i + 1)
                      << " pc=0x" << std::hex << rows[i].pc << std::dec
                      << " window=" << rows[i].window
                      << " lifetime=" << rows[i].lifetime
                      << " window_pct=" << pct << "%\n";
        }
        std::cerr.flush();

        uint64_t phaseTotal = 0;
        for (uint32_t i = 0; i < GuestPcProfile::kPhaseCount; ++i)
        {
            phaseTotal += m_phaseMicros[i];
        }
        if (phaseTotal > 0)
        {
            static const char *kNames[GuestPcProfile::kPhaseCount] = {
                "events", "checkpoint", "guest", "other"};
            uint64_t callTotal = 0;
            for (uint32_t i = 0; i < GuestPcProfile::kPhaseCount; ++i)
            {
                callTotal += m_phaseCalls[i];
            }
            std::cerr << "[pc-profile]   host-phase us="
                      << phaseTotal
                      << "  per-dispatch us="
                      << (windowTotal ? (phaseTotal / windowTotal) : 0);
            for (uint32_t i = 0; i < GuestPcProfile::kPhaseCount; ++i)
            {
                std::cerr << "  " << kNames[i] << "="
                          << m_phaseMicros[i] << "us"
                          << (100.0 * static_cast<double>(m_phaseMicros[i]) /
                                  static_cast<double>(phaseTotal))
                          << "% n=" << m_phaseCalls[i]
                          << " avg=" << (m_phaseCalls[i] ? (m_phaseMicros[i] / m_phaseCalls[i]) : 0)
                          << "us";
                m_phaseMicros[i] = 0;
                m_phaseCalls[i] = 0;
            }
            std::cerr << "\n";
            std::cerr.flush();
        }

        // Reset per-window counters, keep lifetime. A spot that only appears in
        // one window is transient; one that tops every window is the loop.
        for (uint32_t i = 0; i < kSlotCount; ++i)
        {
            m_slots[i].window = 0;
        }
    }

    void GuestPcProfile::reportTotals()
    {
        std::vector<Row> rows;
        rows.reserve(m_used);
        for (uint32_t i = 0; i < kSlotCount; ++i)
        {
            if (m_slots[i].lifetime == 0)
            {
                continue;
            }
            rows.push_back({m_slots[i].pc, m_slots[i].window, m_slots[i].lifetime});
        }
        std::sort(rows.begin(), rows.end(), [](const Row &a, const Row &b)
                  { return a.lifetime > b.lifetime; });

        std::cerr << "[pc-profile] TOTAL dispatches=" << m_totalSamples
                  << " distinct=" << rows.size()
                  << " table_used=" << m_used << "\n";
        const size_t topN = std::min<size_t>(rows.size(), 20);
        for (size_t i = 0; i < topN; ++i)
        {
            const double pct = 100.0 * static_cast<double>(rows[i].lifetime) /
                               static_cast<double>(m_totalSamples ? m_totalSamples : 1);
            std::cerr << "[pc-profile]   #" << (i + 1)
                      << " pc=0x" << std::hex << rows[i].pc << std::dec
                      << " lifetime=" << rows[i].lifetime
                      << " pct=" << pct << "%\n";
        }
        std::cerr.flush();
    }

    void reportGuestPcWindow(const char *label)
    {
        GuestPcProfile::instance().reportWindow(label);
    }

    void reportGuestPcTotals()
    {
        GuestPcProfile::instance().reportTotals();
    }
} // namespace lodestone

#endif // PS2X_GUEST_PC_PROFILE
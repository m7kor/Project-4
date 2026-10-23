#ifndef LODESTONE_GUEST_PC_PROFILE_H
#define LODESTONE_GUEST_PC_PROFILE_H

// LODESTONE PATCH 12 — guest PC sampling profile.
//
// WHY THIS EXISTS
//
// RE4 reached the end of its resolved syscall path (the SetSyscall 0x83 loop
// now exits after three iterations, dead_ends#0063) and then went silent: no
// syscall, no branch diagnostic, no crash, no frame, for 40+ seconds.
//
// That silence is the worst failure mode this project has, because every
// instrument we own keys off a control-flow EVENT. No event means no report,
// and a report that cannot fire is indistinguishable from a report that is
// broken. The question "is the guest spinning, or working?" had no answer.
//
// Dispatch-level PC sampling answers it in one run: a spin collapses onto one
// address, real work spreads across thousands.
//
// WHY IT IS COMPILE-TIME GATED, NOT ENV-GATED
//
// Red-tv141/DC2 measured the general form of this mistake and it is worth
// respecting rather than rediscovering:
//
//   12c  "a const bool guard does not make diagnostic code free" - ~60
//         never-executed const-bool-guarded lines cost +0.484 ms/frame with
//         zero behavioural difference, and "no env rollback can ever recover
//         it". Diagnostic code in a hot TU must be a compile-time mode with
//         #if-excluded call sites, reporter in a separate TU.
//   16    a default-OFF family was still 121,285 bytes / 1,059 COMDATs =
//         8.52% of a TU's machine code; #if-excluding it removed 134,807 bytes
//         for -1.082 ms/f.
//
// EeScheduler::run is the hottest loop in the entire runtime. So: default OFF,
// every call site #if'd out, and this file is compiled only when ON. An OFF
// build links exactly as if this feature did not exist.
//
// REPORTING IS PERIODIC, NOT AT-EXIT
//
// A profile that dumps when the process exits normally is useless for the
// failure we are chasing, because the process has to be killed to observe it.
// Deltas are therefore emitted on a sample budget, so a SIGKILL still leaves
// the last window on stderr.

#include <cstdint>
#include <chrono>
#include <string>

namespace lodestone
{
#if defined(PS2X_GUEST_PC_PROFILE)

    // Open-addressed, fixed capacity, allocation-free after construction.
    // A std::unordered_map here would allocate and contend inside the hottest
    // loop in the runtime; this touches one array and never allocates.
    class GuestPcProfile
    {
    public:
        static GuestPcProfile &instance();

        // Called once per guest dispatch from EeScheduler::run. Must stay
        // branch-light: this runs millions of times a second.
        void sample(uint32_t pc);

        // Emits the top-N addresses accumulated since the previous report,
        // oldest window first, and resets the per-window counters (NOT the
        // lifetime totals). Never throws.
        void reportWindow(const char *label);

        // Lifetime totals since process start, for a whole-run summary.
        void reportTotals();

        uint64_t totalSamples() const { return m_totalSamples; }
        uint32_t overflow() const { return m_overflow; }

        // Phase accounting. The PC histogram says WHERE the guest is; it cannot
        // say what the host spent doing about it, and on RE4 that turned out to
        // be the entire story - 126 dispatches/second means ~7.9 ms of host CPU
        // per guest loop iteration, and the loop body is five instructions.
        //
        // Two wrong answers came out of guessing before this existed
        // (dead_ends#0069, #0070). This exists so the next one is a number.
        enum class Phase : uint32_t
        {
            Events = 0,    // processPendingEvents + processDueDeadlines
            Checkpoint,    // checkpointDue / accountCycles / timers / IOP
            Guest,         // the recompiled function itself
            Other,         // reschedule bookkeeping
            Count_
        };

        static constexpr uint32_t kPhaseCount = static_cast<uint32_t>(Phase::Count_);

        // A start time PER PHASE, not one shared start time.
//
// The first version shared one `m_phaseStart`, and that is wrong the moment a
// phase nests inside another: eeCheckpointDue() is called from inside the guest
// function, so its phaseBegin() overwrote the guest function's start, and the
// enclosing Guest phase measured only the time since the last nested call. It
// reported guest=0us, which is obviously false, and reporting an obviously
// false number from an instrument is how an instrument stops being believed.
// Per-phase starts cannot collide because no phase re-enters itself:
// checkpointDue() does not call eeCheckpointDue().
//
// Note that with per-phase starts the phases are no longer a partition - Guest
// includes the checkpoint time nested inside it. That is deliberate and is why
// the report prints percentages of the accounted total rather than claiming a
// decomposition.
void phaseBegin(Phase phase) noexcept
        {
            m_phaseStart[static_cast<uint32_t>(phase)] = std::chrono::steady_clock::now();
        }

        void phaseAdd(Phase phase) noexcept
        {
            const uint32_t i = static_cast<uint32_t>(phase);
            m_phaseMicros[i] += std::chrono::duration_cast<std::chrono::microseconds>(
                                    std::chrono::steady_clock::now() - m_phaseStart[i])
                                    .count();
            ++m_phaseCalls[i];
        }

        uint64_t phaseMicros(uint32_t index) const { return m_phaseMicros[index]; }
        uint64_t phaseCalls(uint32_t index) const { return m_phaseCalls[index]; }

    private:
        GuestPcProfile();

        struct Slot
        {
            uint32_t pc;
            uint32_t window;
            uint32_t lifetime;
            uint32_t pad;
        };

        static constexpr uint32_t kSlotCount = 1u << 17; // 128 Ki entries, 2 MiB
        static constexpr uint32_t kProbeLimit = 8u;

        Slot m_slots[kSlotCount]{};
        uint32_t m_used = 0;
        uint32_t m_overflow = 0;
        uint32_t m_window = 0;
        uint64_t m_totalSamples = 0;
        uint32_t m_sinceReport = 0;

        uint64_t m_phaseMicros[kPhaseCount]{};
        uint64_t m_phaseCalls[kPhaseCount]{};
        std::chrono::steady_clock::time_point m_phaseStart[kPhaseCount]{};

        static uint32_t hashPc(uint32_t pc);
    };

    // Call sites compile to nothing when the feature is off.
    inline void sampleGuestPc(uint32_t pc)
    {
        GuestPcProfile::instance().sample(pc);
    }

    void reportGuestPcWindow(const char *label);
    void reportGuestPcTotals();

#else

    inline void sampleGuestPc(uint32_t)
    {
    }
    inline void reportGuestPcWindow(const char *)
    {
    }
    inline void reportGuestPcTotals()
    {
    }

#endif // PS2X_GUEST_PC_PROFILE
} // namespace lodestone

#endif // LODESTONE_GUEST_PC_PROFILE_H
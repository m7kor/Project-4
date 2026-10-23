// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <functional>

class VU1Interpreter;
struct VU1State;
class PS2Memory;
class GS;

// Captured by EE at publication. Execution never receives a CPU context or
// scheduler; the worker must not query either while consuming this value.
struct PS2Vu1RunControl
{
    uint32_t fbrst = 0;
    uint64_t eeVsync = 0;
};

struct PS2Vu1Completion
{
    uint32_t statusBits = 0;
    // Enabled D and T stops both request INTC_VU1 (cause 7). An ordinary
    // E stop or a cycle-budget return does not request this interrupt.
    bool requestsInterrupt() const { return (statusBits & 0x0600u) != 0u; }
    // Applied by EE after synchronization, preserving unrelated VU0/EE bits
    // as they are at retirement (not as they were when work was published).
    uint32_t mergeStatus(uint32_t current) const
    {
        return (current & ~0x0600u) | (statusBits & 0x0600u);
    }
};

enum class PS2Vu1Command { Start, Continue };
using PS2Vu1BeforeStart = std::function<void(const VU1State &, const PS2Vu1RunControl &)>;

// Caller owns VU1, its memory and GS for the whole command. No EE state is
// accessed: control comes in by value and the status result comes back by value.
PS2Vu1Completion executePS2Vu1Command(VU1Interpreter &vu1, PS2Memory &memory, GS &gs,
                                     PS2Vu1Command command, PS2Vu1RunControl control,
                                     uint32_t startPc, uint32_t top, uint32_t itop,
                                     uint32_t budget = 65536,
                                     const PS2Vu1BeforeStart &beforeStart = {});

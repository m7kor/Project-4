#include "iop_vblank.h"

#include "../core/iop_cpu.h"
#include "../iop_emulator_const.h"
#include "../core/iop_kernel.h"
#include "iop_intrman.h"
#include "../services/iop_rpc.h"
#include <algorithm>
#include <cstdlib>
#include <iostream>

namespace ps2x::iop::detail
{
    IopVblank::IopVblank(IopKernel &kernel, IopIntrman &intrman) noexcept
        : m_kernel(kernel), m_intrman(intrman)
    {
        reset();
    }

    void IopVblank::reset()
    {
        for (auto &list : m_handlers) list.clear();
        m_next = {kVblankPeriodCycles, kVblankEndPhaseCycles};
        m_pending = {UINT64_MAX, UINT64_MAX};
        m_servicing = false; m_traceCount = 0;
    }

    bool IopVblank::dispatchImport(uint16_t ordinal, IopCpuState &cpu, uint64_t currentCycle)
    {
        switch (ordinal)
        {
        case 4: // WaitVblankStart
        case 5: // WaitVblankEnd
        case 6: // WaitVblank
        case 7: // WaitNonVblank
        {
            const bool waitForEnd = ordinal == 5u || ordinal == 7u;
            const uint64_t phase = waitForEnd ? kVblankEndPhaseCycles : 0u;
            const uint64_t fieldStart = currentCycle - (currentCycle % kVblankPeriodCycles);
            uint64_t wakeCycle = fieldStart + phase;
            if (wakeCycle <= currentCycle)
                wakeCycle += kVblankPeriodCycles;
            m_kernel.delayCurrentUntil(wakeCycle, cpu);
            cpu.gpr[2] = 0u;
            return true;
        }
        case 8: // RegisterVblankHandler
        case 9: // ReleaseVblankHandler
        {
            // ABI and lifetime follow PS2SDK iop/system/vblank/src/vblank.c:
            // smaller priorities first; equal priorities keep registration order;
            // return zero from a callback removes it. Two of 16 ROM records
            // belong to the service's own start/end wait handlers.
            if (m_intrman.inInterruptContext())
            { cpu.gpr[2] = static_cast<uint32_t>(-100); return true; }
            const unsigned phase = cpu.gpr[4] != 0 ? 1 : 0;
            auto &list = m_handlers[phase];
            const uint32_t function = cpu.gpr[ordinal == 8 ? 6 : 5];
            const auto found = std::find_if(list.begin(), list.end(),
                [&](const Handler &h) { return h.function == function; });
            if (ordinal == 9)
            {
                if (found == list.end()) { cpu.gpr[2] = static_cast<uint32_t>(-105); return true; }
                list.erase(found);
                if (list.empty()) m_pending[phase] = UINT64_MAX;
            }
            else
            {
                if (m_handlers[0].size() + m_handlers[1].size() >= 14)
                { cpu.gpr[2] = static_cast<uint32_t>(-400); return true; }
                if (found != list.end()) { cpu.gpr[2] = static_cast<uint32_t>(-104); return true; }
                if (list.empty())
                {
                    m_next[phase] = currentCycle - currentCycle % kVblankPeriodCycles +
                                    (phase ? kVblankEndPhaseCycles : 0);
                    if (m_next[phase] <= currentCycle) m_next[phase] += kVblankPeriodCycles;
                }
                const int32_t priority = static_cast<int32_t>(cpu.gpr[5]);
                const auto position = std::find_if(list.begin(), list.end(),
                    [&](const Handler &h) { return h.priority > priority; });
                list.insert(position, {function, cpu.gpr[7], cpu.gpr[28], priority});
            }
            cpu.gpr[2] = 0u;
            return true;
        }
        default:
            return false;
        }
    }

    void IopVblank::serviceDue(uint64_t currentCycle, IopGuestExecutor &executor)
    {
        // Called after every IOP instruction: nothing due and nothing pending
        // is the common case.
        if (m_next[0] > currentCycle && m_next[1] > currentCycle &&
            m_pending[0] == UINT64_MAX && m_pending[1] == UINT64_MAX)
            return;
        if (m_servicing) return;
        m_servicing = true;
        struct Guard { bool &flag; ~Guard() { flag = false; } } guard{m_servicing};
        for (unsigned phase = 0; phase < 2; ++phase)
        {
            if (m_next[phase] <= currentCycle)
            {
                if (!m_handlers[phase].empty() && m_pending[phase] == UINT64_MAX)
                    m_pending[phase] = m_next[phase];
                // An IRQ pending while masked coalesces fields rather than
                // replaying thousands of callbacks after an idle fast-forward.
                m_next[phase] += ((currentCycle - m_next[phase]) / kVblankPeriodCycles + 1) * kVblankPeriodCycles;
            }
        }
        const unsigned first = m_pending[0] <= m_pending[1] ? 0 : 1;
        for (const unsigned phase : {first, 1 - first})
        {
            if (m_pending[phase] == UINT64_MAX || !m_intrman.canDispatchServiceInterrupt(phase ? 11 : 0)) continue;
            m_pending[phase] = UINT64_MAX;
            const auto handlers = m_handlers[phase];
            for (const auto &handler : handlers)
            {
                const uint32_t result = m_intrman.executeInterruptCallback(handler.function, handler.argument, handler.gp, executor);
                const bool completed = executor.lastGuestCallCompleted();
                if (std::getenv("PS2X_TRACE_IOP_VBLANK") && m_traceCount++ < 64)
                    std::cerr << "[IOP VBlank callback] phase=" << phase << " cycles=" << currentCycle
                              << " function=0x" << std::hex << handler.function << " v0=0x" << result
                              << std::dec << " completed=" << completed << '\n';
                if (completed && result == 0)
                    std::erase_if(m_handlers[phase], [&](const Handler &h) { return h.function == handler.function; });
            }
        }
    }

    uint64_t IopVblank::nextEventCycle(uint64_t fallback) const noexcept
    {
        for (unsigned phase = 0; phase < 2; ++phase)
            if (!m_handlers[phase].empty()) fallback = std::min(fallback, m_next[phase]);
        return fallback;
    }
}

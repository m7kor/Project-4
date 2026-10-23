#include "iop_intrman.h"

#include "../core/iop_cpu.h"
#include "../core/iop_memory.h"
#include "../services/iop_rpc.h"
#include <cstdlib>
#include <iostream>

namespace ps2x::iop::detail
{
    IopIntrman::IopIntrman(IopMemory &memory) noexcept
        : m_memory(memory)
    {
    }

    void IopIntrman::reset()
    {
        m_handlers.clear();
        m_enabled.clear();
        m_interruptDepth = 0u;
    }

    bool IopIntrman::dispatchImport(uint16_t ordinal, IopCpuState &cpu, IopGuestExecutor &executor)
    {
        const uint32_t a0 = cpu.gpr[4];
        const uint32_t a1 = cpu.gpr[5];
        const uint32_t a2 = cpu.gpr[6];
        const uint32_t a3 = cpu.gpr[7];
        const auto setV0 = [&](uint32_t value)
        {
            cpu.gpr[2] = value;
        };
        if ([] { static const char *const cached = std::getenv("PS2X_TRACE_IOP_IRQ"); return cached; }() && ordinal >= 4u && ordinal <= 9u)
        {
            static uint32_t traceCount = 0u;
            if (traceCount++ < 128u)
                std::cerr << "[IOP IRQ import] ordinal=" << ordinal << " pc=0x" << std::hex << cpu.pc
                          << " ra=0x" << cpu.gpr[31] << " a0=0x" << a0 << " a1=0x" << a1
                          << " a2=0x" << a2 << " a3=0x" << a3 << " gp=0x" << cpu.gpr[28]
                          << std::dec << '\n';
        }

        switch (ordinal)
        {
        case 3:
            setV0(0u);
            return true;
        case 4: // RegisterIntrHandler
            m_handlers[static_cast<int>(a0)] = {a2, a3, cpu.gpr[28]};
            setV0(0u);
            return true;
        case 5: // ReleaseIntrHandler
            m_handlers.erase(static_cast<int>(a0));
            setV0(0u);
            return true;
        case 6: // EnableIntr
            m_enabled[static_cast<int>(a0)] = true;
            if (a0 < 32u)
                m_memory.setInterruptMask(m_memory.interruptMask() | (1u << a0));
            setV0(0u);
            return true;
        case 7: // DisableIntr
            if (a1 != 0u)
                m_memory.write32(a1, a0);
            if (a0 < 32u)
                m_memory.setInterruptMask(m_memory.interruptMask() & ~(1u << a0));
            m_enabled[static_cast<int>(a0)] = false;
            setV0(0u);
            return true;
        case 8: // CpuDisableIntr
        {
            const uint32_t previous = m_memory.interruptControl();
            m_memory.setInterruptControl(0u);
            setV0(previous != 0u ? 0u : static_cast<uint32_t>(-102)); // KE_CPUDI
            return true;
        }
        case 9: // CpuEnableIntr
            m_memory.setInterruptControl(1u);
            setV0(0u);
            return true;
        case 14:
            setV0(a0 != 0u
                      ? executor.executeGuestFunctionWithBudget(a0, a1, a2, a3, 0u, cpu.gpr[28], 100000u)
                      : 0u);
            return true;
        case 15:
        case 16:
        case 24:
        case 25:
        case 28:
        case 30:
            setV0(0u);
            return true;
        case 23: // QueryIntrContext
            setV0(m_interruptDepth != 0u ? 1u : 0u);
            return true;
        case 17: // CpuSuspendIntr
        {
            const uint32_t previous = m_memory.interruptControl();
            if (a0 != 0u)
                m_memory.write32(a0, previous);
            m_memory.setInterruptControl(0u);
            setV0(previous != 0u ? 0u : static_cast<uint32_t>(-102)); // KE_CPUDI
            return true;
        }
        case 18:
            m_memory.setInterruptControl(a0 != 0u ? 1u : 0u);
            setV0(0u);
            return true;
        default:
            return false;
        }
    }

    bool IopIntrman::canDispatchInterrupt(int irq) const
    {
        const auto enabled = m_enabled.find(irq);
        const auto handler = m_handlers.find(irq);
        return m_memory.interruptControl() != 0u && enabled != m_enabled.end() && enabled->second &&
               handler != m_handlers.end() && handler->second.function != 0u;
    }

    bool IopIntrman::dispatchInterrupt(int irq, IopGuestExecutor &executor) const
    {
        const auto enabled = m_enabled.find(irq);
        const auto handler = m_handlers.find(irq);
        static uint32_t traceCount = 0u;
        const bool trace = [] { static const char *const cached = std::getenv("PS2X_TRACE_IOP_IRQ"); return cached; }() && traceCount++ < 128u;
        if (trace)
            std::cerr << "[IOP IRQ dispatch] irq=0x" << std::hex << irq
                      << " enabled=" << (enabled != m_enabled.end() && enabled->second)
                      << " handler=0x" << (handler != m_handlers.end() ? handler->second.function : 0u)
                      << " argument=0x" << (handler != m_handlers.end() ? handler->second.argument : 0u)
                      << " control=0x" << m_memory.interruptControl() << std::dec << '\n';
        if (!canDispatchInterrupt(irq))
            return false;

        const uint32_t result = executeInterruptCallback(handler->second.function,
                                                        handler->second.argument,
                                                        handler->second.gp, executor);
        if (trace)
            std::cerr << "[IOP IRQ return] irq=0x" << std::hex << irq << " v0=0x" << result
                      << " completed=" << executor.lastGuestCallCompleted() << std::dec << '\n';
        return true;
    }

    bool IopIntrman::canDispatchServiceInterrupt(int irq) const
    {
        const auto enabled = m_enabled.find(irq);
        return m_memory.interruptControl() != 0 &&
               (enabled == m_enabled.end() || enabled->second);
    }

    uint32_t IopIntrman::executeInterruptCallback(uint32_t function, uint32_t argument,
                                                 uint32_t gp, IopGuestExecutor &executor) const
    {
        // Keep nested guest calls in ISR context, and unwind it on every exit.
        struct InterruptContextGuard
        {
            uint32_t &depth;
            explicit InterruptContextGuard(uint32_t &value) : depth(value) { ++depth; }
            ~InterruptContextGuard() { --depth; }
        } context(m_interruptDepth);
        return executor.executeGuestFunctionWithBudget(function,
                                                      argument,
                                                      0u,
                                                      0u,
                                                      0u,
                                                      gp,
                                                      100000u);
    }
}

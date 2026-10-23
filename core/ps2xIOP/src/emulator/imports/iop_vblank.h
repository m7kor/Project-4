#pragma once

#include <cstdint>
#include <array>
#include <vector>

namespace ps2x::iop::detail
{
    struct IopCpuState;
    class IopKernel;
    class IopIntrman;
    class IopGuestExecutor;

    class IopVblank
    {
    public:
        explicit IopVblank(IopKernel &kernel, IopIntrman &intrman) noexcept;
        void reset();

        [[nodiscard]] bool dispatchImport(uint16_t ordinal, IopCpuState &cpu, uint64_t currentCycle);
        void serviceDue(uint64_t currentCycle, IopGuestExecutor &executor);
        [[nodiscard]] uint64_t nextEventCycle(uint64_t fallback) const noexcept;

    private:
        IopKernel &m_kernel;
        IopIntrman &m_intrman;
        struct Handler { uint32_t function, argument, gp; int32_t priority; };
        std::array<std::vector<Handler>, 2> m_handlers;
        std::array<uint64_t, 2> m_next{}, m_pending{};
        bool m_servicing = false;
        uint32_t m_traceCount = 0;
    };
}

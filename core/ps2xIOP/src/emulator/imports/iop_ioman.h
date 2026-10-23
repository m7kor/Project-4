#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <map>
#include "iop_cdvd.h"

namespace ps2x::iop::detail
{
    struct IopCpuState;
    class IopGuestExecutor;
    class IopMemory;

    class IopIoman
    {
    public:
        IopIoman(IopMemory &memory, IopCdvd &cdvd) noexcept;

        void reset();
        [[nodiscard]] bool dispatchImport(uint16_t ordinal, IopCpuState &cpu, IopGuestExecutor &executor);

    private:
        struct Device
        {
            uint32_t address = 0u;
            uint32_t gp = 0u;
            std::string name;
        };
        struct OpenFile { IopCdvd::FileHandle file; uint32_t offset = 0u; };

        IopMemory &m_memory;
        IopCdvd &m_cdvd;
        std::vector<Device> m_devices;
        std::map<int, OpenFile> m_files;
        int m_nextFile = 3;
    };
}

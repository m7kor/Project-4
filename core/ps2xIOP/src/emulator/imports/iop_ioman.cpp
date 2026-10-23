#include "iop_ioman.h"

#include "../core/iop_cpu.h"
#include "../core/iop_memory.h"
#include "iop_cdvd.h"
#include "../services/iop_rpc.h"

#include <algorithm>

namespace ps2x::iop::detail
{
    IopIoman::IopIoman(IopMemory &memory, IopCdvd &cdvd) noexcept
        : m_memory(memory), m_cdvd(cdvd)
    {
    }

    void IopIoman::reset()
    {
        m_devices.clear();
        m_files.clear();
        m_nextFile = 3;
    }

    bool IopIoman::dispatchImport(uint16_t ordinal, IopCpuState &cpu, IopGuestExecutor &executor)
    {
        constexpr size_t kMaxDevices = 16u;
        const uint32_t a0 = cpu.gpr[4];
        const uint32_t a1 = cpu.gpr[5];
        const uint32_t a2 = cpu.gpr[6];
        const auto setV0 = [&](uint32_t value)
        {
            cpu.gpr[2] = value;
        };

        switch (ordinal)
        {
        case 4: {
            const auto file = m_cdvd.openFile(m_memory.readString(a0, 1024u));
            if (!file) { setV0(0xfffffffbu); return true; }
            const int fd = m_nextFile++;
            m_files.emplace(fd, OpenFile{*file, 0u});
            setV0(static_cast<uint32_t>(fd));
            return true;
        }
        case 5:
            setV0(m_files.erase(static_cast<int>(a0)) ? 0u : 0xfffffffbu);
            return true;
        case 6: {
            const auto it = m_files.find(static_cast<int>(a0));
            if (it == m_files.end() || !m_memory.ownsRamRange(a1, a2)) { setV0(0xfffffffbu); return true; }
            std::vector<uint8_t> bytes(a2);
            const size_t got = m_cdvd.readFile(it->second.file, it->second.offset, bytes.data(), bytes.size());
            if (got) m_memory.writeRam(a1, bytes.data(), got);
            it->second.offset += static_cast<uint32_t>(got);
            setV0(static_cast<uint32_t>(got));
            return true;
        }
        case 8: {
            const auto it = m_files.find(static_cast<int>(a0));
            if (it == m_files.end()) { setV0(0xfffffffbu); return true; }
            const int32_t amount = static_cast<int32_t>(a1);
            const int32_t mode = static_cast<int32_t>(a2);
            int64_t position = mode == 0 ? amount : mode == 1 ? static_cast<int64_t>(it->second.offset) + amount : static_cast<int64_t>(it->second.file.size) + amount;
            position = std::clamp<int64_t>(position, 0, it->second.file.size);
            it->second.offset = static_cast<uint32_t>(position);
            setV0(it->second.offset);
            return true;
        }
        case 31: // iomanX_devctl (present in the ioman 1.4 import table)
        {
            const uint32_t command = cpu.gpr[5];
            const uint32_t buffer = m_memory.read32(cpu.gpr[29] + 16u);
            const uint32_t bufferLength = m_memory.read32(cpu.gpr[29] + 20u);
            // CDVDMAN uses 0x4391 to expose its interrupt event flag to FILEIO.
            // The result is written to the caller's output buffer and the devctl
            // itself returns zero, matching cdvdman's ioctl implementation.
            if (command == 0x4391u && buffer != 0u && bufferLength >= 4u)
            {
                IopCpuState context{};
                context.gpr[4] = 0xfffffff5u; // sceCdSC(-11): CDVD interrupt event flag
                if (!m_cdvd.dispatchImport(50u, context))
                {
                    setV0(0xfffffffbu); // -EIO
                    return true;
                }
                m_memory.write32(buffer, context.gpr[2]);
                setV0(0u);
                return true;
            }
            setV0(0xfffffffbu); // unsupported device-control request
            return true;
        }
        case 20: // AddDrv
        {
            if (a0 == 0u || m_devices.size() >= kMaxDevices)
            {
                setV0(0xFFFFFFFFu);
                return true;
            }

            const uint32_t nameAddress = m_memory.read32(a0);
            const uint32_t operations = m_memory.read32(a0 + 16u);
            const std::string name = m_memory.readString(nameAddress, 64u);
            if (nameAddress == 0u || operations == 0u || name.empty())
            {
                setV0(0xFFFFFFFFu);
                return true;
            }

            m_devices.push_back({a0, cpu.gpr[28], name});
            const uint32_t init = m_memory.read32(operations);
            if (init != 0u)
            {
                const int32_t result = static_cast<int32_t>(
                    executor.executeGuestFunction(init, a0, 0u, 0u, 0u, cpu.gpr[28]));
                if (result < 0)
                {
                    m_devices.pop_back();
                    setV0(0xFFFFFFFFu);
                    return true;
                }
            }

            setV0(0u);
            return true;
        }
        case 21: // DelDrv
        {
            const std::string name = m_memory.readString(a0, 64u);
            const auto device = std::find_if(
                m_devices.begin(), m_devices.end(),
                [&](const Device &candidate)
                { return candidate.name == name; });
            if (device == m_devices.end())
            {
                setV0(0xFFFFFFFFu);
                return true;
            }

            const uint32_t operations = m_memory.read32(device->address + 16u);
            const uint32_t deinit = operations != 0u ? m_memory.read32(operations + 4u) : 0u;
            if (deinit != 0u)
                (void)executor.executeGuestFunction(deinit, device->address, 0u, 0u, 0u, device->gp);
            m_devices.erase(device);
            setV0(0u);
            return true;
        }
        default:
            return false;
        }
    }
}

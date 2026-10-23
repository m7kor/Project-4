#pragma once

#include "../core/iop_cpu.h"
#include "../core/iop_memory.h"

namespace ps2x::iop::detail
{
    // DMACMAN register access imports share the same MMIO as guest load/store.
    // Transfer execution remains the responsibility of the device backend.
    inline bool dispatchDmacmanRegister(IopMemory &memory, uint16_t ordinal, IopCpuState &cpu)
    {
        if ((ordinal < 4u || ordinal > 9u) && ordinal != 28u && ordinal != 32u)
            return false;
        const uint32_t channel = cpu.gpr[4];
        if (channel > 12u)
        {
            cpu.gpr[2] = 0u;
            return true;
        }
        const uint32_t base = channel < 7u ? 0x1F801080u + channel * 16u
                                          : 0x1F801500u + (channel - 7u) * 16u;
        if (ordinal == 28u) // sceSetSliceDMA(channel, addr, words, blocks, dir)
        {
            // PS2SDK rejects OTC; IOP o32 passes direction on the stack.
            if (channel == 6u)
            {
                cpu.gpr[2] = 0u;
                return true;
            }
            const uint32_t direction = memory.read32(cpu.gpr[29] + 16u);
            memory.write32(base, cpu.gpr[5] & 0x00FFFFFFu);
            memory.write32(base + 4u, (cpu.gpr[6] & 0xFFFFu) | (cpu.gpr[7] << 16u));
            memory.write32(base + 8u, (direction & 1u) | 0x200u |
                                     (direction == 0u ? 0x40000000u : 0u));
            cpu.gpr[2] = 1u;
            return true;
        }
        if (ordinal == 32u) // sceStartDMA; completion belongs to the device.
        {
            memory.write32(base + 8u, memory.read32(base + 8u) | 0x01000000u);
            cpu.gpr[2] = 0u;
            return true;
        }
        const uint32_t address = base + ((ordinal - 4u) / 2u) * 4u;
        if ((ordinal & 1u) != 0u)
            cpu.gpr[2] = memory.read32(address);
        else
        {
            memory.write32(address, cpu.gpr[5]);
            cpu.gpr[2] = 0u;
        }
        return true;
    }
}

#pragma once
#include <cstdint>
#include <memory>
#include <span>

namespace ps2x::iop::detail
{
    // Callbacks are latched here; no guest code runs inside the sound backend.
    class IopSpu2
    {
    public:
        virtual ~IopSpu2() = default;
        virtual void reset(uint64_t cycle) = 0;
        virtual uint16_t read16(uint32_t address, uint64_t cycle) = 0;
        virtual void write16(uint32_t address, uint16_t value, uint64_t cycle) = 0;
        virtual void startDma(unsigned core, uint16_t *ram, uint32_t halfwords,
                              uint32_t madr, bool write, uint64_t cycle) = 0;
        virtual uint32_t dmaMadr(unsigned core) const = 0;
        virtual void advance(uint64_t cycle) = 0;
        virtual uint64_t nextEvent() const = 0;
        virtual uint32_t takeEvents() = 0; // bit 0 SPU IRQ; bits 1/2 DMA cores 0/1
        virtual uint32_t readSamples(int16_t *stereo, uint32_t frames) = 0;
    };
    std::unique_ptr<IopSpu2> createNativeSpu2(std::span<uint8_t> ram);
}

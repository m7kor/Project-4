#include "iop_spu2.h"
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#if defined(PS2X_NATIVE_SPU2)
#include "kzspu2.h"
#endif

namespace ps2x::iop::detail
{
#if defined(PS2X_NATIVE_SPU2)
    namespace
    {
        bool occupied = false; // kzspu2 has one isolated process-wide hardware instance.
        class NativeSpu2 final : public IopSpu2
        {
        public:
            explicit NativeSpu2(std::span<uint8_t> ram)
            {
                if (occupied) throw std::runtime_error("native SPU2 instance already in use");
                KzSpu2Config config;
                config.user = this;
                config.irq = [](void *user) { static_cast<NativeSpu2 *>(user)->events |= 1u; };
                config.dmaComplete = [](void *user, int core) {
                    if (core >= 0 && core < 2) static_cast<NativeSpu2 *>(user)->events |= 2u << core;
                };
                if (!kzspu2Init(config)) throw std::runtime_error("native SPU2 initialization failed");
                occupied = true;
                kzspu2SetIopRam(ram.data(), static_cast<uint32_t>(ram.size()));
            }
            ~NativeSpu2() override { kzspu2Shutdown(); occupied = false; }
            // kzspu2 ignores a clock that goes backwards, but an IOP reboot
            // (sceSifRebootIop / UDNL) restarts the IOP clock at zero. Keep the
            // backend clock monotonic with an offset; otherwise mixing and DMA
            // progress stop until the new IOP clock passes the old one.
            void reset(uint64_t cycle) override
            {
                const uint64_t backendNow = kzspu2GetStatus(false).iopCycle;
                offset = backendNow > cycle ? backendNow - cycle : 0u;
                events = 0;
                nextTrace = 0;
                kzspu2Reset(cycle + offset);
            }
            uint16_t read16(uint32_t address, uint64_t cycle) override { return kzspu2Read16(address, cycle + offset); }
            void write16(uint32_t address, uint16_t value, uint64_t cycle) override { kzspu2Write16(address, value, cycle + offset); }
            void startDma(unsigned core, uint16_t *ram, uint32_t size, uint32_t madr, bool write, uint64_t cycle) override
            {
                if (write) kzspu2DmaWrite(static_cast<int>(core), ram, size, madr, cycle + offset);
                else kzspu2DmaRead(static_cast<int>(core), ram, size, madr, cycle + offset);
            }
            uint32_t dmaMadr(unsigned core) const override { return kzspu2DmaMadr(static_cast<int>(core)); }
            void advance(uint64_t cycle) override
            {
                kzspu2Advance(cycle + offset);
                // PS2X_TRACE_SPU2: one status line per ~5 s of IOP time.
                static const bool trace = [] { const char *v = std::getenv("PS2X_TRACE_SPU2"); return v && *v && *v != '0'; }();
                if (trace && cycle >= nextTrace)
                {
                    nextTrace = cycle + 36864000ull * 5u;
                    const KzSpu2Status s = kzspu2GetStatus(true);
                    std::fprintf(stderr,
                                 "[SPU2 status] cycle=%llu mixed=%llu dropped=%llu irq=%u dma=%u/%u voices=%u/%u attr=%04x/%04x peak=%d/%d\n",
                                 static_cast<unsigned long long>(s.iopCycle), static_cast<unsigned long long>(s.framesMixed),
                                 static_cast<unsigned long long>(s.framesDropped), s.irqCount, s.dmaCount[0], s.dmaCount[1],
                                 s.keyedOnVoices[0], s.keyedOnVoices[1], s.coreAttr[0], s.coreAttr[1], s.peak[0], s.peak[1]);
                }
            }
            uint64_t nextEvent() const override
            {
                const uint64_t next = kzspu2NextEventCycle();
                return next == UINT64_MAX ? next : (next > offset ? next - offset : 0u);
            }
            uint32_t takeEvents() override { const uint32_t value = events; events = 0; return value; }
            uint32_t readSamples(int16_t *stereo, uint32_t frames) override { return kzspu2ReadSamples(stereo, frames); }
        private:
            uint32_t events = 0;
            uint64_t nextTrace = 0;
            uint64_t offset = 0; // backend cycle = IOP cycle + offset
        };
    }
#endif
    std::unique_ptr<IopSpu2> createNativeSpu2(std::span<uint8_t> ram)
    {
#if defined(PS2X_NATIVE_SPU2)
        return std::make_unique<NativeSpu2>(ram);
#else
        (void)ram;
        return nullptr;
#endif
    }
}

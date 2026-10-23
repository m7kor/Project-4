#include "iop_memory.h"
#include "iop_spu2.h"
#include "iop_sio2.h"
#include <stdexcept>
#include <limits>
#include <cstdio>
#include <cstdlib>
#include <iostream>

#include <algorithm>
#include <cstring>

namespace ps2x::iop::detail
{
    namespace
    {
        constexpr uint32_t kDmaSpu0Chcr = 0x1F8010C8u;
        constexpr uint32_t kDmaSpu1Chcr = 0x1F801508u;
        constexpr uint32_t kDmaStart = 1u << 24u;
        constexpr int kDmaSpu0Irq = 0x24;
        constexpr int kDmaSpu1Irq = 0x28;

        uint32_t alignUp(uint32_t value, uint32_t alignment)
        {
            return (value + alignment - 1u) & ~(alignment - 1u);
        }

        // Optional PCM producer trace. The clock is the last serviced SPU2
        // clock (normally <=127 IOP cycles old), not an instruction timestamp.
        void tracePcmWrite(uint64_t cycle, uint32_t address, const void *data, size_t size)
        {
            struct Trace
            {
                std::FILE *file = nullptr;
                uint32_t start = 0, length = 0, rows = 0;
                Trace()
                {
                    const char *path = std::getenv("PS2X_IOP_PCM_WRITES");
                    const char *range = std::getenv("PS2X_IOP_PCM_RANGE");
                    if (!path || !*path || !range) return;
                    char *end = nullptr;
                    const unsigned long begin = std::strtoul(range, &end, 0);
                    if (end == range || *end != ':') return;
                    const char *count = end + 1;
                    const unsigned long bytes = std::strtoul(count, &end, 0);
                    if (end == count || *end || begin >= IopMemory::RamSize || !bytes || bytes > IopMemory::RamSize - begin) return;
                    start = static_cast<uint32_t>(begin); length = static_cast<uint32_t>(bytes);
                    file = std::fopen(path, "wb");
                    if (file)
                    {
                        const uint32_t header[] = {0x5750434d, 1, start, length}; // MCPW v1
                        std::fwrite(header, sizeof(header), 1, file);
                    }
                }
                ~Trace() { if (file) std::fclose(file); }
            };
            static Trace trace;
            if (!trace.file || !cycle || trace.rows >= 16000000u || address >= uint64_t(trace.start) + trace.length || uint64_t(address) + size <= trace.start) return;
            const auto *bytes = static_cast<const uint8_t *>(data);
            const size_t first = address < trace.start ? trace.start - address : 0;
            const size_t last = std::min(size, static_cast<size_t>(uint64_t(trace.start) + trace.length - address));
            for (size_t i = first; i < last && trace.rows < 16000000u;)
            {
                const uint32_t count = static_cast<uint32_t>(std::min<size_t>(4, last - i));
                uint32_t value = 0;
                std::memcpy(&value, bytes + i, count);
                const uint32_t fields[] = {address + static_cast<uint32_t>(i), count, value};
                std::fwrite(&cycle, sizeof(cycle), 1, trace.file);
                std::fwrite(fields, sizeof(fields), 1, trace.file);
                if ((++trace.rows & 65535u) == 0u) std::fflush(trace.file);
                i += count;
            }
        }
    }

    IopMemory::IopMemory()
        : m_ram(RamSize), m_owned(RamSize), m_scratch(ScratchSize)
    {
        reset();
    }

    void IopMemory::reset()
    {
        std::fill(m_ram.begin(), m_ram.end(), uint8_t{0});
        std::fill(m_owned.begin(), m_owned.end(), uint8_t{0});
        std::fill(m_scratch.begin(), m_scratch.end(), uint8_t{0});
        m_hardware.clear();
        m_allocations.clear();
        m_heapCursor = HeapBase;
        m_interruptStatus = 0;
        m_interruptMask = 0;
        m_interruptControl = 1;
        m_dmaStarts.clear();
        m_spu2Cycle = 0;
        m_spu2Events = 0;
        m_spu2ReadRanges = {};
        m_sio2TraceCount = 0u;
        if (m_spu2) m_spu2->reset(0u);
        if (m_sio2) m_sio2->reset();
    }

    IopMemory::~IopMemory() = default;
    bool IopMemory::enableNativeSio2(const std::filesystem::path &cardPath, IopPad::Sampler sampler)
    {
        auto sio2 = std::make_unique<IopSio2>();
        if (!sio2->openCard(cardPath)) return false;
        sio2->setPadSampler(std::move(sampler)); sio2->reset(); m_sio2 = std::move(sio2); return true;
    }
    bool IopMemory::enableNativeSpu2()
    {
        if (!m_spu2) m_spu2 = createNativeSpu2(m_ram);
        return m_spu2 != nullptr;
    }
    void IopMemory::advanceSpu2(uint64_t cycle)
    {
        if (!m_spu2) return;
        if (cycle < m_spu2Cycle) throw std::runtime_error("SPU2 clock moved backwards");
        m_spu2Cycle = cycle;
        m_spu2->advance(cycle);
        const uint32_t events = m_spu2->takeEvents();
        m_spu2Events |= events;
        for (unsigned core = 0; core < 2; ++core)
        {
            if ((events & (2u << core)) == 0u) continue;
            const uint32_t base = core ? 0x1F801500u : 0x1F8010C0u;
            m_hardware[base] = m_spu2->dmaMadr(core);
            m_hardware[base + 8u] &= ~kDmaStart;
            const auto range = m_spu2ReadRanges[core];
            if (range.size) markOwned(range.address, range.size);
            m_spu2ReadRanges[core] = {};
        }
    }
    uint64_t IopMemory::nextSpu2Event() const
    {
        return m_spu2 ? std::min(m_spu2->nextEvent(), m_spu2Cycle + 768u * 32u)
                      : std::numeric_limits<uint64_t>::max();
    }
    uint32_t IopMemory::takeSpu2Events() noexcept
    {
        const uint32_t events = m_spu2Events; m_spu2Events = 0; return events;
    }
    uint32_t IopMemory::readAudio(int16_t *stereo, uint32_t frames)
    {
        return m_spu2 && stereo ? m_spu2->readSamples(stereo, frames) : 0;
    }

    uint32_t IopMemory::physicalAddress(uint32_t address) noexcept
    {
        return address & 0x1FFFFFFFu;
    }

    uint8_t IopMemory::read8(uint32_t address) const
    {
        const uint32_t phys = physicalAddress(address);
        if (m_spu2 && phys >= Spu2Base && phys < Spu2Base + 0x800u)
            return static_cast<uint8_t>(m_spu2->read16(phys & ~1u, m_spu2Cycle) >> ((phys & 1u) * 8u));
        if (phys < RamSize)
            return m_ram[phys];
        if (phys >= ScratchBase && phys < ScratchBase + ScratchSize)
            return m_scratch[phys - ScratchBase];
        const uint32_t value = readHardware32(phys & ~3u);
        return static_cast<uint8_t>(value >> ((phys & 3u) * 8u));
    }

    uint16_t IopMemory::read16(uint32_t address) const
    {
        const uint32_t phys = physicalAddress(address);
        if (m_spu2 && !(phys & 1u) && phys >= Spu2Base && phys < Spu2Base + 0x800u)
            return m_spu2->read16(phys, m_spu2Cycle);
        if (phys + 1u < RamSize)
        {
            uint16_t value;
            std::memcpy(&value, m_ram.data() + phys, sizeof(value));
            return value;
        }
        return static_cast<uint16_t>(read8(address) | (static_cast<uint16_t>(read8(address + 1u)) << 8u));
    }

    uint32_t IopMemory::read32(uint32_t address) const
    {
        const uint32_t phys = physicalAddress(address);
        if ((phys & 3u) == 0u && phys + 3u < RamSize)
        {
            uint32_t value;
            std::memcpy(&value, m_ram.data() + phys, sizeof(value));
            return value;
        }
        if ((phys & 3u) == 0u && phys >= ScratchBase && phys + 3u < ScratchBase + ScratchSize)
        {
            uint32_t value;
            std::memcpy(&value, m_scratch.data() + (phys - ScratchBase), sizeof(value));
            return value;
        }
        if ((phys & 3u) == 0u && isHardwareAddress(phys))
            return readHardware32(phys);

        return static_cast<uint32_t>(read8(address)) |
               (static_cast<uint32_t>(read8(address + 1u)) << 8u) |
               (static_cast<uint32_t>(read8(address + 2u)) << 16u) |
               (static_cast<uint32_t>(read8(address + 3u)) << 24u);
    }

    void IopMemory::write8(uint32_t address, uint8_t value)
    {
        const uint32_t phys = physicalAddress(address);
        if (m_sio2 && (phys == 0x1f808260u || (phys & ~3u) == 0x1f808280u))
        {
            writeHardware32(phys & ~3u, uint32_t(value) << ((phys & 3u) * 8)); return;
        }
        if (m_spu2 && phys >= Spu2Base && phys < Spu2Base + 0x800u)
        {
            const uint32_t aligned = phys & ~1u, shift = (phys & 1u) * 8u;
            const uint16_t old = m_spu2->read16(aligned, m_spu2Cycle);
            m_spu2->write16(aligned, static_cast<uint16_t>((old & ~(0xFFu << shift)) | (uint32_t{value} << shift)), m_spu2Cycle);
            return;
        }
        if (phys < RamSize)
        {
            m_ram[phys] = value;
            tracePcmWrite(m_spu2Cycle, phys, &value, sizeof(value));
            markOwned(phys, sizeof(value));
            return;
        }
        if (phys >= ScratchBase && phys < ScratchBase + ScratchSize)
        {
            m_scratch[phys - ScratchBase] = value;
            return;
        }
        const uint32_t aligned = phys & ~3u;
        uint32_t current = readHardware32(aligned);
        const uint32_t shift = (phys & 3u) * 8u;
        current = (current & ~(0xFFu << shift)) | (static_cast<uint32_t>(value) << shift);
        writeHardware32(aligned, current);
    }

    void IopMemory::write16(uint32_t address, uint16_t value)
    {
        const uint32_t phys = physicalAddress(address);
        if (m_spu2 && !(phys & 1u) && phys >= Spu2Base && phys < Spu2Base + 0x800u)
        {
            m_spu2->write16(phys, value, m_spu2Cycle);
            return;
        }
        if (phys + 1u < RamSize)
        {
            std::memcpy(m_ram.data() + phys, &value, sizeof(value));
            tracePcmWrite(m_spu2Cycle, phys, &value, sizeof(value));
            markOwned(phys, sizeof(value));
            return;
        }
        write8(address, static_cast<uint8_t>(value));
        write8(address + 1u, static_cast<uint8_t>(value >> 8u));
    }

    void IopMemory::write32(uint32_t address, uint32_t value)
    {
        const uint32_t phys = physicalAddress(address);
        if ((phys & 3u) == 0u && phys + 3u < RamSize)
        {
            std::memcpy(m_ram.data() + phys, &value, sizeof(value));
            tracePcmWrite(m_spu2Cycle, phys, &value, sizeof(value));
            markOwned(phys, sizeof(value));
            return;
        }
        if ((phys & 3u) == 0u && phys >= ScratchBase && phys + 3u < ScratchBase + ScratchSize)
        {
            std::memcpy(m_scratch.data() + (phys - ScratchBase), &value, sizeof(value));
            return;
        }
        if ((phys & 3u) == 0u)
        {
            writeHardware32(phys, value);
            return;
        }
        write8(address, static_cast<uint8_t>(value));
        write8(address + 1u, static_cast<uint8_t>(value >> 8u));
        write8(address + 2u, static_cast<uint8_t>(value >> 16u));
        write8(address + 3u, static_cast<uint8_t>(value >> 24u));
    }

    bool IopMemory::readRam(uint32_t address, void *destination, size_t size) const
    {
        const uint32_t phys = physicalAddress(address);
        if ((!destination && size != 0u) || phys > RamSize || size > RamSize - phys)
            return false;
        if (size != 0u)
            std::memcpy(destination, m_ram.data() + phys, size);
        return true;
    }

    bool IopMemory::writeRam(uint32_t address, const void *source, size_t size)
    {
        const uint32_t phys = physicalAddress(address);
        if ((!source && size != 0u) || phys > RamSize || size > RamSize - phys)
            return false;
        if (size != 0u)
        {
            std::memcpy(m_ram.data() + phys, source, size);
            tracePcmWrite(m_spu2Cycle, phys, source, size);
            markOwned(phys, size);
        }
        return true;
    }

    bool IopMemory::zeroRam(uint32_t address, size_t size)
    {
        const uint32_t phys = physicalAddress(address);
        if (phys > RamSize || size > RamSize - phys)
            return false;
        if (size != 0u)
        {
            std::memset(m_ram.data() + phys, 0, size);
            tracePcmWrite(m_spu2Cycle, phys, m_ram.data() + phys, size);
            markOwned(phys, size);
        }
        return true;
    }

    bool IopMemory::ownsRamRange(uint32_t address, size_t size) const
    {
        const uint32_t phys = physicalAddress(address);
        if (phys > RamSize || size > RamSize - phys)
            return false;
        return std::all_of(m_owned.begin() + phys, m_owned.begin() + phys + size,
                           [](uint8_t value)
                           { return value != 0u; });
    }

    void IopMemory::markOwned(uint32_t address, size_t size)
    {
        if (address > RamSize || size > RamSize - address)
            return;
        std::fill(m_owned.begin() + address, m_owned.begin() + address + size, uint8_t{1});
    }

    bool IopMemory::isHardwareAddress(uint32_t address) const
    {
        const uint32_t phys = physicalAddress(address);
        return (phys >= HardwareBase && phys < HardwareEnd) ||
               (phys >= 0x1F402000u && phys < 0x1F402040u) ||
               (phys >= Spu2Base && phys < Spu2End) ||
               (phys >= SifBase && phys < SifEnd);
    }

    void IopMemory::traceSio2Hardware(const char *operation, uint32_t address, uint32_t value) const
    {
        // Aligned backing-word observations, including read/modify/write reads.
        // SIO2 and its DMA channels 11/12 have a separate diagnostic budget.
        if (!((address >= 0x1F808200u && address <= 0x1F808280u) ||
              (address >= 0x1F801540u && address <= 0x1F801558u)) ||
            ![] { static const char *const cached = std::getenv("PS2X_TRACE_IOP_SIO2"); return cached; }() || m_sio2TraceCount >= 128u)
            return;
        ++m_sio2TraceCount;
        std::cerr << "[IOP SIO2 word] op=" << operation << " address=0x" << std::hex
                  << address << " value=0x" << value << std::dec
                  << " sample=" << m_sio2TraceCount << '\n';
    }

    uint32_t IopMemory::readHardware32(uint32_t address) const
    {
        if (m_sio2 && address >= 0x1f808200u && address <= 0x1f808280u)
        {
            const uint32_t value = m_sio2->read(address);
            traceSio2Hardware("read", address, value); return value;
        }
        if (m_spu2 && address >= Spu2Base && address < Spu2Base + 0x800u)
            return uint32_t{m_spu2->read16(address, m_spu2Cycle)} |
                   (uint32_t{m_spu2->read16(address + 2u, m_spu2Cycle)} << 16u);
        if (m_spu2 && (address == 0x1F8010C0u || address == 0x1F801500u))
        {
            const auto control = m_hardware.find(address + 8u);
            if (control != m_hardware.end() && (control->second & kDmaStart))
                return m_spu2->dmaMadr(address == 0x1F801500u ? 1u : 0u);
        }
        const auto value = m_hardware.find(address);
        traceSio2Hardware("read", address, value != m_hardware.end() ? value->second : 0u);
        if (value != m_hardware.end())
            return value->second;
        switch (address)
        {
        case 0x1F801070u:
            return m_interruptStatus;
        case 0x1F801074u:
            return m_interruptMask;
        case 0x1F801078u:
            return m_interruptControl;
        default:
            return 0u;
        }
    }

    void IopMemory::writeHardware32(uint32_t address, uint32_t value)
    {
        traceSio2Hardware("write", address, value);
        if (m_sio2 && address >= 0x1f808200u && address <= 0x1f808280u)
        {
            m_sio2->write(address, value);
            serviceSio2Dma();
            if (m_sio2->takeInterrupt()) m_dmaStarts.push_back({17, 32});
            return;
        }
        if (m_spu2 && address >= Spu2Base && address < Spu2Base + 0x800u)
        {
            m_spu2->write16(address, static_cast<uint16_t>(value), m_spu2Cycle);
            m_spu2->write16(address + 2u, static_cast<uint16_t>(value >> 16u), m_spu2Cycle);
            return;
        }
        switch (address)
        {
        case 0x1F801070u:
            m_interruptStatus &= value;
            return;
        case 0x1F801074u:
            m_interruptMask = value;
            return;
        case 0x1F801078u:
            m_interruptControl = value & 1u;
            return;
        default:
            break;
        }

        m_hardware[address] = value;
        if (m_sio2 && (address == 0x1f801548u || address == 0x1f801558u))
        { serviceSio2Dma(); return; }
        if ((address != kDmaSpu0Chcr && address != kDmaSpu1Chcr) || (value & kDmaStart) == 0u)
            return;

        const bool secondCore = address == kDmaSpu1Chcr;
        if (m_spu2)
        {
            const unsigned core = secondCore ? 1u : 0u;
            const uint32_t base = address - 8u;
            const uint32_t madr = physicalAddress(m_hardware[base]);
            const uint32_t bcr = m_hardware[base + 4u];
            const uint64_t bytes = uint64_t{bcr & 0xFFFFu} * (bcr >> 16u) * 4u;
            if ((madr & 1u) || madr >= RamSize || bytes == 0u || bytes > RamSize - madr)
                throw std::runtime_error("invalid native SPU2 DMA RAM range");
            const bool toSpu = (value & 1u) != 0;
            // PS2X_ADMA_RAW=<path>: append every IOP->SPU2 DMA payload, framed as
            // [u32 core][u32 bytes][u64 cycle][data], to judge the stream the
            // sound driver produced before the SPU2 mixes it.
            static std::FILE *admaCapture = [] {
                const char *path = std::getenv("PS2X_ADMA_RAW");
                return path && *path ? std::fopen(path, "wb") : nullptr;
            }();
            if (admaCapture && toSpu)
            {
                const uint32_t header[2] = {core, static_cast<uint32_t>(bytes)};
                const uint64_t cycle = m_spu2Cycle;
                std::fwrite(header, sizeof(header), 1, admaCapture);
                std::fwrite(&cycle, sizeof(cycle), 1, admaCapture);
                std::fwrite(m_ram.data() + madr, 1, static_cast<size_t>(bytes), admaCapture);
            }
            m_spu2ReadRanges[core] = toSpu ? Allocation{} : Allocation{madr, static_cast<uint32_t>(bytes)};
            m_spu2->startDma(core, reinterpret_cast<uint16_t *>(m_ram.data() + madr),
                            static_cast<uint32_t>(bytes / 2u), madr, toSpu, m_spu2Cycle);
            return;
        }
        m_hardware[address] = value & ~kDmaStart;

        const uint32_t statusAddress = 0x1F900344u + (secondCore ? 0x400u : 0u);
        const uint32_t alignedStatus = statusAddress & ~3u;
        const uint32_t shift = (statusAddress & 2u) * 8u;
        uint32_t status = 0u;
        if (const auto current = m_hardware.find(alignedStatus); current != m_hardware.end())
            status = current->second;
        status |= 0x80u << shift;
        m_hardware[alignedStatus] = status;

        const uint32_t blockControlAddress = address - sizeof(uint32_t);
        uint32_t blockControl = 0u;
        if (const auto current = m_hardware.find(blockControlAddress); current != m_hardware.end())
            blockControl = current->second;
        const uint32_t wordsPerBlock = std::max<uint32_t>(blockControl & 0xFFFFu, 1u);
        const uint32_t blockCount = std::max<uint32_t>(blockControl >> 16u, 1u);
        const uint64_t transferWords = static_cast<uint64_t>(wordsPerBlock) * blockCount;
        m_dmaStarts.push_back(DmaStart{
            secondCore ? kDmaSpu1Irq : kDmaSpu0Irq,
            std::max<uint64_t>(transferWords * 2u, 64u),
        });
    }

    void IopMemory::serviceSio2Dma()
    {
        for (const uint32_t base : {0x1f801540u, 0x1f801550u})
        {
            const auto control = m_hardware.find(base + 8);
            if (control == m_hardware.end() || !(control->second & kDmaStart)) continue;
            const bool input = base == 0x1f801540u;
            if (bool(control->second & 1) != input)
                throw std::runtime_error("invalid SIO2 DMA direction");
            const uint32_t address = m_hardware[base] & 0xffffffu;
            const uint32_t bcr = m_hardware[base + 4];
            const uint32_t blockBytes = (bcr & 0xffffu) * 4;
            const uint64_t bytes = uint64_t(blockBytes) * (bcr >> 16);
            if (!bytes || address >= RamSize || bytes > RamSize - address)
                throw std::runtime_error("invalid SIO2 DMA RAM range");
            static const bool traceCard = std::getenv("PS2X_TRACE_SIO2_CARD") != nullptr;
            if (traceCard)
                std::fprintf(stderr, "[sio2:dma] %s addr=%06x block=%u blocks=%u available=%zu\n", input ? "tx" : "rx",
                             address, blockBytes, bcr >> 16, m_sio2->available());
            if (input)
                for (size_t i = 0; i < bytes; ++i) m_sio2->input(m_ram[address + i], blockBytes);
            else
            {
                if (m_sio2->available() < bytes) continue;
                for (size_t i = 0; i < bytes; ++i) m_ram[address + i] = m_sio2->output();
                markOwned(address, static_cast<size_t>(bytes));
            }
            m_hardware[base] = address + static_cast<uint32_t>(bytes);
            m_hardware[base + 8] &= ~kDmaStart;
            m_dmaStarts.push_back({input ? 0x2b : 0x2c, std::max<uint64_t>(bytes * 2, 64)});
        }
    }

    std::optional<IopMemory::DmaStart> IopMemory::takeDmaStart() noexcept
    {
        if (m_dmaStarts.empty()) return std::nullopt;
        const auto result = m_dmaStarts.front(); m_dmaStarts.pop_front(); return result;
    }

    uint32_t IopMemory::allocate(uint32_t size, uint32_t alignment, std::optional<uint32_t> fixed)
    {
        if (size > HeapLimit - HeapBase) return 0u;
        size = alignUp(std::max(size, 1u), 16u);
        alignment = std::max<uint32_t>(alignment, 4u);
        if (alignment > HeapLimit || (alignment & (alignment - 1u)) != 0u) return 0u;
        if (fixed)
        {
            const uint32_t address = *fixed;
            if (address < HeapBase || address > HeapLimit || size > HeapLimit - address)
                return 0u;
            for (const auto &block : m_allocations)
                if (address < block.address + block.size && block.address < address + size)
                    return 0u;
            m_allocations.push_back({address, size});
            markOwned(address, size);
            return address;
        }

        // Search live allocations from the beginning so freed RPC/IRX buffers
        // can be reused instead of permanently consuming the heap's high-water mark.
        uint32_t candidate = alignUp(HeapBase, alignment);
        for (;;)
        {
            bool overlap = false;
            for (const auto &block : m_allocations)
            {
                if (candidate < block.address + block.size && block.address < candidate + size)
                {
                    candidate = alignUp(block.address + block.size, alignment);
                    overlap = true;
                    break;
                }
            }
            if (!overlap)
                break;
        }
        if (candidate > HeapLimit || size > HeapLimit - candidate)
            return 0u;
        m_allocations.push_back({candidate, size});
        markOwned(candidate, size);
        m_heapCursor = std::max(m_heapCursor, candidate + size);
        return candidate;
    }

    bool IopMemory::freeAllocation(uint32_t address)
    {
        const auto block = std::find_if(m_allocations.begin(), m_allocations.end(),
                                        [&](const Allocation &candidate)
                                        { return candidate.address == address; });
        if (block == m_allocations.end())
            return false;
        std::fill(m_owned.begin() + block->address,
                  m_owned.begin() + block->address + block->size,
                  uint8_t{0});
        m_allocations.erase(block);
        return true;
    }

    uint32_t IopMemory::maxFreeMemory() const
    {
        auto blocks = m_allocations;
        std::sort(blocks.begin(), blocks.end(), [](const Allocation &a, const Allocation &b)
        { return a.address < b.address; });
        uint32_t cursor = HeapBase;
        uint32_t largest = 0;
        for (const auto &block : blocks)
        {
            largest = std::max(largest, block.address - cursor);
            cursor = block.address + block.size;
        }
        return std::max(largest, HeapLimit - cursor);
    }

    std::optional<IopMemory::Allocation> IopMemory::allocationContaining(uint32_t address) const
    {
        const auto block = std::find_if(m_allocations.begin(), m_allocations.end(),
                                        [&](const Allocation &candidate)
                                        {
                                            return address >= candidate.address &&
                                                   address < candidate.address + candidate.size;
                                        });
        if (block == m_allocations.end())
            return std::nullopt;
        return *block;
    }

    std::string IopMemory::readString(uint32_t address, size_t limit) const
    {
        std::string result;
        result.reserve(std::min<size_t>(limit, 64u));
        for (size_t i = 0; i < limit; ++i)
        {
            const char ch = static_cast<char>(read8(address + static_cast<uint32_t>(i)));
            if (ch == '\0')
                break;
            result.push_back(ch);
        }
        return result;
    }
}

#include "iop_cdvd.h"

#include "../core/iop_cpu.h"
#include "../core/iop_kernel.h"
#include "../core/iop_memory.h"
#include "ps2x/iop/iop_host.h"
#include "ps2x/iop/ps2_path.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include <ctime>
#include <filesystem>
#include <limits>
#include <string>
#include <sstream>
#include <system_error>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ps2x::iop::detail
{
    namespace
    {
        constexpr uint32_t kSectorSize = 2048u;
        constexpr uint32_t kPrimaryVolumeDescriptorLsn = 16u;
        constexpr uint32_t kVolumeDescriptorTerminatorLsn = 17u;
        constexpr uint32_t kFirstDirectoryLsn = 20u;
        constexpr uint32_t kCdvdErrorNone = 0u;
        constexpr uint32_t kCdvdErrorRead = 0x30u;
        constexpr uint32_t kCdvdTypePs2Dvd = 0x14u;
        constexpr uint32_t kCdvdReadyComplete = 2u;
        constexpr uint32_t kCdvdNotReady = 6u;
        constexpr uint32_t kCdvdNcmdStatusAddress = 0x1F402005u;
        constexpr uint32_t kCdvdDriveStatusAddress = 0x1F40200Au;
        constexpr uint32_t kCdvdDiscTypeAddress = 0x1F40200Fu;
        constexpr uint32_t kCdvdNcmdReadyStatus = 0x40u;
        constexpr uint32_t kCdvdMediaAuto = 0xFFu;
        constexpr uint32_t kCdvdMediaDvd = 2u;
        constexpr uint32_t kCdvdStatusPause = 0x0Au;
        constexpr uint32_t kCdvdInitExit = 5u;
        constexpr uint32_t kCdvdCallbackRead = 1u;
        constexpr uint32_t kCdvdCallbackSeek = 4u;
        constexpr uint32_t kCdvdInterruptReadyBits = 0x29u;
        constexpr uint32_t kEventFlagMulti = 2u;
        constexpr uint32_t kCdvdStreamTimeout = 5000u;
        constexpr uint32_t kCdvdSyncTimeout = 15000u;
        constexpr uint32_t kCdvdmanVersion = 0x0226u;
        // CDVDMAN's shared read workspace, also used by the physical CDVDFSV IRX.
        constexpr uint32_t kFsvReadBufferSize = 42128u;
        constexpr uint32_t kDvdRawSectorSize = 2064u;
        constexpr uint32_t kDma3Madr = 0x1F8010B0u;
        constexpr uint32_t kDma3Bcr = 0x1F8010B4u;
        constexpr uint32_t kDma3Chcr = 0x1F8010B8u;
        constexpr uint32_t kDmaActive = 0x01000000u;

        uint32_t alignSectors(uint64_t bytes)
        {
            return static_cast<uint32_t>((bytes + kSectorSize - 1u) / kSectorSize);
        }

        void writeLe16(uint8_t *destination, uint16_t value)
        {
            destination[0] = static_cast<uint8_t>(value);
            destination[1] = static_cast<uint8_t>(value >> 8u);
        }

        void writeBe16(uint8_t *destination, uint16_t value)
        {
            destination[0] = static_cast<uint8_t>(value >> 8u);
            destination[1] = static_cast<uint8_t>(value);
        }

        void writeLe32(uint8_t *destination, uint32_t value)
        {
            for (uint32_t i = 0u; i < 4u; ++i)
                destination[i] = static_cast<uint8_t>(value >> (i * 8u));
        }

        void writeBe32(uint8_t *destination, uint32_t value)
        {
            for (uint32_t i = 0u; i < 4u; ++i)
                destination[i] = static_cast<uint8_t>(value >> ((3u - i) * 8u));
        }

        void writeBoth16(uint8_t *destination, uint16_t value)
        {
            writeLe16(destination, value);
            writeBe16(destination + 2u, value);
        }

        void writeBoth32(uint8_t *destination, uint32_t value)
        {
            writeLe32(destination, value);
            writeBe32(destination + 4u, value);
        }

        std::string isoName(const std::filesystem::path &path, bool directory)
        {
            std::string name = path.filename().string();
            for (char &character : name)
            {
                const unsigned char byte = static_cast<unsigned char>(character);
                character = byte < 0x80u ? static_cast<char>(std::toupper(byte)) : '_';
            }
            if (name.size() > 200u)
                name.resize(200u);
            if (!directory && name.find(';') == std::string::npos)
                name += ";1";
            return name;
        }

        size_t directoryRecordSize(size_t identifierSize)
        {
            const size_t unpadded = 33u + identifierSize;
            return unpadded + (unpadded & 1u);
        }

        uint32_t directoryBytesFor(const std::vector<size_t> &identifierSizes)
        {
            uint64_t cursor = 0u;
            for (const size_t identifierSize : identifierSizes)
            {
                const uint64_t recordSize = directoryRecordSize(identifierSize);
                const uint64_t sectorOffset = cursor % kSectorSize;
                if (sectorOffset + recordSize > kSectorSize)
                    cursor += kSectorSize - sectorOffset;
                cursor += recordSize;
            }
            return static_cast<uint32_t>(std::max<uint64_t>(kSectorSize, alignSectors(cursor) * kSectorSize));
        }

        std::string normalizedIsoComponent(std::string_view value)
        {
            std::string result(value);
            const size_t semicolon = result.rfind(';');
            if (semicolon != std::string::npos && semicolon + 1u < result.size() &&
                std::all_of(result.begin() + static_cast<std::ptrdiff_t>(semicolon + 1u), result.end(),
                            [](unsigned char ch)
                            { return std::isdigit(ch) != 0; }))
            {
                result.resize(semicolon);
            }
            std::transform(result.begin(), result.end(), result.begin(),
                           [](unsigned char ch)
                           { return static_cast<char>(std::toupper(ch)); });
            return result;
        }

        size_t writeDirectoryRecord(uint8_t *destination,
                                    uint32_t lsn,
                                    uint32_t size,
                                    bool directory,
                                    const uint8_t *identifier,
                                    size_t identifierSize)
        {
            const size_t recordSize = directoryRecordSize(identifierSize);
            std::memset(destination, 0, recordSize);
            destination[0] = static_cast<uint8_t>(recordSize);
            writeBoth32(destination + 2u, lsn);
            writeBoth32(destination + 10u, size);
            destination[25] = directory ? 2u : 0u;
            writeBoth16(destination + 28u, 1u);
            destination[32] = static_cast<uint8_t>(identifierSize);
            std::memcpy(destination + 33u, identifier, identifierSize);
            return recordSize;
        }
    }

    class IopCdvd::Impl
    {
    public:
        struct Callback
        {
            uint32_t address = 0u;
            uint32_t gp = 0u;
        };

        struct IsoNode
        {
            std::filesystem::path hostPath;
            std::string identifier;
            size_t parent = 0u;
            bool directory = false;
            uint32_t lsn = 0u;
            uint32_t size = 0u;
            uint32_t sectors = 0u;
            uint64_t handle = 0u;
            std::vector<size_t> children;
        };

        Impl(IopHost &hostRef, IopMemory &memoryRef, IopKernel &kernelRef)
            : host(hostRef), memory(memoryRef), kernel(kernelRef)
        {
            reset();
        }

        ~Impl()
        {
            closeFiles();
        }

        void reset()
        {
            closeFiles();
            if (fsvReadBuffer != 0u)
                (void)memory.freeAllocation(fsvReadBuffer);
            fsvReadBuffer = 0u;
            if (internalState != 0u)
                (void)memory.freeAllocation(internalState);
            internalState = 0u;
            dvdRemaining = 0u;
            dvdNextLsn = 0u;
            dvdCallback = {};
            callback = {};
            initialized = false;
            mediaMode = kCdvdMediaAuto;
            currentLsn = 0u;
            lastError = kCdvdErrorNone;
            streamFlag = 0u;
            lastReadTimeout = 0u;
            interruptEventFlagId = 0;
            virtualIsoBuilt = false;
            virtualIsoValid = false;
            completionCallback.reset();
            nodes.clear();
            metadataSectors.clear();
            imageHandle = 0u;
            // This backend mounts a PS2 DVD and completes sector reads
            // synchronously. Physical CDVDFSV also inlines these register
            // reads, so the imports and MMIO must expose the same state.
            memory.write8(kCdvdNcmdStatusAddress, kCdvdNcmdReadyStatus);
            memory.write8(kCdvdDriveStatusAddress, kCdvdStatusPause);
            memory.write8(kCdvdDiscTypeAddress, kCdvdTypePs2Dvd);
        }

        bool dispatchImport(uint16_t ordinal, IopCpuState &cpu)
        {
            const uint32_t a0 = cpu.gpr[4];
            const uint32_t a1 = cpu.gpr[5];
            const uint32_t a2 = cpu.gpr[6];

            switch (ordinal)
            {
            case 4: // sceCdInit
                initialized = a0 != kCdvdInitExit;
                if (initialized)
                {
                    callback = {};
                    completionCallback.reset();
                }
                lastError = kCdvdErrorNone;
                cpu.gpr[2] = 1u;
                return true;

            case 24: // sceCdReadClock
            case 51: // sceCdRC (same host-backed RTC, without a hardware month flag)
            {
                // The clock is an eight-byte IOP buffer, never an EE address.
                // Match the existing native EE clock's host-local time policy.
                if (a0 == 0u || !memory.ownsRamRange(a0, 8u))
                {
                    cpu.gpr[2] = 0u;
                    return true;
                }
                const std::time_t now = std::time(nullptr);
                std::tm clock{};
#ifdef _WIN32
                const bool valid = now != static_cast<std::time_t>(-1) && localtime_s(&clock, &now) == 0;
#else
                const bool valid = now != static_cast<std::time_t>(-1) && localtime_r(&now, &clock) != nullptr;
#endif
                if (!valid)
                {
                    cpu.gpr[2] = 0u;
                    return true;
                }
                const auto bcd = [](unsigned value) { return static_cast<uint8_t>(((value / 10u) << 4u) | (value % 10u)); };
                const std::array<uint8_t, 8> data{0u, bcd(clock.tm_sec), bcd(clock.tm_min),
                    bcd(clock.tm_hour), 0u, bcd(clock.tm_mday), bcd(clock.tm_mon + 1u),
                    bcd((clock.tm_year + 1900u) % 100u)};
                cpu.gpr[2] = memory.writeRam(a0, data.data(), data.size()) ? 1u : 0u;
                return true;
            }

            case 5: // sceCdStandby
                cpu.gpr[2] = 1u;
                return true;

            case 6: // sceCdRead
                if (readSectors(a0, a1, a2))
                {
                    signalCommandComplete();
                    if (callback.address != 0u)
                    {
                        completionCallback = CompletionCallback{
                            callback.address,
                            callback.gp,
                            kCdvdCallbackRead,
                        };
                    }
                    cpu.gpr[2] = 1u;
                }
                else
                    cpu.gpr[2] = 0u;
                return true;

            case 63: // sceCdRV: raw DVD sectors, optionally delivered in chunks.
            {
                const uint32_t sp = IopMemory::physicalAddress(cpu.gpr[29]);
                traceDvd("request", a0, a1, a2, sp <= IopMemory::RamSize - 24u ? memory.read32(sp + 16u) : 0u);
                if (sp > IopMemory::RamSize - 24u || !memory.ownsRamRange(sp + 16u, 8u) ||
                    !memory.ownsRamRange(cpu.gpr[7], 4u) || ensureInternalState() == 0u ||
                    memory.read8(kCdvdDiscTypeAddress) != kCdvdTypePs2Dvd ||
                    (mediaMode != kCdvdMediaAuto && mediaMode != kCdvdMediaDvd) ||
                    dvdRemaining != 0u || memory.read32(internalState + 0xA0u) != 0u ||
                    static_cast<uint64_t>(a0) + a1 > 0xFD0000u)
                {
                    traceDvd("request-rejected", a0, a1, a2, sp <= IopMemory::RamSize - 24u ? memory.read32(sp + 16u) : 0u);
                    lastError = kCdvdErrorRead;
                    cpu.gpr[2] = 0u;
                    return true;
                }
                const uint32_t chunkLimit = memory.read32(sp + 16u);
                const uint32_t count = chunkLimit == 0u ? a1 : std::min(a1, chunkLimit);
                if (!readDvdChunk(a0, count, a2))
                {
                    cpu.gpr[2] = 0u;
                    return true;
                }
                dvdRemaining = a1 - count;
                traceDvd("first-chunk-delivered", a0, count, a2, chunkLimit);
                dvdNextLsn = a0 + count;
                dvdCallback = {memory.read32(sp + 20u), cpu.gpr[28]};
                memory.write32(internalState + 0x34u, 1u); // DVD flag
                memory.write32(internalState + 0x38u, a0);
                memory.write32(internalState + 0x3Cu, a2);
                memory.write32(internalState + 0x40u, a1);
                memory.write32(internalState + 0x44u, memory.read32(cpu.gpr[7]));
                memory.write32(internalState + 0x50u, dvdCallback.address);
                memory.write32(internalState + 0x54u, count);
                // The retail CDVDFSV IRX reads block words/count at +A4/+A6
                // and stores the DMA destination at +A8 (verified instructions).
                memory.write16(internalState + 0xA4u, 12u);
                memory.write16(internalState + 0xA6u, static_cast<uint16_t>(43u * (chunkLimit == 0u ? count : 1u)));
                memory.write32(internalState + 0xA8u, a2); // DMA3 workspace
                memory.write32(internalState + 0xB0u, dvdCallback.address);
                memory.write16(internalState + 0xB4u, static_cast<uint16_t>(count));
                memory.write16(internalState + 0xB6u, 0x8Cu);
                memory.write32(internalState + 0xB8u, a1);
                completeDvdChunk();
                cpu.gpr[2] = 1u;
                return true;
            }

            case 7: // sceCdSeek
                currentLsn = a0;
                lastError = kCdvdErrorNone;
                signalCommandComplete();
                if (callback.address != 0u)
                {
                    completionCallback = CompletionCallback{
                        callback.address,
                        callback.gp,
                        kCdvdCallbackSeek,
                    };
                }
                cpu.gpr[2] = 1u;
                return true;

            case 8: // sceCdGetError
                cpu.gpr[2] = lastError;
                return true;

            case 10: // sceCdSearchFile
                cpu.gpr[2] = searchFile(a0, a1) ? 1u : 0u;
                return true;

            case 84: // sceCdLayerSearchFile(sceCdlFILE *, const char *, int layer)
                // The extracted-disc index represents layer zero only.
                // Reject other layers before touching the caller's result.
                cpu.gpr[2] = a2 == 0u && searchFile(a0, a1) ? 1u : 0u;
                return true;

            case 11: // sceCdSync
                // Mode 32 observes the completed chunk; normal polling
                // observes the complete command, including later DMA chunks.
                cpu.gpr[2] = a0 == 32u ? 0u : (dvdRemaining != 0u ? 1u : 0u);
                return true;

            case 12: // sceCdGetDiskType
                cpu.gpr[2] = memory.read8(kCdvdDiscTypeAddress);
                return true;

            case 13: // sceCdDiskReady
                // Mode 8 returns the raw N-command status byte. CDVDFSV
                // tests bits 0xC0 for 0x40, rather than the public ready code.
                cpu.gpr[2] = memory.read8(kCdvdNcmdStatusAddress);
                if (a0 != 8u)
                    cpu.gpr[2] = (cpu.gpr[2] & 0xC0u) == kCdvdNcmdReadyStatus ? kCdvdReadyComplete : kCdvdNotReady;
                return true;

            case 28: // sceCdStatus
                cpu.gpr[2] = memory.read8(kCdvdDriveStatusAddress);
                return true;

            case 37: // sceCdCallback
            {
                const uint32_t previous = callback.address;
                callback = {a0, cpu.gpr[28]};
                cpu.gpr[2] = previous;
                return true;
            }

            case 47: // sceGetFsvRbuf
                if (fsvReadBuffer == 0u)
                {
                    fsvReadBuffer = memory.allocate(kFsvReadBufferSize, 64u);
                    if (fsvReadBuffer != 0u)
                        (void)memory.zeroRam(fsvReadBuffer, kFsvReadBufferSize);
                }
                cpu.gpr[2] = fsvReadBuffer;
                return true;

            case 50: // sceCdSC
            {
                const int32_t code = static_cast<int32_t>(a0);
                switch (code)
                {
                case -14: // Shared CDVDMAN state consumed by physical CDVDFSV.
                    if (!memory.ownsRamRange(a1, 4u))
                    {
                        cpu.gpr[2] = 0u;
                        return true;
                    }
                    cpu.gpr[2] = ensureInternalState() != 0u ? 0xFFu : 0u;
                    if (cpu.gpr[2] != 0u)
                        memory.write32(a1, internalState);
                    return true;
                case -22: // DvdDual_infochk: validate the virtual DVD layer mapping.
                    // Extracted discs have a single continuous LSN space.
                    // Physical ISO layer geometry is not inferred from a filename.
                    cpu.gpr[2] = memory.read8(kCdvdDiscTypeAddress) == kCdvdTypePs2Dvd &&
                                 host.hostPath(HostPathKind::CdImage).empty() && buildVirtualIso();
                    return true;
                case -23: // Translate a logical sector for a dual-layer disc.
                    // The host image exposes one continuous LSN space, so no layer offset is required.
                    cpu.gpr[2] = a1 != 0u ? memory.read32(a1) : 0u;
                    return true;
                case -18:
                    lastReadTimeout = a1 != 0u ? memory.read32(a1) : 0u;
                    cpu.gpr[2] = 0u;
                    return true;
                case -17:
                    cpu.gpr[2] = kCdvdStreamTimeout;
                    return true;
                case -15:
                    cpu.gpr[2] = kCdvdSyncTimeout;
                    return true;
                case -12: // Media mode is compatible with the mounted PS2 DVD.
                    cpu.gpr[2] = memory.read8(kCdvdDiscTypeAddress) == kCdvdTypePs2Dvd &&
                                 (mediaMode == kCdvdMediaAuto || mediaMode == kCdvdMediaDvd);
                    return true;
                case -11:
                    cpu.gpr[2] = static_cast<uint32_t>(ensureInterruptEventFlag());
                    return true;
                case -9:
                    cpu.gpr[2] = kCdvdmanVersion;
                    return true;
                case -3: // read2_flag: sector reads complete synchronously here.
                    cpu.gpr[2] = 0u;
                    return true;
                case -2:
                    lastError = a1 != 0u ? memory.read8(a1) : kCdvdErrorNone;
                    cpu.gpr[2] = lastError;
                    return true;
                case -1:
                case 0:
                case 1:
                case 2:
                    if (a1 != 0u)
                        memory.write32(a1, lastError & 0xFFu);
                    if (code != -1)
                        streamFlag = static_cast<uint32_t>(code);
                    cpu.gpr[2] = streamFlag;
                    return true;
                default:
                    // sceCdSC is intentionally extensible; unsupported controls are no-ops in cdvdman.
                    cpu.gpr[2] = 0u;
                    return true;
                }
            }

            case 75: // sceCdMmode
                mediaMode = a0;
                cpu.gpr[2] = 1u;
                return true;

            default:
                return false;
            }
        }

        std::optional<CompletionCallback> takeCompletionCallback() noexcept
        {
            std::optional<CompletionCallback> result = completionCallback;
            completionCallback.reset();
            return result;
        }

        void syncInternalError()
        {
            if (internalState != 0u)
                memory.write8(internalState + 1u, static_cast<uint8_t>(lastError));
        }

        void serviceDma()
        {
            if (dvdRemaining == 0u)
                return;
            const uint32_t chcr = memory.read32(kDma3Chcr);
            if ((chcr & kDmaActive) == 0u)
                return;
            const uint32_t bcr = memory.read32(kDma3Bcr);
            const uint64_t bytes = static_cast<uint64_t>(bcr & 0xFFFFu) * (bcr >> 16u) * 4u;
            const uint32_t count = static_cast<uint32_t>(bytes / kDvdRawSectorSize);
            const uint32_t destination = memory.read32(kDma3Madr);
            traceDvd("dma-start", dvdNextLsn, count, destination, bcr);
            if (bytes == 0u || bytes % kDvdRawSectorSize != 0u || bytes > IopMemory::RamSize ||
                count > dvdRemaining || !readDvdChunk(dvdNextLsn, count, destination))
            {
                lastError = kCdvdErrorRead;
                traceDvd("dma-rejected", dvdNextLsn, count, destination, bcr);
                dvdRemaining = 0u;
            }
            else
            {
                dvdRemaining -= count;
                dvdNextLsn += count;
                memory.write32(kDma3Madr, destination + static_cast<uint32_t>(bytes));
                memory.write32(kDma3Bcr, bcr & 0xFFFFu);
            }
            memory.write32(kDma3Chcr, chcr & ~kDmaActive);
            syncInternalError();
            completeDvdChunk();
        }

        IopHost &hostInterface() noexcept { return host; }

        std::optional<IopCdvd::FileHandle> openFile(std::string_view path)
        {
            IsoNode *node = findVirtualIsoNode(path);
            if (!node || node->directory)
                return std::nullopt;
            return IopCdvd::FileHandle{node->lsn, node->size};
        }

        size_t readFile(const IopCdvd::FileHandle &file, uint32_t offset, uint8_t *destination, size_t size)
        {
            if (offset >= file.size || size == 0u)
                return 0u;
            size = std::min<size_t>(size, file.size - offset);
            size_t completed = 0u;
            std::array<uint8_t, kSectorSize> sector{};
            while (completed < size)
            {
                const uint32_t absolute = offset + static_cast<uint32_t>(completed);
                if (!readVirtualSector(file.lsn + absolute / kSectorSize, sector.data()))
                    break;
                const size_t within = absolute % kSectorSize;
                const size_t chunk = std::min(size - completed, kSectorSize - within);
                std::memcpy(destination + completed, sector.data() + within, chunk);
                completed += chunk;
            }
            return completed;
        }

    private:
        void traceDvd(const char *event, uint32_t lsn, uint32_t count, uint32_t destination, uint32_t parameter)
        {
            if ([] { static const char *const cached = std::getenv("PS2X_TRACE_CDVD"); return cached; }() == nullptr || dvdTraceCount >= 128u)
                return;
            ++dvdTraceCount;
            const uint64_t bytes = static_cast<uint64_t>(count) * kDvdRawSectorSize;
            std::ostringstream out;
            out << "[DVD transfer] event=" << event << " lsn=" << lsn << " count=" << count
                << " destination=0x" << std::hex << destination << " parameter=0x" << parameter
                << " remaining=" << std::dec << dvdRemaining << " owned="
                << (bytes <= IopMemory::RamSize && memory.ownsRamRange(destination, static_cast<size_t>(bytes)))
                << " chcr=0x" << std::hex << memory.read32(kDma3Chcr)
                << " bcr=0x" << memory.read32(kDma3Bcr) << " madr=0x" << memory.read32(kDma3Madr);
            host.log(LogLevel::Info, out.str());
        }

        uint32_t ensureInternalState()
        {
            if (internalState == 0u)
            {
                internalState = memory.allocate(0x200u, 16u);
                if (internalState != 0u)
                    (void)memory.zeroRam(internalState, 0x200u);
            }
            return internalState;
        }

        void completeDvdChunk()
        {
            signalCommandComplete();
            if (dvdCallback.address != 0u)
                completionCallback = CompletionCallback{dvdCallback.address, dvdCallback.gp, 0u};
        }

        bool readDvdChunk(uint32_t lsn, uint32_t count, uint32_t destination)
        {
            const uint64_t rawSize = static_cast<uint64_t>(count) * kDvdRawSectorSize;
            if (rawSize > IopMemory::RamSize || !memory.ownsRamRange(destination, static_cast<size_t>(rawSize)))
            {
                traceDvd("destination-rejected", lsn, count, destination, 0u);
                lastError = kCdvdErrorRead;
                return false;
            }
            std::vector<uint8_t> data;
            if (!loadSectorData(lsn, count, data))
            {
                traceDvd("source-rejected", lsn, count, destination, 0u);
                lastError = kCdvdErrorRead;
                return false;
            }
            std::vector<uint8_t> raw(static_cast<size_t>(rawSize), 0u);
            for (uint32_t i = 0; i < count; ++i)
            {
                uint8_t *sector = raw.data() + static_cast<size_t>(i) * kDvdRawSectorSize;
                const uint32_t id = lsn + i + 0x30000u;
                sector[0] = 0x20u; // DVD data sector on virtual layer zero.
                sector[1] = static_cast<uint8_t>(id >> 16u);
                sector[2] = static_cast<uint8_t>(id >> 8u);
                sector[3] = static_cast<uint8_t>(id);
                // The host supplies decoded payloads. IED/CPR_MAI/EDC are
                // zero here, matching the software-disc framing model.
                std::memcpy(sector + 12u, data.data() + static_cast<size_t>(i) * kSectorSize, kSectorSize);
            }
            if (rawSize != 0u && !memory.writeRam(destination, raw.data(), raw.size()))
            {
                lastError = kCdvdErrorRead;
                return false;
            }
            lastError = kCdvdErrorNone;
            return true;
        }
        int ensureInterruptEventFlag()
        {
            if (interruptEventFlagId == 0)
            {
                interruptEventFlagId = kernel.createInternalEventFlag(
                    kEventFlagMulti, 0u, kCdvdInterruptReadyBits);
            }
            return interruptEventFlagId;
        }

        void signalCommandComplete()
        {
            if (interruptEventFlagId != 0)
                (void)kernel.setInternalEventFlag(interruptEventFlagId, kCdvdInterruptReadyBits);
        }

        void closeFiles()
        {
            if (imageHandle != 0u)
                host.closeHostFile(imageHandle);
            imageHandle = 0u;
            for (IsoNode &node : nodes)
            {
                if (node.handle != 0u)
                    host.closeHostFile(node.handle);
                node.handle = 0u;
            }
        }

        bool addDirectory(size_t parent, const std::filesystem::path &path)
        {
            std::error_code error;
            std::vector<std::filesystem::directory_entry> entries;
            for (
                std::filesystem::directory_iterator iterator(path, std::filesystem::directory_options::skip_permission_denied, error),
                end;
                !error && iterator != end;
                iterator.increment(error))
            {
                const std::filesystem::directory_entry &entry = *iterator;
                if (entry.is_symlink(error))
                {
                    error.clear();
                    continue;
                }
                error.clear();
                if (entry.is_directory(error) || entry.is_regular_file(error))
                    entries.push_back(entry);
                error.clear();
            }

            std::sort(entries.begin(), entries.end(),
                      [](const auto &lhs, const auto &rhs)
                      {
                          return isoName(lhs.path(), lhs.is_directory()) < isoName(rhs.path(), rhs.is_directory());
                      });

            for (const auto &entry : entries)
            {
                error.clear();
                const bool directory = entry.is_directory(error);
                if (error)
                    continue;
                IsoNode node;
                node.hostPath = entry.path();
                node.identifier = isoName(entry.path(), directory);
                node.parent = parent;
                node.directory = directory;
                if (!directory)
                {
                    const uint64_t fileSize = entry.file_size(error);
                    if (error)
                        continue;
                    node.size = static_cast<uint32_t>(std::min<uint64_t>(fileSize, std::numeric_limits<uint32_t>::max()));
                }
                const size_t index = nodes.size();
                nodes.push_back(std::move(node));
                nodes[parent].children.push_back(index);
                if (directory && !addDirectory(index, entry.path()))
                    return false;
            }
            return true;
        }

        bool buildVirtualIso()
        {
            if (virtualIsoBuilt)
                return virtualIsoValid;
            virtualIsoBuilt = true;

            const std::string rootValue = host.hostPath(HostPathKind::CdRoot);
            if (rootValue.empty())
                return false;
            const std::filesystem::path rootPath(rootValue);
            std::error_code error;
            if (!std::filesystem::is_directory(rootPath, error) || error)
                return false;

            nodes.clear();
            IsoNode root;
            root.hostPath = rootPath;
            root.identifier.clear();
            root.parent = 0u;
            root.directory = true;
            nodes.push_back(std::move(root));
            if (!addDirectory(0u, rootPath))
                return false;

            for (IsoNode &node : nodes)
            {
                if (!node.directory)
                    continue;
                std::vector<size_t> identifierSizes = {1u, 1u};
                identifierSizes.reserve(node.children.size() + 2u);
                for (const size_t child : node.children)
                    identifierSizes.push_back(nodes[child].identifier.size());
                node.size = directoryBytesFor(identifierSizes);
                node.sectors = node.size / kSectorSize;
            }

            uint32_t cursor = kFirstDirectoryLsn;
            for (IsoNode &node : nodes)
            {
                if (!node.directory)
                    continue;
                node.lsn = cursor;
                cursor += node.sectors;
            }
            for (IsoNode &node : nodes)
            {
                if (node.directory)
                    continue;
                node.lsn = cursor;
                node.sectors = alignSectors(node.size);
                cursor += node.sectors;
            }
            volumeSectors = std::max<uint32_t>(cursor, 32u);
            // With the disc trace on, publish the virtual layout once so a
            // sector read can be named (tools/diagnostics/stall_report.py
            // resolves it further to the AFS entry and its file name).
            if ([] { static const char *const cached = std::getenv("PS2X_TRACE_CDVD"); return cached; }())
            {
                for (const IsoNode &node : nodes)
                {
                    if (node.directory)
                        continue;
                    std::cerr << "[CDVD layout] lsn=" << node.lsn << " sectors=" << node.sectors
                              << " bytes=" << node.size << " path=" << node.hostPath.filename().string() << '\n';
                }
            }

            std::array<uint8_t, kSectorSize> primary{};
            primary[0] = 1u;
            std::memcpy(primary.data() + 1u, "CD001", 5u);
            primary[6] = 1u;
            std::memset(primary.data() + 8u, ' ', 32u);
            std::memcpy(primary.data() + 8u, "PS2XRECOMP", 10u);
            std::memset(primary.data() + 40u, ' ', 32u);
            std::memcpy(primary.data() + 40u, "PS2X VIRTUAL DISC", 17u);
            writeBoth32(primary.data() + 80u, volumeSectors);
            writeBoth16(primary.data() + 120u, 1u);
            writeBoth16(primary.data() + 124u, 1u);
            writeBoth16(primary.data() + 128u, static_cast<uint16_t>(kSectorSize));
            const uint8_t rootIdentifier = 0u;
            (void)writeDirectoryRecord(primary.data() + 156u, nodes[0].lsn, nodes[0].size, true, &rootIdentifier, 1u);
            primary[881] = 1u;
            metadataSectors[kPrimaryVolumeDescriptorLsn] = primary;

            std::array<uint8_t, kSectorSize> terminator{};
            terminator[0] = 255u;
            std::memcpy(terminator.data() + 1u, "CD001", 5u);
            terminator[6] = 1u;
            metadataSectors[kVolumeDescriptorTerminatorLsn] = terminator;

            for (size_t nodeIndex = 0u; nodeIndex < nodes.size(); ++nodeIndex)
            {
                const IsoNode &node = nodes[nodeIndex];
                if (!node.directory)
                    continue;
                std::vector<uint8_t> bytes(node.size, 0u);
                size_t offset = 0u;
                const auto appendRecord = [&](const IsoNode &entry, const uint8_t *identifier, size_t identifierSize)
                {
                    const size_t recordSize = directoryRecordSize(identifierSize);
                    const size_t sectorOffset = offset % kSectorSize;
                    if (sectorOffset + recordSize > kSectorSize)
                        offset += kSectorSize - sectorOffset;
                    offset += writeDirectoryRecord(bytes.data() + offset,
                                                   entry.lsn,
                                                   entry.size,
                                                   entry.directory,
                                                   identifier,
                                                   identifierSize);
                };
                const uint8_t selfIdentifier = 0u;
                const uint8_t parentIdentifier = 1u;
                appendRecord(node, &selfIdentifier, 1u);
                appendRecord(nodes[node.parent], &parentIdentifier, 1u);
                for (const size_t childIndex : node.children)
                {
                    const IsoNode &child = nodes[childIndex];
                    appendRecord(child, reinterpret_cast<const uint8_t *>(child.identifier.data()), child.identifier.size());
                }
                for (uint32_t sector = 0u; sector < node.sectors; ++sector)
                {
                    std::array<uint8_t, kSectorSize> contents{};
                    std::memcpy(contents.data(), bytes.data() + sector * kSectorSize, kSectorSize);
                    metadataSectors[node.lsn + sector] = contents;
                }
            }

            virtualIsoValid = true;
            return true;
        }

        IsoNode *findVirtualIsoNode(std::string_view guestPath)
        {
            if (!buildVirtualIso())
                return nullptr;

            const ParsedPs2Path parsed = parsePs2Path(guestPath);
            if (!parsed || parsed.device != Ps2PathDevice::Cdrom)
                return nullptr;

            size_t current = 0u;
            size_t begin = 0u;
            while (begin <= parsed.path.size())
            {
                const size_t end = parsed.path.find('/', begin);
                const size_t length = (end == std::string::npos) ? parsed.path.size() - begin : end - begin;
                const std::string_view component(parsed.path.data() + begin, length);
                begin = (end == std::string::npos) ? parsed.path.size() + 1u : end + 1u;

                if (component.empty() || component == ".")
                    continue;
                if (component == "..")
                    return nullptr;

                const std::string wanted = normalizedIsoComponent(component);
                const auto child = std::find_if(nodes[current].children.begin(), nodes[current].children.end(),
                                                [&](size_t childIndex)
                                                {
                                                    return normalizedIsoComponent(nodes[childIndex].identifier) == wanted;
                                                });
                if (child == nodes[current].children.end())
                    return nullptr;
                current = *child;
            }
            return &nodes[current];
        }

        bool searchFile(uint32_t resultAddress, uint32_t nameAddress)
        {
            if (resultAddress == 0u || nameAddress == 0u)
                return false;

            const std::string guestPath = memory.readString(nameAddress, 1024u);
            IsoNode *node = findVirtualIsoNode(guestPath);
            if ([] { static const char *const cached = std::getenv("PS2X_TRACE_CDVD"); return cached; }() != nullptr && searchTraceCount < 64u)
            {
                ++searchTraceCount;
                std::ostringstream out;
                out << "[CDVD search] path=";
                for (unsigned char c : guestPath)
                    out << (c >= 32u && c < 127u ? static_cast<char>(c) : '?');
                out << " found=" << (node != nullptr);
                if (node)
                    out << " directory=" << node->directory << " lsn=" << node->lsn << " size=" << node->size;
                host.log(LogLevel::Info, out.str());
            }
            if (!node)
                return false;

            // sceCdlFILE: lsn, size, name[16], date/flags[8].
            std::array<uint8_t, 32u> result{};
            writeLe32(result.data(), node->lsn);
            writeLe32(result.data() + 4u, node->size);
            const std::string leaf = normalizedIsoComponent(node->identifier);
            std::memcpy(result.data() + 8u, leaf.data(), std::min<size_t>(16u, leaf.size()));
            result[24u] = node->directory ? 2u : 0u;
            return memory.writeRam(resultAddress, result.data(), result.size());
        }

        IsoNode *fileForSector(uint32_t lsn)
        {
            for (IsoNode &node : nodes)
            {
                if (!node.directory && lsn >= node.lsn && lsn < node.lsn + node.sectors)
                    return &node;
            }
            return nullptr;
        }

        bool readVirtualSector(uint32_t lsn, uint8_t *destination)
        {
            const auto metadata = metadataSectors.find(lsn);
            if (metadata != metadataSectors.end())
            {
                std::memcpy(destination, metadata->second.data(), kSectorSize);
                return true;
            }

            IsoNode *node = fileForSector(lsn);
            if (!node)
            {
                std::memset(destination, 0, kSectorSize);
                return lsn < volumeSectors;
            }
            if (node->handle == 0u)
                node->handle = host.openHostFile(node->hostPath.string());
            if (node->handle == 0u)
                return false;

            std::memset(destination, 0, kSectorSize);
            const uint64_t offset = static_cast<uint64_t>(lsn - node->lsn) * kSectorSize;
            const size_t wanted = static_cast<size_t>(std::min<uint64_t>(kSectorSize, static_cast<uint64_t>(node->size) - offset));
            size_t bytesRead = 0u;
            return host.readHostFile(node->handle, offset, destination, wanted, bytesRead) && bytesRead == wanted;
        }

        bool readSectors(uint32_t lsn, uint32_t sectors, uint32_t destination)
        {
            if (sectors == 0u)
            {
                lastError = kCdvdErrorNone;
                return true;
            }
            const uint64_t byteCount64 = static_cast<uint64_t>(sectors) * kSectorSize;
            if (byteCount64 > IopMemory::RamSize || !memory.ownsRamRange(destination, static_cast<size_t>(byteCount64)))
            {
                lastError = kCdvdErrorRead;
                return false;
            }
            std::vector<uint8_t> bytes;
            if (!loadSectorData(lsn, sectors, bytes) || !memory.writeRam(destination, bytes.data(), bytes.size()))
            {
                lastError = kCdvdErrorRead;
                return false;
            }
            lastError = kCdvdErrorNone;
            return true;
        }

        bool loadSectorData(uint32_t lsn, uint32_t sectors, std::vector<uint8_t> &bytes)
        {
            const uint64_t byteCount64 = static_cast<uint64_t>(sectors) * kSectorSize;
            if (byteCount64 > IopMemory::RamSize || static_cast<uint64_t>(lsn) + sectors > 0x100000000ull)
                return false;
            const size_t byteCount = static_cast<size_t>(byteCount64);
            bytes.assign(byteCount, 0u);
            if (sectors == 0u)
                return true;

            bool read = false;
            const std::string imagePath = host.hostPath(HostPathKind::CdImage);
            if (!imagePath.empty())
            {
                if (imageHandle == 0u)
                    imageHandle = host.openHostFile(imagePath);
                if (imageHandle != 0u)
                {
                    size_t bytesRead = 0u;
                    read = host.readHostFile(imageHandle,
                                             static_cast<uint64_t>(lsn) * kSectorSize,
                                             bytes.data(),
                                             byteCount,
                                             bytesRead) &&
                           bytesRead == byteCount;
                }
            }

            if (!read && buildVirtualIso())
            {
                read = true;
                for (uint32_t sector = 0u; sector < sectors; ++sector)
                {
                    if (!readVirtualSector(lsn + sector, bytes.data() + static_cast<size_t>(sector) * kSectorSize))
                    {
                        read = false;
                        break;
                    }
                }
            }

            return read;
        }

        IopHost &host;
        IopMemory &memory;
        IopKernel &kernel;
        Callback callback;
        std::optional<CompletionCallback> completionCallback;
        bool initialized = false;
        uint32_t mediaMode = kCdvdMediaAuto;
        uint32_t currentLsn = 0u;
        uint32_t lastError = kCdvdErrorNone;
        uint32_t streamFlag = 0u;
        uint32_t lastReadTimeout = 0u;
        int interruptEventFlagId = 0;
        uint64_t imageHandle = 0u;
        uint32_t fsvReadBuffer = 0u;
        uint32_t searchTraceCount = 0u;
        uint32_t dvdTraceCount = 0u;
        uint32_t internalState = 0u;
        uint32_t dvdRemaining = 0u;
        uint32_t dvdNextLsn = 0u;
        Callback dvdCallback;
        bool virtualIsoBuilt = false;
        bool virtualIsoValid = false;
        uint32_t volumeSectors = 0u;
        std::vector<IsoNode> nodes;
        std::unordered_map<uint32_t, std::array<uint8_t, kSectorSize>> metadataSectors;
    };

    IopCdvd::IopCdvd(IopHost &host, IopMemory &memory, IopKernel &kernel)
        : m_impl(std::make_unique<Impl>(host, memory, kernel))
    {
    }

    IopCdvd::~IopCdvd() = default;

    void IopCdvd::reset() noexcept
    {
        m_impl->reset();
    }

    bool IopCdvd::dispatchImport(uint16_t ordinal, IopCpuState &cpu)
    {
        const bool handled = m_impl->dispatchImport(ordinal, cpu);
        if (handled)
            m_impl->syncInternalError();
        return handled;
    }

    void IopCdvd::serviceDma()
    {
        m_impl->serviceDma();
    }

    std::optional<IopCdvd::FileHandle> IopCdvd::openFile(std::string_view path)
    {
        return m_impl->openFile(path);
    }

    size_t IopCdvd::readFile(const FileHandle &file, uint32_t offset, uint8_t *destination, size_t size)
    {
        return m_impl->readFile(file, offset, destination, size);
    }

    bool IopCdvd::hasBuiltinRpc(uint32_t sid) noexcept
    {
        return sid == 0x80000592u || sid == 0x80000593u ||
               sid == 0x8000059au || sid == 0x8000059cu;
    }

    RpcResult IopCdvd::handleRpc(const RpcRequest &request)
    {
        RpcResult result{};
        if (!hasBuiltinRpc(request.sid))
            return result;
        uint32_t parameter = 0u;
        uint16_t ordinal = 0u;
        uint32_t responseBytes = 4u;
        if (request.sid == 0x80000592u)
        {
            ordinal = 4u;
            responseBytes = 16u;
        }
        else if (request.sid == 0x8000059au || request.sid == 0x8000059cu)
            ordinal = 13u;
        else
        {
            switch (request.function)
            {
            case 3u: ordinal = 12u; break;
            case 4u: ordinal = 8u; break;
            case 12u: ordinal = 28u; break;
            case 34u: ordinal = 75u; break;
            default: return result;
            }
        }
        if (ordinal == 4u || ordinal == 13u || ordinal == 75u)
        {
            if (request.send.size < 4u || !m_impl->hostInterface().readGuest(request.send.address, &parameter, 4u))
                return result;
        }
        IopCpuState context{};
        context.gpr[4] = parameter;
        if (!dispatchImport(ordinal, context))
            return result;
        // No physical CDVDFSV IRX is loaded for this native provider, so its
        // version is zero. CDVDMAN's version comes from the existing backend.
        std::array<uint32_t, 4u> response{context.gpr[2], 0u, 0u, 0u};
        if (responseBytes == 16u)
        {
            context.gpr[4] = 0xfffffff7u;
            if (dispatchImport(50u, context))
                response[2] = context.gpr[2];
        }
        if (request.receive.size != 0u &&
            !m_impl->hostInterface().writeGuest(request.receive.address, response.data(),
                                    std::min(request.receive.size, responseBytes)))
            return result;
        result.handled = true;
        result.resultAddress = request.receive.address;
        result.serverDispatchPolicy = ServerDispatchPolicy::Suppress;
        result.signalCompletion = true;
        return result;
    }

    std::optional<IopCdvd::CompletionCallback> IopCdvd::takeCompletionCallback() noexcept
    {
        return m_impl->takeCompletionCallback();
    }
}

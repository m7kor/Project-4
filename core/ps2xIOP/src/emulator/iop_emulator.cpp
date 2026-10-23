#include "iop_emulator.h"
#include "imports/iop_cdvd.h"
#include "imports/iop_dmacman.h"
#include "core/iop_cpu.h"
#include "imports/iop_heaplib.h"
#include "imports/iop_imports.h"
#include "imports/iop_intrman.h"
#include "imports/iop_ioman.h"
#include "core/iop_kernel.h"
#include "imports/iop_loadcore.h"
#include "core/iop_memory.h"
#include "core/iop_secrman.h"
#include "services/iop_module_loader.h"
#include "services/iop_rpc.h"
#include "imports/iop_stdio.h"
#include "imports/iop_sysclib.h"
#include "imports/iop_sysmem.h"
#include "imports/iop_timrman.h"
#include "imports/iop_vblank.h"
#include "iop_emulator_const.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <unordered_map>
#include <vector>
#include <array>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <map>
#include <optional>
#include <span>
#include <sstream>
#include <utility>
#include <stdexcept>

namespace ps2x::iop::detail
{
    namespace
    {
        constexpr uint32_t kRamSize = IopMemory::RamSize;
        constexpr uint32_t kKernelHeapBase = IopMemory::HeapBase;
        constexpr uint32_t kKernelHeapLimit = IopMemory::HeapLimit;
        constexpr uint32_t kCallStackBase = kKernelHeapLimit;
        constexpr uint32_t kCallStackLimit = 0x001FFF00u;
        constexpr uint32_t kCallStackSize = 0x2000u;
        constexpr uint32_t kCallStackCapacity = (kCallStackLimit - kCallStackBase) / kCallStackSize;
        constexpr uint64_t kCdvdCompletionCycles = 128u;

        uint32_t physicalAddress(uint32_t address)
        {
            return IopMemory::physicalAddress(address);
        }

        int32_t sign16(uint32_t value)
        {
            return static_cast<int16_t>(value & 0xFFFFu);
        }

        bool iequals(std::string_view lhs, std::string_view rhs)
        {
            if (lhs.size() != rhs.size())
                return false;
            for (size_t i = 0; i < lhs.size(); ++i)
            {
                if (std::tolower(static_cast<unsigned char>(lhs[i])) !=
                    std::tolower(static_cast<unsigned char>(rhs[i])))
                    return false;
            }
            return true;
        }

    }

    class IopEmulator::Impl final : public IopGuestExecutor
    {
    public:
        using CpuState = IopCpuState;

        struct Module
        {
            int id = 0;
            std::string path;
            std::string name;
            uint32_t base = 0;
            uint32_t size = 0;
            uint32_t entry = 0;
            uint32_t gp = 0;
            bool resident = false;
            bool started = false;
        };

        struct GuestCallback
        {
            uint32_t function = 0;
            uint32_t gp = 0;
        };

        struct ScheduledGuestCallback
        {
            uint32_t function = 0u;
            uint32_t gp = 0u;
            uint32_t argument = 0u;
        };

        struct ResumableCall
        {
            CpuState cpu;
            uint32_t stackSlot = 0u;
        };

        explicit Impl(IopHost &hostRef)
            : host(hostRef),
              sysmem(host, memory),
              kernel(memory),
              cdvd(host, memory, kernel),
              vblank(kernel, intrman),
              rpc(host, memory, kernel, cdvd),
              sysclib(memory),
              stdio(host, memory),
              heaplib(memory),
              intrman(memory),
              timrman(),
              ioman(memory, cdvd),
              cpuCore(memory),
              imports(memory),
              loadcore(memory, imports)
        {
            reset();
        }

        void reset()
        {
            memory.reset();
            if (std::getenv("PS2X_IOP_SPU2_NATIVE") && !memory.enableNativeSpu2())
                throw std::runtime_error("native SPU2 requested but not compiled");
            if (std::getenv("PS2X_IOP_SIO2_NATIVE"))
            {
                const auto root = std::filesystem::path(host.hostPath(HostPathKind::MemoryCardRoot));
                if (root.empty()) throw std::runtime_error("native SIO2 needs a memory-card storage directory");
                std::filesystem::create_directories(root);
                if (!memory.enableNativeSio2(root / "native-card-0.ps2",
                    [this](int port, int slot, IopHost::PadInput &input) { return host.samplePadInput(port, slot, input); }))
                    throw std::runtime_error("native SIO2 could not open the raw memory card");
            }
            kernel.reset();
            modules.clear();
            imports.reset();
            rpc.reset();
            cdvd.reset();
            cdvdTraceCount = 0u;
            soundHandlerTraceCount = 0u;
            soundTransferTraceCount = 0u;
            selectedIopPc.reset();
            selectedIopPcTraceCount = 0u;
            traceInterruptOwnership = std::getenv("PS2X_TRACE_IOP_INTERRUPT_OWNER") != nullptr;
            interruptOwner = {};
            interruptChangeCount = 0u;
            maskedSliceTraceCount = 0u;
            contextControlTraceCount = 0u;
            extendedThreadTrace = std::getenv("PS2X_TRACE_IOP_THREADS") != nullptr;
            // Diagnostics are configured before startup/reset, like the other
            // trace options. Never scan the process environment per IOP slice.
            captureDiagnostics = std::getenv("PS2X_CAPTURE_DIR") != nullptr;
            const char *stageOption = std::getenv("PS2X_PROFILE_IOP_STAGES");
            profileStages = stageOption && std::string_view(stageOption) == "1";
            stageCalls = 0u; stageSamples = 0u; stageRows = 0u;
            stageIdle = 0u; stageReady = 0u; stageNanoseconds.fill(0u);
            threadTraceCount = 0u;
            nextThreadTraceCycle = 0u;
            if (const char *selection = std::getenv("PS2X_TRACE_IOP_PC"))
            {
                char *end = nullptr;
                const auto value = std::strtoull(selection, &end, 0);
                if (end != selection && *end == '\0' && value <= UINT32_MAX && (value & 3u) == 0u)
                    selectedIopPc = static_cast<uint32_t>(value);
            }
            intrman.reset();
            vblank.reset();
            timrman.reset();
            ioman.reset();
            pendingDmaInterrupts.clear();
            pendingGuestCallbacks.clear();
            nextModuleId = 1;
            moduleCursor = kModuleLoadBase;
            totalCycles = 0;
            totalInstructions = 0;
            eeCycleCarry = 0;
            activeCpu = nullptr;
            lastError.clear();
            servicingDmaInterrupts = false;
            servicingGuestCallbacks = false;
            callDepth = 0u;
            resumableCalls.clear();
            callStackLeases.fill(false);
            runtimeFaulted = false;
            secrMcCommandHandler = {};
            secrMcDevIdHandler = {};
            mechaAuth.reset();
            checkKelfPathCallback = {};
        }

        uint8_t read8(uint32_t address) const
        {
            return memory.read8(address);
        }

        uint16_t read16(uint32_t address) const
        {
            return memory.read16(address);
        }

        uint32_t read32(uint32_t address) const
        {
            return memory.read32(address);
        }

        void write8(uint32_t address, uint8_t value)
        {
            memory.write8(address, value);
            schedulePendingDma();
        }

        void write16(uint32_t address, uint16_t value)
        {
            memory.write16(address, value);
            schedulePendingDma();
        }

        void write32(uint32_t address, uint32_t value)
        {
            memory.write32(address, value);
            schedulePendingDma();
        }

        void schedulePendingDma()
        {
            cdvd.serviceDma();
            if (const auto callback = cdvd.takeCompletionCallback())
                pendingGuestCallbacks.emplace(totalCycles + kCdvdCompletionCycles,
                    ScheduledGuestCallback{callback->address, callback->gp, callback->reason});
            while (const auto dma = memory.takeDmaStart())
            {
                pendingDmaInterrupts[dma->irq] = totalCycles + dma->delayCycles;
                if ([] { static const char *const cached = std::getenv("PS2X_TRACE_IOP_IRQ"); return cached; }())
                {
                    static uint32_t traceCount = 0u;
                    if (traceCount++ < 128u)
                    {
                        std::ostringstream out;
                        out << "[IOP DMA completion scheduled] irq=0x" << std::hex << dma->irq
                            << " cycles=" << std::dec << totalCycles << " due=" << totalCycles + dma->delayCycles;
                        log(LogLevel::Info, out.str());
                    }
                }
            }
        }

        bool readRam(uint32_t address, void *destination, size_t size) const
        {
            return memory.readRam(address, destination, size);
        }

        bool writeRam(uint32_t address, const void *source, size_t size)
        {
            return memory.writeRam(address, source, size);
        }

        bool zeroRam(uint32_t address, size_t size)
        {
            return memory.zeroRam(address, size);
        }

        bool isHardwareAddress(uint32_t phys) const
        {
            return memory.isHardwareAddress(phys);
        }

        uint32_t allocate(uint32_t size, uint32_t alignment = 16u, std::optional<uint32_t> fixed = std::nullopt)
        {
            return memory.allocate(size, alignment, fixed);
        }

        bool freeAllocation(uint32_t address)
        {
            return memory.freeAllocation(address);
        }

        void log(LogLevel level, std::string_view text)
        {
            host.log(level, text);
        }

        bool checkInterrupt(CpuState &cpu)
        {
            const uint32_t status = cpu.cop0[12];
            if ((status & 1u) == 0u)
                return false;
            if ((status & 0x2u) != 0u)
                return false;
            const bool pending = memory.interruptControl() != 0u && (memory.interruptStatus() & memory.interruptMask()) != 0u;
            if (!pending)
                return false;
            cpu.cop0[13] |= 0x400u;
            cpuCore.raiseException(cpu, 0u, cpu.pc, false);
            return true;
        }

        enum class ImportDisposition
        {
            Handled,
            JumpToGuest,
            Missing,
        };

        ImportDisposition dispatchImport(const IopImportCall &call, CpuState &cpu)
        {
            const uint32_t a0 = cpu.gpr[4];
            auto setV0 = [&](uint32_t value)
            {
                cpu.gpr[2] = value;
            };

            if (iequals(call.library, "sysmem") && sysmem.dispatchImport(call.ordinal, cpu))
                return ImportDisposition::Handled;

            const bool traceCdvd = iequals(call.library, "cdvdman") && [] { static const char *const cached = std::getenv("PS2X_TRACE_CDVD"); return cached; }() != nullptr;
            const auto cdvdArgs = std::array<uint32_t, 4>{cpu.gpr[4], cpu.gpr[5], cpu.gpr[6], cpu.gpr[7]};
            const bool cdvdHandled = iequals(call.library, "cdvdman") && cdvd.dispatchImport(call.ordinal, cpu);
            // PS2X_TRACE_CDVD_LIMIT raises the 512-line cap for traces that
            // must reach past boot (a stage load minutes into a run).
            static const uint64_t cdvdTraceLimit = []() -> uint64_t
            {
                const char *value = [] { static const char *const cached = std::getenv("PS2X_TRACE_CDVD_LIMIT"); return cached; }();
                return value && *value ? std::strtoull(value, nullptr, 10) : 512u;
            }();
            if (traceCdvd && cdvdTraceCount++ < cdvdTraceLimit)
            {
                std::ostringstream out;
                out << "[CDVD import] cycles=" << totalCycles << " ordinal=" << call.ordinal << " pc=0x" << std::hex << cpu.pc
                    << " ra=0x" << cpu.gpr[31];
                for (size_t i = 0; i < cdvdArgs.size(); ++i)
                    out << " a" << i << "=0x" << cdvdArgs[i];
                out << " v0=0x" << cpu.gpr[2] << " handled=" << cdvdHandled;
                log(LogLevel::Info, out.str());
            }
            if (cdvdHandled)
            {
                if (const auto callback = cdvd.takeCompletionCallback())
                {
                    pendingGuestCallbacks.emplace(
                        totalCycles + kCdvdCompletionCycles,
                        ScheduledGuestCallback{
                            callback->address,
                            callback->gp,
                            callback->reason,
                        });
                }
                return ImportDisposition::Handled;
            }

            if (iequals(call.library, "loadcore") && loadcore.dispatchImport(call.ordinal, cpu))
                return ImportDisposition::Handled;

            if (iequals(call.library, "thbase") || iequals(call.library, "threadman"))
            {
                return kernel.dispatchThreadImport(call.ordinal, cpu, totalCycles)
                           ? ImportDisposition::Handled
                           : ImportDisposition::Missing;
            }
            if (iequals(call.library, "thsemap"))
            {
                return kernel.dispatchSemaphoreImport(call.ordinal, cpu)
                           ? ImportDisposition::Handled
                           : ImportDisposition::Missing;
            }
            if (iequals(call.library, "thevent"))
            {
                return kernel.dispatchEventImport(call.ordinal, cpu)
                           ? ImportDisposition::Handled
                           : ImportDisposition::Missing;
            }
            if (iequals(call.library, "thmsgbx"))
                return kernel.dispatchMailboxImport(call.ordinal, cpu)
                           ? ImportDisposition::Handled : ImportDisposition::Missing;
            if (iequals(call.library, "sifcmd"))
            {
                return rpc.dispatchSifCmdImport(call.ordinal, cpu)
                           ? ImportDisposition::Handled
                           : ImportDisposition::Missing;
            }
            if (iequals(call.library, "intrman") && intrman.dispatchImport(call.ordinal, cpu, *this))
                return ImportDisposition::Handled;
            if (iequals(call.library, "secrman"))
            {
                switch (call.ordinal)
                {
                case 4: // SecrSetMcCommandHandler
                    secrMcCommandHandler = {a0, cpu.gpr[28]};
                    setV0(0);
                    return ImportDisposition::Handled;
                case 5: // SecrSetMcDevIDHandler
                    secrMcDevIdHandler = {a0, cpu.gpr[28]};
                    setV0(0);
                    return ImportDisposition::Handled;
                case 6: // SecrAuthCard
                case 7: // SecrResetAuthCard
                {
                    const IopSecrman::Transfer transfer = [this](int port, int slot,
                        std::span<const uint8_t> input, std::vector<uint8_t> &output, uint32_t &status) {
                        return transferSecurityPacket(port, slot, input, output, status);
                    };
                    const IopSecrman::Mecha mecha = [this](uint8_t command,
                        std::span<const uint8_t> input, std::vector<uint8_t> &output) {
                        return mechaAuth.exchange(command, input, output);
                    };
                    bool success = false;
                    if (call.ordinal == 6)
                        success = IopSecrman::authenticate(static_cast<int>(a0), static_cast<int>(cpu.gpr[5]),
                            static_cast<int>(cpu.gpr[6]), transfer, mecha);
                    else
                        IopSecrman::reset(static_cast<int>(a0), static_cast<int>(cpu.gpr[5]),
                            static_cast<int>(cpu.gpr[6]), transfer, mecha);
                    setV0(success ? 1u : 0u);
                    return ImportDisposition::Handled;
                }
                default:
                    break;
                }
            }
            if (iequals(call.library, "modload"))
            {
                if (call.ordinal == 10u) // LoadModuleBuffer(buffer): load, do not execute.
                {
                    std::vector<uint8_t> image;
                    const bool valid = readIopElf(a0, image);
                    if (!valid && captureDiagnostics)
                    {
                        static uint32_t reports = 0u;
                        if (reports++ < 8u)
                        {
                            std::ostringstream out;
                            out << "[IOP module buffer rejected] ptr=0x" << std::hex << a0
                                << " words=" << memory.read32(a0) << ',' << memory.read32(a0 + 4u)
                                << ',' << memory.read32(a0 + 8u) << ',' << memory.read32(a0 + 12u);
                            log(LogLevel::Warning, out.str());
                        }
                    }
                    const auto loaded = valid ? loadImage("buffer", image, nullptr, 0u, false)
                                              : ModuleLoadResult{true, -1, -1};
                    setV0(static_cast<uint32_t>(loaded.moduleId));
                    return ImportDisposition::Handled;
                }
                if (call.ordinal == 8u) // StartModule(id, name, arglen, args, result).
                {
                    // o32 places the fifth argument at sp+16, not in a3.
                    const uint32_t resultAddress = memory.read32(cpu.gpr[29] + 16u);
                    const int32_t result = startLoadedModule(static_cast<int32_t>(a0),
                        cpu.gpr[5], cpu.gpr[6], cpu.gpr[7], resultAddress);
                    if (result < 0 && captureDiagnostics)
                    {
                        static uint32_t reports = 0u;
                        if (reports++ < 8u)
                        {
                            std::ostringstream out;
                            out << "[IOP module start rejected] id=" << static_cast<int32_t>(a0)
                                << " arglen=" << cpu.gpr[6] << " args=0x" << std::hex << cpu.gpr[7]
                                << " result=0x" << resultAddress << " bytes=";
                            for (uint32_t i = 0; i < std::min(cpu.gpr[6], 64u); ++i)
                                out << static_cast<uint32_t>(memory.read8(cpu.gpr[7] + i)) << ',';
                            log(LogLevel::Warning, out.str());
                        }
                    }
                    setV0(static_cast<uint32_t>(result));
                    return ImportDisposition::Handled;
                }
                if (call.ordinal == 13u)
                {
                    checkKelfPathCallback = {a0, cpu.gpr[28]};
                    setV0(0);
                    return ImportDisposition::Handled;
                }
            }
            if (iequals(call.library, "ioman") && ioman.dispatchImport(call.ordinal, cpu, *this))
                return ImportDisposition::Handled;
            if (iequals(call.library, "ioman") && call.ordinal == 31u && captureDiagnostics)
            {
                std::ostringstream out;
                out << "[IOP devctl request] device=" << memory.readString(a0, 64u)
                    << " cmd=0x" << std::hex << cpu.gpr[5]
                    << " arg=0x" << cpu.gpr[6] << " arglen=0x" << cpu.gpr[7]
                    << " buf=0x" << memory.read32(cpu.gpr[29] + 16u)
                    << " buflen=0x" << memory.read32(cpu.gpr[29] + 20u);
                log(LogLevel::Info, out.str());
            }
            if (iequals(call.library, "sifman"))
            {
                return rpc.dispatchSifManImport(call.ordinal, cpu)
                           ? ImportDisposition::Handled
                           : ImportDisposition::Missing;
            }
            if (iequals(call.library, "vblank") && vblank.dispatchImport(call.ordinal, cpu, totalCycles))
                return ImportDisposition::Handled;
            if (iequals(call.library, "timrman") && timrman.dispatchImport(call.ordinal, cpu, totalCycles))
                return ImportDisposition::Handled;
            if (iequals(call.library, "dmacman"))
            {
                if (dispatchDmacmanRegister(memory, call.ordinal, cpu))
                {
                    schedulePendingDma();
                    return ImportDisposition::Handled;
                }
                setV0(0);
                return ImportDisposition::Handled;
            }
            if (iequals(call.library, "stdio") && stdio.dispatchImport(call.ordinal, cpu))
                return ImportDisposition::Handled;
            if (iequals(call.library, "sysclib"))
            {
                return sysclib.dispatchImport(call.ordinal, cpu)
                           ? ImportDisposition::Handled
                           : ImportDisposition::Missing;
            }
            if (iequals(call.library, "heaplib") && heaplib.dispatchImport(call.ordinal, cpu))
                return ImportDisposition::Handled;

            const uint32_t target = imports.resolve(call.library, call.ordinal, call.version);
            if (target != 0u)
            {
                const bool soundHandler = call.ordinal == 2u || call.ordinal == 4u ||
                                          call.ordinal == 26u || call.ordinal == 27u;
                const bool soundTransfer = call.ordinal == 17u || call.ordinal == 18u;
                if (iequals(call.library, "libsd") && [] { static const char *const cached = std::getenv("PS2X_TRACE_IOP_SOUND"); return cached; }() &&
                    ((soundHandler && soundHandlerTraceCount < 64u) ||
                     (soundTransfer && soundTransferTraceCount < 128u)))
                {
                    if (soundHandler) ++soundHandlerTraceCount;
                    else ++soundTransferTraceCount;
                    uint32_t fifthArgument = 0u;
                    const uint64_t stackArgument = static_cast<uint64_t>(cpu.gpr[29]) + 16u;
                    const bool fifthValid = stackArgument <= UINT32_MAX &&
                        memory.readRam(static_cast<uint32_t>(stackArgument), &fifthArgument, sizeof(fifthArgument));
                    std::ostringstream out;
                    out << "[IOP sound import] ordinal=" << call.ordinal << " cycles=" << totalCycles
                        << " pc=0x" << std::hex << cpu.pc << " ra=0x" << cpu.gpr[31]
                        << " target=0x" << target << " gp=0x" << cpu.gpr[28];
                    for (unsigned i = 0u; i < 4u; ++i)
                        out << " a" << i << "=0x" << cpu.gpr[4u + i];
                    out << " a4=0x" << fifthArgument << " a4_valid=" << fifthValid
                        << " control=0x" << memory.interruptControl();
                    log(LogLevel::Info, out.str());
                }
                cpu.pc = target;
                cpu.branchPending = false;
                return ImportDisposition::JumpToGuest;
            }

            std::ostringstream out;
            out << "[IOP] unhandled import " << call.library << ':' << call.ordinal
                << " version=0x" << std::hex << call.version << " pc=0x" << cpu.pc;
            log(LogLevel::Warning, out.str());
            setV0(0);
            return ImportDisposition::Missing;
        }

        void observeInterruptControl(uint32_t previous, uint32_t pc, uint32_t ra)
        {
            if (!traceInterruptOwnership || previous == memory.interruptControl())
                return;
            interruptOwner = {totalCycles, pc, ra};
            if (interruptChangeCount++ < 256u)
            {
                std::ostringstream out;
                out << "[IOP interrupt control] cycles=" << totalCycles << " pc=0x" << std::hex
                    << pc << " ra=0x" << ra << " before=0x" << previous
                    << " after=0x" << memory.interruptControl();
                log(LogLevel::Info, out.str());
            }
        }

        bool step(CpuState &cpu)
        {
            memory.setSpu2Cycle(totalCycles);
            if (cpu.stopped)
                return false;
            if (cpu.pc == kThreadReturnSentinel || cpu.pc == kCallReturnSentinel)
            {
                cpu.stopped = true;
                return false;
            }
            if (physicalAddress(cpu.pc) >= kRamSize)
            {
                std::ostringstream out;
                out << "[IOP] execution outside RAM pc=0x" << std::hex << cpu.pc;
                log(LogLevel::Error, out.str());
                cpu.stopped = true;
                return false;
            }
            if (selectedIopPc && cpu.pc == *selectedIopPc && selectedIopPcTraceCount < 64u)
            {
                ++selectedIopPcTraceCount;
                std::ostringstream out;
                out << "[IOP PC sample] cycles=" << totalCycles << " pc=0x" << std::hex << cpu.pc
                    << " ra=0x" << cpu.gpr[31] << " gp=0x" << cpu.gpr[28]
                    << " sp=0x" << cpu.gpr[29] << " v0=0x" << cpu.gpr[2]
                    << " control=0x" << memory.interruptControl();
                log(LogLevel::Info, out.str());
            }
            if (checkInterrupt(cpu))
                return true;

            const uint32_t controlBefore = memory.interruptControl();
            const uint32_t instructionPc = cpu.pc;
            const uint32_t instructionRa = cpu.gpr[31];
            // PS2X_IOP_PC_HIST=1: every 2^24 instructions print the 12 hottest
            // 64-byte IOP code blocks, to find busy-wait loops.
            static const bool pcHistogram = [] { const char *v = std::getenv("PS2X_IOP_PC_HIST"); return v && *v == '1'; }();
            if (pcHistogram)
            {
                static std::unordered_map<uint32_t, uint64_t> blocks;
                static uint64_t samples = 0;
                ++blocks[instructionPc & ~0x3Fu];
                if ((++samples & 0xFFFFFFu) == 0u)
                {
                    std::vector<std::pair<uint32_t, uint64_t>> top(blocks.begin(), blocks.end());
                    std::sort(top.begin(), top.end(), [](const auto &a, const auto &b) { return a.second > b.second; });
                    std::fprintf(stderr, "[iop:pc]");
                    for (size_t i = 0; i < std::min<size_t>(top.size(), 12u); ++i)
                        std::fprintf(stderr, " %06x:%.1f%%", top[i].first, 100.0 * double(top[i].second) / double(0x1000000));
                    std::fprintf(stderr, "\n");
                    blocks.clear();
                    static bool dumped = false;
                    if (!dumped)
                    {
                        dumped = true;
                        if (std::FILE *f = std::fopen("iop-ram.bin", "wb"))
                        {
                            std::fwrite(memory.ram().data(), 1, memory.ram().size(), f);
                            std::fclose(f);
                        }
                    }
                }
            }
            // Import stubs start with "jr ra": peek the word straight from RAM
            // and skip the full decode (two read32 calls with translation) for
            // every other instruction, the hot path of the interpreter.
            bool maybeImport = true;
            uint32_t instructionWord = 0;
            bool instructionInRam = false;
            {
                const uint32_t physicalPc = IopMemory::physicalAddress(cpu.pc);
                if (physicalPc <= IopMemory::RamSize - 4u)
                {
                    std::memcpy(&instructionWord, memory.ram().data() + physicalPc, sizeof(instructionWord));
                    instructionInRam = true;
                    maybeImport = instructionWord == 0x03E00008u;
                }
            }
            if (const auto import = maybeImport ? imports.decode(cpu.pc) : std::nullopt)
            {
                const ImportDisposition disposition = dispatchImport(*import, cpu);
                observeInterruptControl(controlBefore, instructionPc, instructionRa);
                ++totalInstructions;
                ++totalCycles;
                if (disposition == ImportDisposition::JumpToGuest)
                    return true;
                cpu.pc = cpu.gpr[31];
                cpu.branchPending = false;
                return !cpu.stopped;
            }

            const bool running = instructionInRam ? cpuCore.executeInstruction(cpu, instructionWord)
                                                  : cpuCore.executeInstruction(cpu);
            observeInterruptControl(controlBefore, instructionPc, instructionRa);
            // Only guest stores can start DMA or change CDVD DMA registers.
            // Host/import register writes already schedule through write8/16/32
            // and the dmacman handler. Keep the conservative path when the
            // instruction word was not read directly from resident RAM.
            const uint32_t opcode = instructionWord >> 26u;
            if (!instructionInRam || (opcode >= 0x28u && opcode <= 0x2Bu) || opcode == 0x2Eu)
                schedulePendingDma();
            ++totalInstructions;
            ++totalCycles;
            return running;
        }

        uint32_t runRamBlock(CpuState &cpu, uint32_t instructionBudget)
        {
            // Batch only instructions whose memory accesses stay in RAM.
            // Every instruction is still fetched and executed, including load
            // delay and branch delay slots. Device/import accesses return to
            // step(), and deadlines bound when device services must run.
            static const bool scalar = [] {
                const char *value = std::getenv("PS2X_IOP_SCALAR");
                return (value && *value == '1') || std::getenv("PS2X_IOP_PC_HIST") != nullptr;
            }();
            if (scalar || selectedIopPc || traceInterruptOwnership || cpu.stopped || cpu.yielded)
                return 0;
            const uint32_t status = cpu.cop0[12];
            if ((status & 3u) == 1u && memory.interruptControl() != 0u &&
                (memory.interruptStatus() & memory.interruptMask()) != 0u)
                return 0; // step() delivers the interrupt before fetching.

            uint64_t limit = std::min(totalCycles + instructionBudget, (totalCycles | 127u) + 1u);
            limit = std::min(limit, memory.nextSpu2Event());
            limit = vblank.nextEventCycle(limit);
            if (!pendingDmaInterrupts.empty())
            {
                const uint64_t dmaCheck = pendingDmaInterrupts.size() != lastPendingDmaCount
                    ? totalCycles + 1u : (totalCycles | 63u) + 1u;
                limit = std::min(limit, dmaCheck);
            }
            if (!pendingGuestCallbacks.empty()) limit = std::min(limit, pendingGuestCallbacks.begin()->first);
            const uint64_t start = totalInstructions;
            while (totalCycles < limit && !cpu.stopped && !cpu.yielded)
            {
                const uint32_t pc = IopMemory::physicalAddress(cpu.pc);
                if (pc > IopMemory::RamSize - 4u) break;
                uint32_t word;
                std::memcpy(&word, memory.ram().data() + pc, sizeof(word));
                if (word == 0x03E00008u) break; // imports and return sentinels
                const uint32_t opcode = word >> 26u;
                if (opcode == 0u)
                {
                    const uint32_t function = word & 63u;
                    if (function == 0x0Cu || function == 0x0Du) break;
                }
                else if (opcode >= 0x20u && opcode <= 0x2Eu && opcode != 0x27u &&
                         opcode != 0x2Cu && opcode != 0x2Du)
                {
                    const uint32_t rs = (word >> 21u) & 31u;
                    const uint32_t address = cpu.gpr[rs] + static_cast<uint32_t>(static_cast<int16_t>(word));
                    if (IopMemory::physicalAddress(address) >= IopMemory::RamSize) break;
                }
                else if (opcode > 0x0Fu)
                    break; // COP0, devices and unsupported instruction groups
                memory.setSpu2Cycle(totalCycles);
                const bool running = cpuCore.executeInstruction(cpu, word);
                ++totalInstructions;
                ++totalCycles;
                if (!running) break;
            }
            return static_cast<uint32_t>(totalInstructions - start);
        }

        uint32_t runCpu(CpuState &cpu, uint32_t instructionBudget)
        {
            struct ActiveCpuGuard
            {
                CpuState *&active;
                CpuState *previous;
                ~ActiveCpuGuard() { active = previous; }
            } guard{activeCpu, activeCpu};
            activeCpu = &cpu;
            const uint64_t start = totalInstructions;
            while (!cpu.stopped && !cpu.yielded && totalInstructions - start < instructionBudget)
            {
                const uint32_t advanced = runRamBlock(cpu, static_cast<uint32_t>(instructionBudget - (totalInstructions - start)));
                if (advanced == 0u)
                {
                    if (!step(cpu)) break;
                }
                else if (cpu.stopped)
                    break;
                serviceNativeSound(false);
                vblank.serviceDue(totalCycles, *this);
                // A pending DMA interrupt that cannot be dispatched yet (masked
                // line, no handler, completion not reached) used to be
                // re-examined after every instruction. Re-check every 64 IOP
                // cycles, or at once when the pending set changes; delivery
                // latency stays under two microseconds of IOP time.
                if (!servicingDmaInterrupts && !pendingDmaInterrupts.empty() &&
                    ((totalCycles & 63u) == 0u || pendingDmaInterrupts.size() != lastPendingDmaCount))
                {
                    servicePendingDmaInterrupts();
                    lastPendingDmaCount = pendingDmaInterrupts.size();
                }
                if (!servicingGuestCallbacks && !pendingGuestCallbacks.empty() &&
                    pendingGuestCallbacks.begin()->first <= totalCycles)
                    servicePendingGuestCallbacks();
            }
            activeCpu = guard.previous;
            memory.advanceSpu2(totalCycles);
            return static_cast<uint32_t>(totalInstructions - start);
        }

        std::optional<uint32_t> leaseCallStack()
        {
            for (uint32_t slot = 0u; slot < callStackLeases.size(); ++slot)
            {
                if (!callStackLeases[slot])
                {
                    callStackLeases[slot] = true;
                    return slot;
                }
            }
            return std::nullopt;
        }

        IopEmulator::GuestCallProgress resumeGuestCall(uint64_t token, uint32_t budget)
        {
            using State = IopEmulator::GuestCallState;
            const auto it = resumableCalls.find(token);
            if (activeCpu || budget == 0u || it == resumableCalls.end()) return {};
            auto &call = it->second;
            if (call.cpu.yielded)
                return {State::Yielded, token, 0u, 0u, call.cpu.pc};
            uint32_t used = 0u;
            try { used = runCpu(call.cpu, budget); }
            catch (...)
            {
                callStackLeases[call.stackSlot] = false;
                resumableCalls.erase(it);
                throw;
            }
            const State state = call.cpu.pc == kCallReturnSentinel ? State::Returned :
                call.cpu.yielded ? State::Yielded :
                (call.cpu.stopped || call.cpu.exception) ? State::Faulted : State::Pending;
            IopEmulator::GuestCallProgress progress{state, token,
                state == State::Returned ? call.cpu.gpr[2] : 0u, used, call.cpu.pc};
            if (state == State::Returned || state == State::Faulted)
            {
                callStackLeases[call.stackSlot] = false;
                resumableCalls.erase(it);
            }
            return progress;
        }

        IopEmulator::GuestCallProgress beginGuestCall(uint32_t address, uint32_t a0,
            uint32_t a1, uint32_t a2, uint32_t a3, uint32_t gp, uint32_t budget)
        {
            const bool ramSegment = address < kRamSize ||
                (address >= 0x80000000u && address < 0x80200000u) ||
                (address >= 0xA0000000u && address < 0xA0200000u);
            if (activeCpu || budget == 0u || !ramSegment || address == 0u || (address & 3u) != 0u ||
                physicalAddress(address) > kRamSize - 4u || nextResumableCallToken == UINT64_MAX)
                return {};
            const auto slot = leaseCallStack();
            if (!slot) return {};
            const uint64_t token = ++nextResumableCallToken;
            try
            {
                ResumableCall call{};
                call.stackSlot = *slot;
                call.cpu.pc = address;
                call.cpu.gpr[4] = a0; call.cpu.gpr[5] = a1;
                call.cpu.gpr[6] = a2; call.cpu.gpr[7] = a3;
                call.cpu.gpr[28] = gp;
                call.cpu.gpr[29] = kCallStackLimit - *slot * kCallStackSize - 32u;
                call.cpu.gpr[31] = kCallReturnSentinel;
                resumableCalls.emplace(token, std::move(call));
            }
            catch (...) { callStackLeases[*slot] = false; throw; }
            return resumeGuestCall(token, budget);
        }

        bool cancelGuestCall(uint64_t token)
        {
            if (activeCpu) return false;
            const auto it = resumableCalls.find(token);
            if (it == resumableCalls.end()) return false;
            callStackLeases[it->second.stackSlot] = false;
            resumableCalls.erase(it);
            return true;
        }

        uint32_t callFunction(uint32_t address,
                              uint32_t a0,
                              uint32_t a1,
                              uint32_t a2,
                              uint32_t a3,
                              uint32_t gp,
                              uint32_t budget = kMaxCallInstructions)
        {
            struct CallDepthGuard
            {
                uint32_t &depth;
                ~CallDepthGuard() { --depth; }
            };

            ++callDepth;
            const CallDepthGuard depthGuard{callDepth};
            const auto stackSlot = leaseCallStack();
            struct StackLeaseGuard
            {
                std::array<bool, kCallStackCapacity> &leases;
                std::optional<uint32_t> slot;
                ~StackLeaseGuard() { if (slot) leases[*slot] = false; }
            } stackGuard{callStackLeases, stackSlot};
            CpuState cpu{};
            cpu.pc = address;
            cpu.gpr[4] = a0;
            cpu.gpr[5] = a1;
            cpu.gpr[6] = a2;
            cpu.gpr[7] = a3;
            cpu.gpr[28] = gp;
            if (stackSlot)
            {
                const uint32_t stackTop = kCallStackLimit - *stackSlot * kCallStackSize;
                cpu.gpr[29] = stackTop - 32u;
            }
            else if (resumableCalls.empty() && activeCpu && activeCpu->gpr[29] > kCallStackBase + kStackGuardBytes)
            {
                // Extremely deep re-entrancy borrows unused space below the
                // suspended caller's live frame. Stack growth remains away
                // from the caller, so its saved registers stay intact.
                cpu.gpr[29] = (activeCpu->gpr[29] - kStackGuardBytes) & ~15u;
            }
            else
            {
                lastCallCompleted = false;
                log(LogLevel::Error, "[IOP call incomplete] no available call stack");
                return 0u;
            }
            cpu.gpr[31] = kCallReturnSentinel;
            const uint32_t executedInstructions = runCpu(cpu, budget);
            lastCallCompleted = cpu.pc == kCallReturnSentinel;
            if (!lastCallCompleted)
            {
                std::ostringstream out;
                out << "[IOP call incomplete] entry=0x" << std::hex << address
                    << " pc=0x" << cpu.pc << " cause=0x" << cpu.cop0[13]
                    << " epc=0x" << cpu.cop0[14] << " badvaddr=0x" << cpu.cop0[8]
                    << " ra=0x" << cpu.gpr[31] << " sp=0x" << cpu.gpr[29]
                    << " a0=0x" << cpu.gpr[4] << " a1=0x" << cpu.gpr[5]
                    << " v1=0x" << cpu.gpr[3]
                    << std::dec << " yielded=" << cpu.yielded
                    << " instructions=" << executedInstructions << " budget=" << budget;
                log(LogLevel::Error, out.str());
            }
            return cpu.gpr[2];
        }

        bool lastGuestCallCompleted() const noexcept override { return lastCallCompleted; }

        uint32_t executeGuestFunction(uint32_t address,
                                      uint32_t a0,
                                      uint32_t a1,
                                      uint32_t a2,
                                      uint32_t a3,
                                      uint32_t gp) override
        {
            return callFunction(address, a0, a1, a2, a3, gp);
        }

        uint32_t executeGuestFunctionWithBudget(uint32_t address,
                                                uint32_t a0,
                                                uint32_t a1,
                                                uint32_t a2,
                                                uint32_t a3,
                                                uint32_t gp,
                                                uint32_t instructionBudget) override
        {
            return callFunction(address, a0, a1, a2, a3, gp, instructionBudget);
        }

        // Not that good to use exception handling for control flow but will do for now
        void servicePendingDmaInterrupts()
        {
            // A completed DMA remains pending while CpuDisableIntr/CpuSuspendIntr
            // masks delivery. Do not erase it until the CPU can take interrupts.
            if (servicingDmaInterrupts || pendingDmaInterrupts.empty() || memory.interruptControl() == 0u)
                return;

            servicingDmaInterrupts = true;

            std::vector<std::pair<int, uint64_t>> completed;
            for (const auto &[irq, completionCycle] : pendingDmaInterrupts)
            {
                if (completionCycle <= totalCycles && intrman.canDispatchInterrupt(irq))
                    completed.emplace_back(irq, completionCycle);
            }
            try
            {
                for (const auto &[irq, completionCycle] : completed)
                {
                    // A preceding handler may mask another line. Retain its
                    // completion until dispatch is accepted; guest callbacks
                    // may also schedule a new DMA on the same line.
                    if (!intrman.dispatchInterrupt(irq, *this))
                        continue;
                    const auto pending = pendingDmaInterrupts.find(irq);
                    if (pending != pendingDmaInterrupts.end() && pending->second == completionCycle)
                        pendingDmaInterrupts.erase(pending);
                }
            }
            catch (...)
            {
                servicingDmaInterrupts = false;
                throw;
            }
            servicingDmaInterrupts = false;
        }

        void servicePendingGuestCallbacks()
        {
            if (servicingGuestCallbacks || pendingGuestCallbacks.empty())
                return;

            std::vector<ScheduledGuestCallback> callbacks;
            for (auto it = pendingGuestCallbacks.begin(); it != pendingGuestCallbacks.end();)
            {
                if (it->first > totalCycles)
                    break;
                callbacks.push_back(it->second);
                it = pendingGuestCallbacks.erase(it);
            }
            if (callbacks.empty())
                return;

            servicingGuestCallbacks = true;
            try
            {
                for (const ScheduledGuestCallback &callback : callbacks)
                {
                    if (callback.function != 0u)
                    {
                        (void)callFunction(callback.function,
                                           callback.argument,
                                           0u,
                                           0u,
                                           0u,
                                           callback.gp,
                                           100000u);
                    }
                }
            }
            catch (...)
            {
                servicingGuestCallbacks = false;
                throw;
            }
            servicingGuestCallbacks = false;
        }

        void serviceNativeSound(bool force)
        {
            if (!memory.nativeSpu2Enabled()) return;
            if (!force && (totalCycles & 127u) != 0u && totalCycles < memory.nextSpu2Event()) return;
            memory.advanceSpu2(totalCycles);
            const uint32_t events = memory.takeSpu2Events();
            if (events & 1u) pendingDmaInterrupts[9] = totalCycles;
            if (events & 2u) pendingDmaInterrupts[0x24] = totalCycles;
            if (events & 4u) pendingDmaInterrupts[0x28] = totalCycles;
        }

        void runCycles(uint64_t cycles) noexcept
        {
            if (runtimeFaulted) return;
            // Sample one call in 1024. The default path never queries a timer.
            const bool sampleStages = profileStages && (++stageCalls & 1023u) == 1u;
            std::chrono::steady_clock::time_point stageStart;
            if (sampleStages) stageStart = std::chrono::steady_clock::now();
            const auto markStage = [&](size_t stage) {
                if (!sampleStages) return;
                const auto now = std::chrono::steady_clock::now();
                stageNanoseconds[stage] += static_cast<uint64_t>(
                    std::chrono::duration_cast<std::chrono::nanoseconds>(now - stageStart).count());
                stageStart = now;
            };
            try
            {
                const uint64_t target = totalCycles + cycles;
                while (totalCycles < target)
                {
                    rpc.dispatchPendingRequests(kCallReturnSentinel);
                    markStage(0u);
                    serviceNativeSound(true);
                    markStage(1u);
                    if (captureDiagnostics && totalCycles >= nextThreadTraceCycle &&
                        threadTraceCount < (extendedThreadTrace ? 512u : 64u))
                    {
                        ++threadTraceCount;
                        nextThreadTraceCycle = totalCycles + (extendedThreadTrace ? kIopClockHz : kIopClockHz / 5u);
                        log(LogLevel::Info, kernel.describeThreads());
                    }
                    markStage(2u);
                    servicePendingDmaInterrupts();
                    servicePendingGuestCallbacks();
                    markStage(3u);
                    timrman.serviceDue(totalCycles, *this);
                    vblank.serviceDue(totalCycles, *this);
                    markStage(4u);
                    const uint32_t previousControl = memory.interruptControl();
                    IopThread *next = kernel.beginNextReady(totalCycles);
                    if (traceInterruptOwnership && previousControl != memory.interruptControl() && contextControlTraceCount++ < 64u)
                    {
                        std::ostringstream out;
                        out << "[IOP context control] cycles=" << totalCycles << " thread=" << (next ? next->id : 0)
                            << " before=0x" << std::hex << previousControl
                            << " after=0x" << memory.interruptControl();
                        log(LogLevel::Info, out.str());
                    }
                    markStage(5u);
                    if (!next)
                    {
                        if (sampleStages) ++stageIdle;
                        uint64_t nextWake = kernel.nextWakeCycle(target);
                        for (const auto &[irq, completionCycle] : pendingDmaInterrupts)
                        {
                            // Mature masked events stay pending without
                            // forcing idle execution into single-cycle spins.
                            if (completionCycle > totalCycles)
                                nextWake = std::min(nextWake, completionCycle);
                        }
                        if (!pendingGuestCallbacks.empty())
                            nextWake = std::min(nextWake, pendingGuestCallbacks.begin()->first);
                        nextWake = timrman.nextEventCycle(nextWake);
                        nextWake = vblank.nextEventCycle(nextWake);
                        nextWake = std::min(nextWake, memory.nextSpu2Event());
                        totalCycles = std::max(totalCycles + 1u, std::min(target, nextWake));
                        markStage(6u);
                        continue;
                    }
                    if (sampleStages) ++stageReady;
                    const uint64_t before = totalCycles;
                    const uint32_t sliceEntryPc = next->cpu.pc;
                    runCpu(next->cpu, static_cast<uint32_t>(std::min<uint64_t>(kDefaultSlice, target - totalCycles)));
                    if (traceInterruptOwnership && memory.interruptControl() == 0u && maskedSliceTraceCount++ < 64u)
                    {
                        std::ostringstream out;
                        out << "[IOP masked slice] cycles=" << totalCycles << " thread=" << next->id
                            << " state=" << static_cast<unsigned>(next->state)
                            << " yielded=" << next->cpu.yielded << " stopped=" << next->cpu.stopped
                            << " entry=0x" << std::hex << sliceEntryPc << " pc=0x" << next->cpu.pc
                            << " owner_pc=0x" << interruptOwner.pc << " owner_ra=0x" << interruptOwner.ra
                            << std::dec << " owner_cycles=" << interruptOwner.cycles;
                        log(LogLevel::Info, out.str());
                    }
                    const auto completion = kernel.finishRpcCall(*next, kCallReturnSentinel);
                    kernel.endTimeslice(*next, kThreadReturnSentinel);
                    if (completion)
                        rpc.finishPendingRequest(completion->token, completion->result, completion->faulted);
                    if (totalCycles == before)
                        ++totalCycles;
                    markStage(6u);
                }
                memory.advanceSpu2(totalCycles);
                markStage(7u);
                if (sampleStages) finishStageProfile();
            }
            catch (const std::exception &error)
            {
                runtimeFaulted = true;
                log(LogLevel::Error, std::string("[IOP runtime exception] ") + error.what());
            }
            catch (...)
            {
                runtimeFaulted = true;
                log(LogLevel::Error, "[IOP runtime exception] unknown failure");
            }
        }

        void finishStageProfile() noexcept
        {
            if (++stageSamples < 1024u) return;
            try
            {
                static constexpr const char *names[] = {
                    "rpc_ns", "sound_ns", "trace_ns", "interrupts_ns",
                    "timers_ns", "scheduler_ns", "work_ns", "final_sound_ns"};
                std::ostringstream out;
                out << "[IOP stage profile] samples=" << stageSamples
                    << " period=1024 idle=" << stageIdle << " ready=" << stageReady
                    << " cycles=" << totalCycles;
                for (size_t i = 0u; i < stageNanoseconds.size(); ++i)
                    out << ' ' << names[i] << '=' << stageNanoseconds[i];
                log(LogLevel::Info, out.str());
                stageSamples = 0u; stageIdle = 0u; stageReady = 0u;
                stageNanoseconds.fill(0u);
                if (++stageRows >= 16u) profileStages = false;
            }
            catch (...)
            {
                // A failed diagnostic must never turn into a guest fault.
                profileStages = false;
            }
        }

        bool transferSecurityPacket(int port, int slot, std::span<const uint8_t> input,
                                    std::vector<uint8_t> &output, uint32_t &status)
        {
            if (!secrMcCommandHandler.function || input.empty() || input.size() > 14) return false;
            const uint32_t packet = memory.allocate(192, 16);
            if (!packet) return false;
            struct PacketGuard { IopMemory &memory; uint32_t address;
                ~PacketGuard() { (void)memory.freeAllocation(address); } } guard{memory, packet};
            (void)memory.zeroRam(packet, 192);
            // This game's registered handler uses the original 148-byte SIO2
            // structure: ctrl1 at 4, ctrl2 at 20, descriptors at 40, PIO sizes
            // at 108/112, pointers at 116/120. All pointers are in IOP RAM.
            memory.write32(packet + 4 + (port & 3) * 4, 0xff060505);
            memory.write32(packet + 20 + (port & 3) * 4, 0x3ffff);
            const uint32_t length = static_cast<uint32_t>(input.size());
            memory.write32(packet + 40, (port & 3) | (length << 8) | (length << 18) | 0x40);
            memory.write32(packet + 108, length); memory.write32(packet + 112, length);
            memory.write32(packet + 116, packet + 148); memory.write32(packet + 120, packet + 164);
            (void)memory.writeRam(packet + 148, input.data(), input.size());
            const auto handler = secrMcCommandHandler;
            const uint32_t result = callFunction(handler.function, port, slot, packet, 0, handler.gp);
            const bool completed = lastCallCompleted;
            status = memory.read32(packet);
            output.resize(length);
            const bool read = memory.readRam(packet + 164, output.data(), output.size());
            if ([] { static const char *const cached = std::getenv("PS2X_TRACE_IOP_SECRMAN"); return cached; }())
            {
                static uint32_t count = 0;
                if (count++ < 64)
                {
                    std::ostringstream out;
                    out << "[IOP SECRMAN packet] command=0x" << std::hex << unsigned(input[1])
                        << " mode=0x" << unsigned(input[2]) << " status=0x" << status
                        << " result=0x" << result << " handler=0x" << handler.function
                        << " completed=" << std::dec << completed;
                    log(LogLevel::Info, out.str());
                }
            }
            return completed && result != 0 && read;
        }

        bool readIopElf(uint32_t address, std::vector<uint8_t> &image)
        {
            // IopHost reads EE memory; modload's pointer is instead in IOP RAM.
            return IopModuleLoader::readElfFromIop(memory, address, image);
        }

        uint32_t prepareModuleArguments(std::string_view name, std::span<const uint8_t> packed,
                                        uint32_t &argc)
        {
            std::vector<uint8_t> strings(name.begin(), name.end());
            strings.push_back(0u);
            const size_t argumentOffset = strings.size();
            const size_t argumentEnd = argumentOffset + packed.size();
            strings.insert(strings.end(), packed.begin(), packed.end());
            strings.push_back(0u);
            // Bound strlen-style parsing to the supplied bytes. Some callers count
            // a final string without its NUL; terminate our owned copy safely.
            std::vector<uint32_t> offsets{0u};
            for (size_t offset = argumentOffset; offset < argumentEnd;)
            {
                const auto end = std::find(strings.begin() + offset, strings.end(), uint8_t{0});
                if (end == strings.end())
                    return 0u;
                offsets.push_back(static_cast<uint32_t>(offset));
                offset = static_cast<size_t>(end - strings.begin()) + 1u;
            }
            const uint32_t pointerBytes = static_cast<uint32_t>((offsets.size() + 1u) * 4u);
            const uint32_t args = allocate(pointerBytes + static_cast<uint32_t>(strings.size()), 16u);
            if (!args)
                return 0u;
            writeRam(args + pointerBytes, strings.data(), strings.size());
            for (size_t i = 0; i < offsets.size(); ++i)
                write32(args + static_cast<uint32_t>(i * 4u), args + pointerBytes + offsets[i]);
            write32(args + static_cast<uint32_t>(offsets.size() * 4u), 0u);
            argc = static_cast<uint32_t>(offsets.size());
            if ([] { static const char *const cached = std::getenv("PS2X_TRACE_IOP_SOUND"); return cached; }())
            {
                std::ostringstream out;
                out << "[IOP module arguments] name=" << name << " argc=" << argc
                    << " packed_size=" << packed.size() << " bytes=" << std::hex;
                for (size_t i = 0; i < std::min(packed.size(), size_t{64}); ++i)
                    out << static_cast<uint32_t>(packed[i]) << ',';
                log(LogLevel::Info, out.str());
            }
            return args;
        }

        int32_t startLoadedModule(int32_t id, uint32_t nameAddress, uint32_t argumentSize,
                                 uint32_t argumentsAddress, uint32_t resultAddress)
        {
            const auto it = modules.find(id);
            if (it == modules.end() || it->second.started || argumentSize > 64u * 1024u ||
                (resultAddress != 0u && (physicalAddress(resultAddress) > kRamSize - 4u)))
                return -1;
            const std::string name = nameAddress ? memory.readString(nameAddress, 1024u) : it->second.name;
            std::vector<uint8_t> packed(argumentSize);
            if (argumentSize && !readRam(argumentsAddress, packed.data(), argumentSize))
                return -1;
            uint32_t argc = 0u;
            const uint32_t args = prepareModuleArguments(name, packed, argc);
            if (!args)
                return -1;
            Module &module = it->second;
            module.started = true; // Prevent a recursive or repeated start.
            const uint32_t startResult = callFunction(module.entry, argc,
                                                     args, 0u, 0u, module.gp);
            freeAllocation(args);
            if (!lastCallCompleted)
            {
                module.started = false;
                return -1;
            }
            module.resident = (startResult & 3u) == 0u || (startResult & 3u) == 2u;
            if (resultAddress)
                write32(resultAddress, startResult);
            std::ostringstream out;
            out << "[IOP] started IRX id=" << id << " name=" << name << " result=" << static_cast<int32_t>(startResult);
            log(LogLevel::Info, out.str());
            return id;
        }

        ModuleLoadResult loadImage(std::string path, std::span<const uint8_t> image, const void *arguments, uint32_t argumentSize,
                                  bool start = true)
        {
            ModuleLoadResult result{true, -1, -1};
            if (argumentSize > 64u * 1024u || (argumentSize && !arguments))
                return result;
            const IopImageLoadResult loaded = IopModuleLoader::load(image, memory, moduleCursor);
            moduleCursor = loaded.nextModuleCursor;
            if (!loaded)
            {
                if (loaded.error == IopImageLoadError::InvalidElf)
                    log(LogLevel::Error, "[IOP] rejected invalid/non-MIPS IRX ELF");
                else if (loaded.error == IopImageLoadError::ArenaExhausted)
                    log(LogLevel::Error, "[IOP] module arena exhausted");
                return result;
            }
            if (!loaded.relocationsComplete)
                log(LogLevel::Warning, "[IOP] one or more IRX relocations were unsupported");

            Module module;
            module.id = nextModuleId++;
            module.path = std::move(path);
            const size_t slash = module.path.find_last_of("/\\:");
            module.name = slash == std::string::npos ? module.path : module.path.substr(slash + 1u);
            module.base = loaded.base;
            module.size = loaded.size;
            module.entry = loaded.entry;
            module.gp = loaded.gp;

            if (!start)
            {
                result.moduleId = module.id;
                modules[module.id] = std::move(module);
                return result;
            }

            uint32_t argc = 0u;
            const uint32_t args = prepareModuleArguments(module.path,
                {static_cast<const uint8_t *>(arguments), argumentSize}, argc);
            if (!args)
                return result;
            const uint32_t startResult = callFunction(module.entry, argc, args, 0u, 0u, module.gp);
            freeAllocation(args);
            if (!lastCallCompleted)
            {
                kernel.terminateThreadsInRange(module.base, module.size);
                kernel.cleanupDeadThreads();
                rpc.removeServersInRange(module.base, module.size);
                imports.eraseRange(module.base, module.size);
                return result;
            }
            module.resident = (startResult & 3u) == 0u || (startResult & 3u) == 2u;
            module.started = true;
            result.moduleId = module.id;
            result.startResult = static_cast<int32_t>(startResult);
            modules[module.id] = std::move(module);

            std::ostringstream out;
            out << "[IOP] loaded IRX id=" << result.moduleId
                << " entry=0x" << std::hex << modules[result.moduleId].entry
                << " base=0x" << modules[result.moduleId].base
                << " start=" << std::dec << result.startResult;
            log(LogLevel::Info, out.str());
            return result;
        }

        ModuleLoadResult loadModule(std::string_view path, const void *arguments, uint32_t argumentSize)
        {
            std::vector<uint8_t> image;
            if (!IopModuleLoader::readWholeHostFile(host, path, image))
            {
                log(LogLevel::Warning, std::string("[IOP] failed to open IRX '") + std::string(path) + "'");
                return {true, -1, -1};
            }
            return loadImage(std::string(path), image, arguments, argumentSize);
        }

        ModuleLoadResult loadModuleBuffer(uint32_t guestAddress, const void *arguments, uint32_t argumentSize)
        {
            std::vector<uint8_t> image;
            if (!IopModuleLoader::readElfFromGuest(host, guestAddress, image))
                return {true, -1, -1};
            std::ostringstream tag;
            tag << "buffer@0x" << std::hex << guestAddress;
            return loadImage(tag.str(), image, arguments, argumentSize);
        }

        bool stopModule(int32_t moduleId, int32_t *result)
        {
            auto it = modules.find(moduleId);
            if (it == modules.end())
                return false;
            // A removable IRX normally exposes a stop entry through module metadata. We do not guess it; terminate owned execution and release the image cleanly.
            kernel.terminateThreadsInRange(it->second.base, it->second.size);
            rpc.removeServersInRange(it->second.base, it->second.size);
            imports.eraseRange(it->second.base, it->second.size);
            modules.erase(it);
            kernel.cleanupDeadThreads();
            if (result)
                *result = 0;
            return true;
        }

        IopHost &host;
        bool lastCallCompleted = true;
        uint64_t nextThreadTraceCycle = 0;
        uint32_t threadTraceCount = 0;
        bool extendedThreadTrace = false;
        bool captureDiagnostics = false;
        bool profileStages = false;
        uint64_t stageCalls = 0u;
        uint32_t stageSamples = 0u;
        uint32_t stageRows = 0u;
        uint64_t stageIdle = 0u;
        uint64_t stageReady = 0u;
        std::array<uint64_t, 8> stageNanoseconds{};
        IopMemory memory;
        IopSysmem sysmem;
        IopKernel kernel;
        IopCdvd cdvd;
        uint32_t cdvdTraceCount = 0u;
        uint32_t soundHandlerTraceCount = 0u;
        uint32_t soundTransferTraceCount = 0u;
        std::optional<uint32_t> selectedIopPc;
        uint32_t selectedIopPcTraceCount = 0u;
        struct InterruptOwner
        {
            uint64_t cycles = 0u;
            uint32_t pc = 0u;
            uint32_t ra = 0u;
        } interruptOwner;
        bool traceInterruptOwnership = false;
        uint32_t interruptChangeCount = 0u;
        uint32_t maskedSliceTraceCount = 0u;
        uint32_t contextControlTraceCount = 0u;
        IopVblank vblank;
        IopRpcBridge rpc;
        IopSysclib sysclib;
        IopStdio stdio;
        IopHeaplib heaplib;
        IopIntrman intrman;
        IopTimrman timrman;
        IopIoman ioman;
        IopCpuCore cpuCore;
        IopImportRegistry imports;
        IopLoadcore loadcore;
        std::map<int, Module> modules;
        std::map<int, uint64_t> pendingDmaInterrupts;
        std::multimap<uint64_t, ScheduledGuestCallback> pendingGuestCallbacks;
        uint32_t nextModuleId = 1;
        uint32_t moduleCursor = kModuleLoadBase;
        uint64_t totalCycles = 0;
        uint64_t totalInstructions = 0;
        uint64_t eeCycleCarry = 0;
        size_t lastPendingDmaCount = 0;
        CpuState *activeCpu = nullptr;
        std::string lastError;
        bool servicingDmaInterrupts = false;
        bool servicingGuestCallbacks = false;
        uint32_t callDepth = 0u;
        std::array<bool, kCallStackCapacity> callStackLeases{};
        std::map<uint64_t, ResumableCall> resumableCalls;
        uint64_t nextResumableCallToken = 0u; // Never reused by reset.
        bool runtimeFaulted = false;
        GuestCallback secrMcCommandHandler;
        GuestCallback secrMcDevIdHandler;
        IopMechaAuth mechaAuth;
        GuestCallback checkKelfPathCallback;
    };

    IopEmulator::IopEmulator(IopHost &host)
        : m_impl(std::make_unique<Impl>(host))
    {
    }

    IopEmulator::~IopEmulator() = default;
    uint32_t IopEmulator::readAudio(int16_t *stereo, uint32_t frames)
    {
        return m_impl->memory.readAudio(stereo, frames);
    }

    void IopEmulator::reset()
    {
        m_impl->reset();
    }

    ModuleLoadResult IopEmulator::loadModule(std::string_view path, const void *arguments, uint32_t argumentSize)
    {
        return m_impl->loadModule(path, arguments, argumentSize);
    }

    ModuleLoadResult IopEmulator::loadModuleBuffer(uint32_t guestAddress, const void *arguments, uint32_t argumentSize)
    {
        return m_impl->loadModuleBuffer(guestAddress, arguments, argumentSize);
    }

    bool IopEmulator::stopModule(int32_t moduleId, int32_t *result)
    {
        return m_impl->stopModule(moduleId, result);
    }

    namespace
    {
        // EE cycles accumulated before the IOP runs. The EE scheduler reports
        // cycles after every guest block (a few hundred EE cycles), and each
        // IOP pass services RPC, sound, DMA interrupts, timers and VBlank even
        // when nothing is due, so stepping per block made that service the
        // runner's largest cost. 4096 EE cycles is 512 IOP cycles, about 14
        // microseconds of emulated time. PS2X_IOP_QUANTUM_EE_CYCLES=8 restores
        // per-block stepping.
        uint64_t iopQuantumEeCycles() noexcept
        {
            static const uint64_t quantum = []() -> uint64_t
            {
                const char *value = std::getenv("PS2X_IOP_QUANTUM_EE_CYCLES");
                if (!value || !*value)
                    return 4096u;
                const unsigned long long parsed = std::strtoull(value, nullptr, 10);
                return parsed < 8u ? 8u : (parsed > (1u << 20) ? (1u << 20) : parsed);
            }();
            return quantum;
        }
    }

    void IopEmulator::runEeCycles(uint64_t eeCycles) noexcept
    {
        const uint64_t total = m_impl->eeCycleCarry + eeCycles;
        if (total < iopQuantumEeCycles())
        {
            m_impl->eeCycleCarry = total;
            return;
        }
        const uint64_t iopCycles = total / 8u;
        m_impl->eeCycleCarry = total % 8u;
        if (iopCycles)
            m_impl->runCycles(iopCycles);
    }

    RpcResult IopEmulator::handleRpc(const RpcRequest &request)
    {
        return m_impl->rpc.handleRpc(request, *m_impl);
    }

    IopEmulator::GuestCallProgress IopEmulator::beginGuestCall(uint32_t address, uint32_t a0,
        uint32_t a1, uint32_t a2, uint32_t a3, uint32_t gp, uint32_t instructionBudget)
    {
        return m_impl->beginGuestCall(address, a0, a1, a2, a3, gp, instructionBudget);
    }

    IopEmulator::GuestCallProgress IopEmulator::resumeGuestCall(uint64_t token, uint32_t instructionBudget)
    {
        return m_impl->resumeGuestCall(token, instructionBudget);
    }

    bool IopEmulator::cancelGuestCall(uint64_t token)
    {
        return m_impl->cancelGuestCall(token);
    }

    bool IopEmulator::hasRpcServer(uint32_t sid) const noexcept
    {
        return m_impl->rpc.hasServer(sid);
    }

    void IopEmulator::onSifTransfer(const SifTransfer &transfer)
    {
        m_impl->rpc.onSifTransfer(transfer);
    }

    uint32_t IopEmulator::allocateMemory(uint32_t size, uint32_t alignment)
    {
        return m_impl->memory.allocate(size, alignment);
    }

    bool IopEmulator::freeMemory(uint32_t address)
    {
        return m_impl->memory.freeAllocation(address);
    }

    bool IopEmulator::readMemory(uint32_t address, void *destination, size_t size) const
    {
        return isMemoryRange(address, size) &&
               m_impl->memory.readRam(address, destination, size);
    }

    bool IopEmulator::writeMemory(uint32_t address, const void *source, size_t size)
    {
        return isMemoryRange(address, size) &&
               m_impl->memory.writeRam(address, source, size);
    }

    bool IopEmulator::zeroMemory(uint32_t address, size_t size)
    {
        return isMemoryRange(address, size) &&
               m_impl->memory.zeroRam(address, size);
    }

    bool IopEmulator::isMemoryRange(uint32_t address, size_t size) const
    {
        const bool physicalSegment = address < IopMemory::RamSize;
        const bool cachedSegment = address >= 0x80000000u && address < 0x80200000u;
        const bool uncachedSegment = address >= 0xA0000000u && address < 0xA0200000u;
        if (!physicalSegment && !cachedSegment && !uncachedSegment)
            return false;
        const uint32_t physical = IopMemory::physicalAddress(address);
        return physical <= IopMemory::RamSize && size <= IopMemory::RamSize - physical;
    }

    uint64_t IopEmulator::cycles() const noexcept
    {
        return m_impl->totalCycles;
    }

    uint64_t IopEmulator::instructions() const noexcept
    {
        return m_impl->totalInstructions;
    }

    uint32_t IopEmulator::loadedModuleCount() const noexcept
    {
        return static_cast<uint32_t>(m_impl->modules.size());
    }

    uint32_t IopEmulator::threadCount() const noexcept
    {
        return static_cast<uint32_t>(m_impl->kernel.threadCount());
    }

    uint32_t IopEmulator::rpcServerCount() const noexcept
    {
        return static_cast<uint32_t>(m_impl->rpc.serverCount());
    }

}

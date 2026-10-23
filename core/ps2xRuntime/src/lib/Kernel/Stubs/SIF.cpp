#include "Common.h"
#include "SIF.h"
#include "../Syscalls/RPC.h"
#include "../../ps2_iop_transport.h"
#include "runtime/ps2_address.h"
#include "runtime/ee_scheduler.h"
#include "../../ps2_iop_host.h"
#include "iop_reboot_image.h"

#include <algorithm>
#include <cstring>
#include <cstdlib>
#include <limits>
#include <memory>
#include <vector>
#include <deque>

namespace ps2_stubs
{
    void sceSifCmdIntrHdlr(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        TODO_NAMED("sceSifCmdIntrHdlr", rdram, ctx, runtime);
    }

    void sceSifLoadModule(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifLoadModule(rdram, ctx, runtime);
    }

    void sceSifSendCmd(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t srcAddr = getRegU32(ctx, 7); // $a3
        const uint32_t dstAddr = readStackU32(rdram, ctx, 16);
        const uint32_t size = readStackU32(rdram, ctx, 20);
        if (size != 0u && srcAddr != 0u && dstAddr != 0u)
        {
            std::vector<uint8_t> payload(size);
            bool valid = runtime != nullptr;
            for (uint32_t i = 0; i < size; ++i)
            {
                const uint8_t *src = getConstMemPtr(rdram, srcAddr + i);
                if (!src)
                {
                    valid = false;
                    break;
                }
                payload[i] = *src;
            }
            if (!valid || !runtime->writeIopMemory(dstAddr, payload.data(), payload.size()))
            {
                setReturnS32(ctx, 0);
                return;
            }
        }

        setReturnS32(ctx, 1);
    }

    namespace
    {
        struct Ps2SifDmaTransfer
        {
            uint32_t src = 0;
            uint32_t dest = 0;
            int32_t size = 0;
            int32_t attr = 0;
        };
        static_assert(sizeof(Ps2SifDmaTransfer) == 16u, "Unexpected SIF DMA descriptor size");

        std::mutex g_sifDmaTransferMutex;
        uint32_t g_nextSifDmaTransferId = 1u;
        std::mutex g_sifCmdStateMutex;
        std::unordered_map<uint32_t, uint32_t> g_sifRegs;
        std::unordered_map<uint32_t, uint32_t> g_sifSregs;
        struct SifCmdHandler
        {
            uint32_t function = 0u;
            uint32_t argument = 0u;
        };

        std::unordered_map<uint32_t, SifCmdHandler> g_sifCmdHandlers;
        struct NativeRpcServer
        {
            uint32_t sid = 0u;
            uint32_t buffer = 0u;
        };
        std::unordered_map<uint32_t, NativeRpcServer> g_nativeRpcServers;
        constexpr uint32_t kNativeRpcBufferSize = 16384u;
        uint32_t g_nativeRpcTraceCount = 0u;
        uint64_t g_nativeRpcTimingGeneration = 0u;
        uint64_t g_nativeRpcReadyCycle = 0u;
        struct PendingSifCommand
        {
            uint8_t *rdram;
            PS2Runtime *runtime;
            uint32_t command;
            std::vector<uint8_t> packet;
        };
        std::deque<PendingSifCommand> g_pendingSifCommands;
        bool g_drainingSifCommands = false;
        // A delivery marks the EE receive buffer busy until the guest re-arms
        // SIF0 with (i)sceSifSetDChain, as the hardware DMA does. Guest SIF
        // handlers clear the size word before copying the packet out, and the
        // IOP runs at checkpoints inside that copy loop, so "size == 0" alone
        // let a second packet tear the first. A long timer is only a fallback.
        bool g_sifDeliveryCooling = false;
        uint64_t g_sifDeliveryGeneration = 0;
        // Only guests whose SIF0 handler re-arms with sceSifSetDChain get the
        // re-arm gate; others signal consumption by clearing the size word.
        bool g_sifGuestRearms = false;
        bool queuePendingSifCommand(uint8_t *, PS2Runtime *, uint32_t, const void *, size_t);
        uint32_t g_selectedNativeRpcTraceCount = 0u;
        std::array<uint8_t, 257u> g_selectedNativeRpcFunctionTraceCounts{};
        bool g_iopBootPending = false;
        uint32_t g_sifCmdBuffer = 0u;
        uint32_t g_sifSysCmdBuffer = 0u;
        bool g_sifCmdInitialized = false;
        uint32_t g_sifGetRegLogCount = 0u;
        uint32_t g_sifSetRegLogCount = 0u;

        constexpr uint32_t kSifRegBootStatus = 0x4u;
        constexpr uint32_t kSifRegMainAddr = 0x80000001u;
        constexpr uint32_t kSifRegSubAddr = 0x80000000u;
        constexpr uint32_t kSifRegMsCom = 0x80000002u;
        constexpr uint32_t kSifBootReadyMask = 0x00020000u;

        void seedDefaultSifRegsLocked()
        {
            g_sifRegs.clear();
            g_sifSregs.clear();
            g_sifCmdHandlers.clear();
            g_nativeRpcServers.clear();
            g_nativeRpcTraceCount = 0u;
            ++g_nativeRpcTimingGeneration;
            g_nativeRpcReadyCycle = 0u;
            g_pendingSifCommands.clear();
            g_drainingSifCommands = false;
            g_sifDeliveryCooling = false;
            g_sifGuestRearms = false;
            ++g_sifDeliveryGeneration;
            g_selectedNativeRpcTraceCount = 0u;
            g_selectedNativeRpcFunctionTraceCounts.fill(0u);
            g_iopBootPending = false;
            g_sifCmdBuffer = 0u;
            g_sifSysCmdBuffer = 0u;
            g_sifCmdInitialized = false;
            g_sifGetRegLogCount = 0u;
            g_sifSetRegLogCount = 0u;

            g_sifRegs[kSifRegBootStatus] = kSifBootReadyMask;
            g_sifRegs[kSifRegMainAddr] = 0u;
            g_sifRegs[kSifRegSubAddr] = 0u;
            g_sifRegs[kSifRegMsCom] = 0u;
        }

        bool shouldTraceSifReg(uint32_t reg)
        {
            switch (reg)
            {
            case 0x2u:
            case 0x4u:
            case 0x80000000u:
            case 0x80000001u:
            case 0x80000002u:
                return true;
            default:
                return false;
            }
        }

        struct SifStateInitializer
        {
            SifStateInitializer()
            {
                std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
                seedDefaultSifRegsLocked();
            }
        } g_sifStateInitializer;

        uint32_t allocateSifDmaTransferId()
        {
            std::lock_guard<std::mutex> lock(g_sifDmaTransferMutex);
            uint32_t id = g_nextSifDmaTransferId++;
            if (id == 0u)
            {
                id = g_nextSifDmaTransferId++;
            }
            return id;
        }

        bool isCopyableGuestAddress(uint32_t addr)
        {
            if (Ps2AddressInRange(addr, PS2_SCRATCHPAD_BASE, PS2_SCRATCHPAD_SIZE))
            {
                return true;
            }

            if (addr < PS2_EE_UNCACHED_RAM_MIRROR_BASE)
            {
                return true;
            }

            if (Ps2IsUncachedRamMirrorAddress(addr))
            {
                return true;
            }

            if (Ps2IsKseg01Address(addr))
            {
                return true;
            }

            return false;
        }

        bool canAccessEeRange(const uint8_t *rdram, uint32_t address, uint32_t sizeBytes)
        {
            if (!rdram)
            {
                return false;
            }
            if (sizeBytes == 0u)
            {
                return true;
            }
            if (sizeBytes - 1u > std::numeric_limits<uint32_t>::max() - address)
            {
                return false;
            }
            for (uint32_t i = 0u; i < sizeBytes; ++i)
            {
                const uint32_t byteAddress = address + i;
                if (!isCopyableGuestAddress(byteAddress) || getConstMemPtr(rdram, byteAddress) == nullptr)
                {
                    return false;
                }
            }
            return true;
        }

        bool readEeRange(const uint8_t *rdram, uint32_t address, void *destination, uint32_t sizeBytes)
        {
            if ((!destination && sizeBytes != 0u) || !canAccessEeRange(rdram, address, sizeBytes))
                return false;
            auto *bytes = static_cast<uint8_t *>(destination);
            for (uint32_t i = 0u; i < sizeBytes; ++i)
            {
                const uint8_t *source = getConstMemPtr(rdram, address + i);
                if (!source)
                    return false;
                bytes[i] = *source;
            }
            return true;
        }

        bool canAccessEeCommandRam(const uint8_t *rdram, uint32_t address, uint32_t sizeBytes)
        {
            // Command structures and receive buffers must stay in one RAM
            // range. Generic guest-pointer resolution also mirrors addresses;
            // a DMA packet must not wrap into RAM zero or alias MMIO.
            const uint32_t physical = address & 0x1fffffffu;
            return isCopyableGuestAddress(address) && physical < PS2_RAM_SIZE &&
                   sizeBytes <= PS2_RAM_SIZE - physical &&
                   canAccessEeRange(rdram, address, sizeBytes);
        }

        bool writeEeRange(uint8_t *rdram, uint32_t address, const void *source, uint32_t sizeBytes)
        {
            if ((!source && sizeBytes != 0u) || !canAccessEeRange(rdram, address, sizeBytes))
                return false;
            ps2TraceGuestRangeWrite(rdram, address, sizeBytes, "SIF IOP-to-EE DMA", nullptr);
            const auto *bytes = static_cast<const uint8_t *>(source);
            for (uint32_t i = 0u; i < sizeBytes; ++i)
            {
                uint8_t *destination = getMemPtr(rdram, address + i);
                if (!destination)
                    return false;
                *destination = bytes[i];
            }
            return true;
        }
    }

    void resetSifState()
    {
        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
        seedDefaultSifRegsLocked();
    }

    bool dispatchSifCommand(uint8_t *rdram,
                            PS2Runtime *runtime,
                            uint32_t commandId,
                            const void *packet,
                            size_t packetSize) noexcept
    {
        if (!rdram || !runtime || !packet || packetSize < 16u || packetSize > 112u)
            return false;

        SifCmdHandler registered{};
        uint32_t nativeCmdData = 0u;
        {
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            const auto handler = g_sifCmdHandlers.find(commandId);
            if (handler != g_sifCmdHandlers.end())
                registered = handler->second;
            nativeCmdData = g_sifRegs[kSifRegMainAddr];
        }

        // Libraries running as recompiled guest code register their receive
        // buffer through SYSREG_MAINADDR, rather than calling our HLE handlers.
        // Deliver through SIF0 so their own interrupt handler decodes the packet.
        if (registered.function == 0u)
        {
            uint32_t receiveBuffer = 0u;
            uint32_t occupied = 0u;
            if (nativeCmdData == 0u || !canAccessEeCommandRam(rdram, nativeCmdData, 32u) ||
                !readEeRange(rdram, nativeCmdData, &receiveBuffer, 4u) ||
                receiveBuffer == 0u || !canAccessEeCommandRam(rdram, receiveBuffer, 128u) ||
                !readEeRange(rdram, receiveBuffer, &occupied, 4u))
                return false;
            static const bool traceSif = std::getenv("PS2X_TRACE_SIF") != nullptr;
            if (traceSif)
            {
                uint32_t body[6] = {};
                std::memcpy(body, static_cast<const uint8_t *>(packet) + 16u, std::min<size_t>(packetSize - 16u, sizeof(body)));
                std::cerr << "[SIF to EE] cid=0x" << std::hex << commandId << " buffer=0x" << receiveBuffer
                          << " occupied=0x" << occupied << " pending=" << g_pendingSifCommands.size()
                          << " draining=" << g_drainingSifCommands << " body=" << body[0] << ',' << body[1] << ','
                          << body[2] << ',' << body[3] << ',' << body[4] << ',' << body[5] << std::dec << '\n';
            }
            if ((occupied & 0xffu) != 0u || g_sifDeliveryCooling ||
                (!g_drainingSifCommands && !g_pendingSifCommands.empty()))
                return !g_drainingSifCommands &&
                       queuePendingSifCommand(rdram, runtime, commandId, packet, packetSize);
            std::array<uint8_t, 128u> received{};
            std::memcpy(received.data(), packet, packetSize);
            uint32_t sizeWord = 0u;
            std::memcpy(&sizeWord, received.data(), 4u);
            sizeWord = (sizeWord & 0xffffff00u) | static_cast<uint32_t>(packetSize);
            std::memcpy(received.data(), &sizeWord, 4u);
            std::memcpy(received.data() + 8u, &commandId, 4u);
            if (!writeEeRange(rdram, receiveBuffer, received.data(), received.size()))
                return false;
            g_sifDeliveryCooling = g_sifGuestRearms;
            if (g_sifGuestRearms)
            {
                const uint64_t delivery = ++g_sifDeliveryGeneration;
                runtime->eeScheduler().scheduleTransportCompletion(EeScheduler::kGeneratedCheckpointCycles * 64u,
                    [delivery] { if (delivery == g_sifDeliveryGeneration) g_sifDeliveryCooling = false; });
            }
            try
            {
                ps2_syscalls::dispatchDmacHandlersForCause(rdram, runtime, 5u);
            }
            catch (...)
            {
                const uint32_t empty = 0u;
                writeEeRange(rdram, receiveBuffer, &empty, 4u);
                return false;
            }
            return true;
        }

        if (!runtime->hasFunction(registered.function))
            return false;
        if (!g_drainingSifCommands && !g_pendingSifCommands.empty())
            return queuePendingSifCommand(rdram, runtime, commandId, packet, packetSize);

        try
        {
            GuestInvocation invocation{};
            invocation.kind = GuestInvocationKind::SifCommand;
            invocation.tag = commandId;
            invocation.context = runtime->cpu();
            invocation.context.pc = registered.function;
            const auto *bytes = static_cast<const uint8_t *>(packet);
            invocation.argumentData.assign(bytes, bytes + packetSize);
            SET_GPR_U32(&invocation.context, 4, 0u);
            SET_GPR_U32(&invocation.context, 5, registered.argument);
            SET_GPR_U32(&invocation.context, 6, 0u);
            SET_GPR_U32(&invocation.context, 7, 0u);
            SET_GPR_U32(&invocation.context, 29, 0u);
            SET_GPR_U32(&invocation.context, 31, 0u);
            runtime->eeScheduler().queueInvocation(std::move(invocation));
            return true;
        }
        catch (...)
        {
            return false;
        }
    }

    namespace
    {
        void drainPendingSifCommands(uint64_t generation)
        {
            if (generation != g_nativeRpcTimingGeneration || g_pendingSifCommands.empty()) return;
            auto &pending = g_pendingSifCommands.front();
            PS2Runtime *runtime = pending.runtime;
            g_drainingSifCommands = true;
            const bool delivered = dispatchSifCommand(pending.rdram, runtime, pending.command,
                                                      pending.packet.data(), pending.packet.size());
            g_drainingSifCommands = false;
            if (delivered) g_pendingSifCommands.pop_front();
            if (!g_pendingSifCommands.empty())
                // Leave runnable guest code time to consume the occupied receive buffer.
                runtime->eeScheduler().scheduleTransportCompletion(EeScheduler::kGeneratedCheckpointCycles,
                    [generation] { drainPendingSifCommands(generation); });
        }

        bool queuePendingSifCommand(uint8_t *rdram, PS2Runtime *runtime, uint32_t command,
                                    const void *packet, size_t size)
        {
            const size_t before = g_pendingSifCommands.size();
            try
            {
                if (g_pendingSifCommands.size() >= 1024u) return false;
                const bool first = g_pendingSifCommands.empty();
                const auto *bytes = static_cast<const uint8_t *>(packet);
                g_pendingSifCommands.push_back({rdram, runtime, command, std::vector<uint8_t>(bytes, bytes + size)});
                if (first)
                {
                    const uint64_t generation = g_nativeRpcTimingGeneration;
                    runtime->eeScheduler().scheduleTransportCompletion(EeScheduler::kGeneratedCheckpointCycles,
                        [generation] { drainPendingSifCommands(generation); });
                }
                return true;
            }
            catch (...)
            {
                if (g_pendingSifCommands.size() > before) g_pendingSifCommands.pop_back();
                return false;
            }
        }

        bool handleIopReset(uint8_t *rdram, PS2Runtime *runtime, const std::vector<uint8_t> &payload)
        {
            if (payload.size() != 104u)
                return false;
            std::array<uint32_t, 6u> header{};
            std::memcpy(header.data(), payload.data(), sizeof(header));
            if ((header[0] & 0xffu) != 104u || header[2] != 0x80000003u || header[4] > 80u)
                return false;
            const std::string args(reinterpret_cast<const char *>(payload.data() + 24u), header[4]);
            constexpr std::string_view prefix = "rom0:UDNL ";
            if (!args.starts_with(prefix))
                return false;
            PS2IopHostAdapter host(*runtime);
            const std::string path = host.translateGuestPath(args.substr(prefix.size()));
            std::ifstream input(path, std::ios::binary | std::ios::ate);
            const auto length = input ? input.tellg() : std::streampos(-1);
            if (length <= 0 || length > 16 * 1024 * 1024)
            {
                std::cerr << "[SIF IOP reset failed] reboot image unavailable\n";
                return false;
            }
            std::vector<uint8_t> image(static_cast<size_t>(length));
            input.seekg(0);
            input.read(reinterpret_cast<char *>(image.data()), image.size());
            std::vector<detail::RebootImageFile> files;
            if (!input || !detail::parseRebootImage(image, files))
            {
                std::cerr << "[SIF IOP reset failed] invalid ROMDIR image\n";
                return false;
            }
            // Kernel libraries and CDVDMAN are provided by the native IOP
            // kernel/import layer. Boot the image's RPC services as real IRX.
            std::vector<detail::RebootImageFile> services;
            for (const auto &file : files)
                if (file.name == "FILEIO" || file.name == "CDVDFSV" || file.name == "LOADFILE")
                    services.push_back(file);
            if (services.size() != 3u)
            {
                std::cerr << "[SIF IOP reset failed] required RPC modules absent\n";
                return false;
            }
            PS2IopTransport::reset(runtime);
            {
                std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
                g_nativeRpcServers.clear();
                g_sifRegs[kSifRegMsCom] = 0u;
                ++g_nativeRpcTimingGeneration;
                g_nativeRpcReadyCycle = 0u;
                g_pendingSifCommands.clear();
                g_drainingSifCommands = false;
                g_iopBootPending = false;
            }
            for (const auto &file : services)
            {
                const uint32_t staging = runtime->guestMalloc(file.size, 16u);
                if (staging == 0u || !writeEeRange(rdram, staging, image.data() + file.offset, file.size))
                {
                    if (staging) runtime->guestFree(staging);
                    std::cerr << "[SIF IOP reset failed] module staging failed\n";
                    return false;
                }
                const auto loaded = runtime->loadIopModuleBuffer(staging);
                runtime->guestFree(staging);
                std::cerr << "[SIF IOP boot] module=" << file.name << " id=" << loaded.moduleId
                          << " result=" << loaded.startResult << '\n';
                if (loaded.moduleId < 0 || (loaded.startResult != 0 && loaded.startResult != 2))
                {
                    std::cerr << "[SIF IOP reset failed] RPC module did not start\n";
                    return false;
                }
            }
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            g_iopBootPending = true;
            return true;
        }

        bool handleNativeRpcPacket(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime,
                                   const std::vector<uint8_t> &payload)
        {
            if (payload.size() != 64u)
                return false;
            std::array<uint32_t, 16u> request{};
            std::memcpy(request.data(), payload.data(), payload.size());
            if ((request[0] & 0xffu) != 64u || (request[2] != 0x80000009u && request[2] != 0x8000000au) ||
                request[7] == 0u || !canAccessEeCommandRam(rdram, request[7], 40u) ||
                request[5] == 0u || !canAccessEeCommandRam(rdram, request[5], 64u))
                return false;
            const bool trace = [] { static const char *const cached = std::getenv("PS2X_CAPTURE_DIR"); return cached; }() && g_nativeRpcTraceCount++ < 128u;
            std::array<uint32_t, 16u> reply{};
            reply[0] = 64u;
            reply[2] = 0x80000008u;
            std::copy(request.begin() + 4u, request.begin() + 8u, reply.begin() + 4u);
            reply[8] = request[2];
            uint64_t measuredIopCycles = 0u;
            if (request[2] == 0x80000009u)
            {
                if ((request[0] >> 8u) != 0u)
                    return false;
                if (PS2IopTransport::canBindRpc(runtime, request[8]))
                {
                    std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
                    for (const auto &entry : g_nativeRpcServers)
                    {
                        if (entry.second.sid == request[8])
                        {
                            reply[9] = entry.first;
                            reply[10] = entry.second.buffer;
                            break;
                        }
                    }
                    if (reply[9] == 0u)
                    {
                        const uint32_t allocation = runtime->allocateIopMemory(64u + kNativeRpcBufferSize, 64u);
                        if (allocation != 0u)
                        {
                            reply[9] = allocation;
                            reply[10] = allocation + 64u;
                            const std::array<uint32_t, 16u> descriptor{request[8], 0u, reply[10]};
                            runtime->writeIopMemory(allocation, descriptor.data(), sizeof(descriptor));
                            g_nativeRpcServers[allocation] = {request[8], reply[10]};
                        }
                    }
                }
                if (trace)
                    std::cerr << "[SIF RPC bind] sid=0x" << std::hex << request[8]
                              << " server=0x" << reply[9] << std::dec << '\n';
            }
            else
            {
                NativeRpcServer server{};
                {
                    std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
                    const auto found = g_nativeRpcServers.find(request[13]);
                    if (found == g_nativeRpcServers.end())
                        return false;
                    server = found->second;
                }
                // A selected service has its own bounded trace budget. Boot audio
                // traffic must not consume diagnostics for later card operations.
                bool selectedTrace = false;
                const auto functionTraceIndex = std::min<uint32_t>(request[8], 256u);
                if (const char *selection = [] { static const char *const cached = std::getenv("PS2X_TRACE_NATIVE_RPC_SID"); return cached; }())
                {
                    char *end = nullptr;
                    const auto sid = std::strtoull(selection, &end, 0);
                    selectedTrace = end != selection && *end == '\0' && sid == server.sid &&
                                    g_selectedNativeRpcTraceCount < 64u &&
                                    g_selectedNativeRpcFunctionTraceCounts[functionTraceIndex] < 8u;
                }
                if (selectedTrace)
                {
                    ++g_selectedNativeRpcTraceCount;
                    ++g_selectedNativeRpcFunctionTraceCounts[functionTraceIndex];
                    std::cerr << "[SIF selected RPC request] sid=0x" << std::hex << server.sid
                              << " function=0x" << request[8] << " packet_bytes=0x" << (request[0] >> 8u)
                              << " send_bytes=0x" << request[9] << " receive_bytes=0x" << request[11]
                              << " buffer=0x" << request[1] << " expected_buffer=0x" << server.buffer
                              << " mode=0x" << request[12] << std::dec << '\n';
                }
                if ((request[0] >> 8u) != request[9] ||
                    (request[9] != 0u && request[1] != server.buffer) ||
                    request[12] != 1u || request[9] > kNativeRpcBufferSize || request[11] > kNativeRpcBufferSize ||
                    (request[11] != 0u && (request[10] == 0u ||
                     !canAccessEeCommandRam(rdram, request[10], request[11]))))
                    return false;
                const uint32_t scratch = runtime->nativeRpcScratch();
                if (scratch == 0u || !canAccessEeCommandRam(rdram, scratch, kNativeRpcBufferSize * 2u))
                {
                    return false;
                }
                std::memset(getMemPtr(rdram, scratch + kNativeRpcBufferSize), 0, kNativeRpcBufferSize);
                std::vector<uint8_t> send(request[9]);
                if (!runtime->readIopMemory(server.buffer, send.data(), send.size()) ||
                    !writeEeRange(rdram, scratch, send.data(), static_cast<uint32_t>(send.size())))
                    return false;
                ps2x::iop::RpcRequest call{};
                call.clientAddress = request[7];
                call.serverAddress = request[13];
                call.serverBuffer = server.buffer;
                call.sid = server.sid;
                call.function = request[8];
                call.send = {scratch, request[9]};
                call.receive = {scratch + kNativeRpcBufferSize, request[11]};
                if (const char *selection = [] { static const char *const cached = std::getenv("PS2X_SIF_RPC_ASYNC"); return cached; }())
                {
                    char *end = nullptr;
                    const auto sid = std::strtoull(selection, &end, 0);
                    call.deferredNative = end != selection && *end == '\0' &&
                        (sid == 1u || (sid <= UINT32_MAX && sid == server.sid));
                    if (call.deferredNative)
                    {
                        call.receive = {request[10], request[11]};
                        call.nativeEndPacket = reply;
                    }
                }
                // 1 selects all services; a SID isolates one service for timing diagnosis.
                // Do not perturb boot audio/module traffic when examining a later service.
                bool selectedTiming = false;
                if (const char *selection = [] { static const char *const cached = std::getenv("PS2X_SIF_RPC_TIMING"); return cached; }())
                {
                    char *end = nullptr;
                    const auto sid = std::strtoull(selection, &end, 0);
                    selectedTiming = end != selection && *end == '\0' &&
                                     (sid == 1u || (sid <= UINT32_MAX && sid == server.sid));
                }
                const bool timedRpc = selectedTiming && runtime->eeScheduler().isExecutingGuest();
                const uint64_t iopBefore = timedRpc ? runtime->iopDebugSnapshot().emulatorCycles : 0u;
                const auto result = PS2IopTransport::handleRpc(runtime, rdram, ctx, call);
                if (timedRpc)
                {
                    const uint64_t iopAfter = runtime->iopDebugSnapshot().emulatorCycles;
                    if (iopAfter >= iopBefore) measuredIopCycles = iopAfter - iopBefore;
                    if (selectedTrace)
                        std::cerr << "[SIF RPC timing] sid=0x" << std::hex << call.sid
                                  << " function=0x" << call.function << std::dec
                                  << " iop_cycles=" << measuredIopCycles
                                  << " ee_cycle=" << runtime->eeScheduler().currentCycle() << '\n';
                }
                if (selectedTrace)
                    std::cerr << "[SIF selected RPC dispatch] sid=0x" << std::hex << call.sid
                              << " function=0x" << call.function << " guest_function=0x" << result.guestFunction
                              << std::dec << " handled=" << result.handled << '\n';
                if (!result.handled || result.guestFunction != 0u)
                {
                    static uint32_t unsupportedCount = 0u;
                    if (unsupportedCount++ < 32u)
                        std::cerr << "[SIF RPC unsupported] sid=0x" << std::hex << call.sid
                                  << " function=0x" << call.function << std::dec << '\n';
                    return false;
                }
                if (result.deferredNative) return true;
                if (request[11] != 0u)
                {
                    std::vector<uint8_t> receive(request[11]);
                    const uint32_t source = result.resultAddress ? result.resultAddress : call.receive.address;
                    if (!readEeRange(rdram, source, receive.data(), request[11]) ||
                        !writeEeRange(rdram, request[10], receive.data(), request[11]))
                        return false;
                    if (selectedTrace && receive.size() >= sizeof(uint32_t))
                    {
                        uint32_t word = 0u;
                        std::memcpy(&word, receive.data(), sizeof(word));
                        std::cerr << "[SIF selected RPC reply] sid=0x" << std::hex << call.sid
                                  << " function=0x" << call.function << " word0=0x" << word
                                  << std::dec << '\n';
                    }
                }
                if (trace)
                    std::cerr << "[SIF RPC call] sid=0x" << std::hex << call.sid
                              << " function=0x" << call.function << std::dec << " handled=1\n";
            }
            // Experimental timing uses executed IOP cycles at the 8:1 EE/IOP
            // clock ratio, not a game-specific delay or forced card result.
            // Builtin services with no executed IOP work keep their old path.
            if (measuredIopCycles != 0u)
            {
                auto &scheduler = runtime->eeScheduler();
                const uint64_t now = scheduler.currentCycle();
                const uint64_t start = std::max(now, g_nativeRpcReadyCycle);
                if (measuredIopCycles > (UINT64_MAX - start) / 8u) return false;
                const uint64_t deadline = start + measuredIopCycles * 8u;
                g_nativeRpcReadyCycle = deadline;
                const uint64_t generation = g_nativeRpcTimingGeneration;
                scheduler.scheduleTransportCompletion(deadline - now,
                    [rdram, runtime, reply, generation]() {
                        if (generation != g_nativeRpcTimingGeneration) return;
                        if (!dispatchSifCommand(rdram, runtime, reply[2], reply.data(), sizeof(reply)))
                            std::cerr << "[SIF RPC timing delivery failed] receive buffer unavailable\n";
                    });
                return true;
            }
            return dispatchSifCommand(rdram, runtime, reply[2], reply.data(), sizeof(reply));
        }
    }

    void sceSifAddCmdHandler(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t cid = getRegU32(ctx, 4);
        const uint32_t handler = getRegU32(ctx, 5);
        const uint32_t argument = getRegU32(ctx, 6);
        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
        g_sifCmdHandlers[cid] = SifCmdHandler{handler, argument};
        setReturnS32(ctx, 0);
    }

    void sceSifAllocIopHeap(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        (void)rdram;
        const uint32_t reqSize = getRegU32(ctx, 4);
        setReturnU32(ctx, runtime ? runtime->allocateIopMemory(reqSize, 64u) : 0u);
    }

    void sceSifAllocSysMemory(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        (void)rdram;
        const uint32_t size = getRegU32(ctx, 5);
        setReturnU32(ctx, runtime ? runtime->allocateIopMemory(size, 64u) : 0u);
    }

    void sceSifBindRpc(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifBindRpc(rdram, ctx, runtime);
    }

    void sceSifCheckStatRpc(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifCheckStatRpc(rdram, ctx, runtime);
    }

    void sceSifDmaStat(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        (void)rdram;
        (void)runtime;
        (void)getRegU32(ctx, 4); // trid

        // Transfers are applied immediately by sceSifSetDma in this runtime.
        setReturnS32(ctx, -1);
    }

    void sceSifExecRequest(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }

    void sceSifExitCmd(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
        if (runtime)
            for (const auto &server : g_nativeRpcServers)
                runtime->freeIopMemory(server.first);
        seedDefaultSifRegsLocked();
        setReturnS32(ctx, 0);
    }

    void sceSifExitRpc(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }

    void sceSifFreeIopHeap(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        (void)rdram;
        const uint32_t addr = getRegU32(ctx, 4);
        setReturnS32(ctx, runtime && runtime->freeIopMemory(addr) ? 0 : -1);
    }

    void sceSifFreeSysMemory(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        (void)rdram;
        const uint32_t addr = getRegU32(ctx, 4);
        setReturnS32(ctx, runtime && runtime->freeIopMemory(addr) ? 0 : -1);
    }

    void sceSifGetDataTable(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
        setReturnU32(ctx, g_sifCmdBuffer);
    }

    void sceSifGetIopAddr(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnU32(ctx, getRegU32(ctx, 4));
    }

    void sceSifGetNextRequest(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }

    void sceSifGetOtherData(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t rdAddr = getRegU32(ctx, 4);
        const uint32_t srcAddr = getRegU32(ctx, 5);
        const uint32_t dstAddr = getRegU32(ctx, 6);
        const int32_t sizeSigned = static_cast<int32_t>(getRegU32(ctx, 7));

        if (sizeSigned <= 0)
        {
            setReturnS32(ctx, 0);
            return;
        }

        const uint32_t size = static_cast<uint32_t>(sizeSigned);
        if (size > PS2_RAM_SIZE)
        {
            static uint32_t warnCount = 0;
            if (warnCount < 32u)
            {
                std::cerr << "sceSifGetOtherData rejected oversized transfer size=0x"
                          << std::hex << size << std::dec << std::endl;
                ++warnCount;
            }
            setReturnS32(ctx, -1);
            return;
        }

        if (runtime)
        {
            PS2IopTransport::notifyTransfer(runtime, rdram, {
                                                                ps2x::iop::SifTransferKind::GetOtherData,
                                                                ps2x::iop::SifTransferPhase::BeforeCopy,
                                                                srcAddr,
                                                                dstAddr,
                                                                size,
                                                            });
        }

        std::vector<uint8_t> payload(size);
        if (!runtime || !runtime->isIopMemoryRange(srcAddr, size) ||
            !canAccessEeRange(rdram, dstAddr, size) ||
            !runtime->readIopMemory(srcAddr, payload.data(), payload.size()) ||
            !writeEeRange(rdram, dstAddr, payload.data(), size))
        {
            static uint32_t warnCount = 0;
            if (warnCount < 32u)
            {
                PS2_IF_AGRESSIVE_LOGS({
                    std::cerr << "sceSifGetOtherData copy failed src=0x" << std::hex << srcAddr
                              << " dst=0x" << dstAddr
                              << " size=0x" << size
                              << std::dec << std::endl;
                });
                ++warnCount;
            }
            setReturnS32(ctx, -1);
            return;
        }

        // SifRpcReceiveData_t keeps src/dest/size at offsets 0x10/0x14/0x18.
        if (uint8_t *rd = getMemPtr(rdram, rdAddr))
        {
            std::memcpy(rd + 0x10u, &srcAddr, sizeof(srcAddr));
            std::memcpy(rd + 0x14u, &dstAddr, sizeof(dstAddr));
            std::memcpy(rd + 0x18u, &size, sizeof(size));
        }

        if (runtime)
        {
            PS2IopTransport::notifyTransfer(runtime, rdram, {
                                                                ps2x::iop::SifTransferKind::GetOtherData,
                                                                ps2x::iop::SifTransferPhase::AfterCopy,
                                                                srcAddr,
                                                                dstAddr,
                                                                size,
                                                            });
        }

        setReturnS32(ctx, 0);
    }

    void sceSifGetReg(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t reg = getRegU32(ctx, 4);
        uint32_t value = 0u;
        bool shouldLog = false;
        {
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            if (reg == kSifRegBootStatus && g_iopBootPending)
            {
                g_sifRegs[reg] |= 0x00070000u;
                g_iopBootPending = false;
            }
            auto it = g_sifRegs.find(reg);
            if (it != g_sifRegs.end())
            {
                value = it->second;
            }
            shouldLog = shouldTraceSifReg(reg) && g_sifGetRegLogCount < 128u;
            if (shouldLog)
            {
                ++g_sifGetRegLogCount;
            }
        }
        if (shouldLog)
        {
            PS2_IF_AGRESSIVE_LOGS({
                auto flags = std::cerr.flags();
                std::cerr << "[sceSifGetReg] reg=0x" << std::hex << reg
                          << " value=0x" << value
                          << " pc=0x" << (ctx ? ctx->pc : 0u)
                          << " ra=0x" << (ctx ? getRegU32(ctx, 31) : 0u)
                          << std::dec << std::endl;
                std::cerr.flags(flags);
            });
        }
        setReturnU32(ctx, value);
    }

    void sceSifGetSreg(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t reg = getRegU32(ctx, 4);
        uint32_t value = 0u;
        {
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            auto it = g_sifSregs.find(reg);
            if (it != g_sifSregs.end())
            {
                value = it->second;
            }
        }
        setReturnU32(ctx, value);
    }

    void sceSifInitCmd(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
        g_sifCmdInitialized = true;
        setReturnS32(ctx, 0);
    }

    void sceSifInitIopHeap(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        // The physical IOP allocator is initialized by IopSubsystem::reset().
        setReturnS32(ctx, 0);
    }

    void sceSifInitRpc(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifInitRpc(rdram, ctx, runtime);
    }

    void sceSifIsAliveIop(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 1);
    }

    void sceSifLoadElf(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::sceSifLoadElf(rdram, ctx, runtime);
    }

    void sceSifLoadElfPart(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::sceSifLoadElfPart(rdram, ctx, runtime);
    }

    void sceSifLoadFileReset(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }

    void sceSifLoadIopHeap(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }

    void sceSifLoadModuleBuffer(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::sceSifLoadModuleBuffer(rdram, ctx, runtime);
    }

    void sceSifRebootIop(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        PS2IopTransport::reset(runtime);
        setReturnS32(ctx, 1);
    }

    void sceSifRegisterRpc(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifRegisterRpc(rdram, ctx, runtime);
    }

    void sceSifRemoveCmdHandler(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t cid = getRegU32(ctx, 4);
        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
        g_sifCmdHandlers.erase(cid);
        setReturnS32(ctx, 0);
    }

    void sceSifRemoveRpc(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifRemoveRpc(rdram, ctx, runtime);
    }

    void sceSifRemoveRpcQueue(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifRemoveRpcQueue(rdram, ctx, runtime);
    }

    void sceSifResetIop(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        PS2IopTransport::reset(runtime);
        setReturnS32(ctx, 1);
    }

    void sceSifRpcLoop(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }

    void sceSifSetCmdBuffer(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t newBuffer = getRegU32(ctx, 4);
        uint32_t prev = 0u;
        {
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            prev = g_sifCmdBuffer;
            g_sifCmdBuffer = newBuffer;
        }
        setReturnU32(ctx, prev);
    }

    void isceSifSetDChain(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        sceSifSetDChain(rdram, ctx, runtime);
    }

    void isceSifSetDma(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        sceSifSetDma(rdram, ctx, runtime);
    }

    void sceSifSetDChain(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        (void)rdram;
        // The EE re-armed SIF0: the receive buffer may take the next packet.
        static const bool gateEnabled = [] {
            const char *v = std::getenv("PS2X_SIF_REARM_GATE");
            return !(v && *v == '0');
        }();
        g_sifGuestRearms = gateEnabled;
        if (g_sifDeliveryCooling && runtime)
        {
            g_sifDeliveryCooling = false;
            ++g_sifDeliveryGeneration;
            // Deliver the next queued packet now, as the IOP DMA would once
            // SIF0 is armed again; waiting a checkpoint added latency to every
            // queued RPC reply.
            if (!g_pendingSifCommands.empty() && !g_drainingSifCommands)
                drainPendingSifCommands(g_nativeRpcTimingGeneration);
        }
        setReturnS32(ctx, 0);
    }

    void sceSifSetDma(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t dmatAddr = getRegU32(ctx, 4);
        const uint32_t count = getRegU32(ctx, 5);

        const uint32_t listAddr = getRegU32(ctx, 4);
        PS2_IF_AGRESSIVE_LOGS({
            std::cerr << "[sceSifSetDma:CALL] pc=0x" << std::hex << ctx->pc
                      << " ra=0x" << getRegU32(ctx, 31)
                      << " list=0x" << listAddr
                      << " count=" << std::dec << count
                      << std::endl;

            for (uint32_t i = 0; i < count; ++i)
            {
                const uint32_t desc = listAddr + i * 16;
                const uint32_t src = READ32(desc + 0);
                const uint32_t dst = READ32(desc + 4);
                const uint32_t size = READ32(desc + 8);
                const uint32_t attr = READ32(desc + 12);

                std::cerr << "[sceSifSetDma:DESC] i=" << i
                          << " src=0x" << std::hex << src
                          << " dst=0x" << dst
                          << " size=0x" << size
                          << " attr=0x" << attr
                          << " pc=0x" << ctx->pc
                          << " ra=0x" << getRegU32(ctx, 31)
                          << std::dec << std::endl;
            }
        });

        if (!dmatAddr || count == 0u || count > 32u)
        {
            setReturnS32(ctx, 0);
            return;
        }

        std::array<Ps2SifDmaTransfer, 32u> pending{};
        uint32_t pendingCount = 0u;
        bool commandReplyDelivered = false;
        bool ok = true;
        for (uint32_t i = 0; i < count; ++i)
        {
            const uint32_t entryAddr = dmatAddr + (i * static_cast<uint32_t>(sizeof(Ps2SifDmaTransfer)));
            const uint8_t *entry = getConstMemPtr(rdram, entryAddr);
            if (!entry)
            {
                ok = false;
                break;
            }

            Ps2SifDmaTransfer xfer{};
            std::memcpy(&xfer, entry, sizeof(xfer));
            if (xfer.size <= 0)
            {
                continue;
            }

            const uint32_t sizeBytes = static_cast<uint32_t>(xfer.size);
            if (sizeBytes > PS2_RAM_SIZE)
            {
                ok = false;
                break;
            }
            if (!runtime || !canAccessEeRange(rdram, xfer.src, sizeBytes) || !runtime->isIopMemoryRange(xfer.dest, sizeBytes))
            {
                ok = false;
                break;
            }

            pending[pendingCount++] = xfer;
        }

        if (ok)
        {
            for (uint32_t i = 0; i < pendingCount; ++i)
            {
                const Ps2SifDmaTransfer &xfer = pending[i];
                if (runtime)
                {
                    PS2IopTransport::notifyTransfer(runtime, rdram, {
                                                                        ps2x::iop::SifTransferKind::SetDma,
                                                                        ps2x::iop::SifTransferPhase::BeforeCopy,
                                                                        xfer.src,
                                                                        xfer.dest,
                                                                        static_cast<uint32_t>(xfer.size),
                                                                    });
                }
                const uint32_t sizeBytes = static_cast<uint32_t>(xfer.size);
                std::vector<uint8_t> payload(sizeBytes);
                if (!readEeRange(rdram, xfer.src, payload.data(), sizeBytes) || !runtime->writeIopMemory(xfer.dest, payload.data(), payload.size()))
                {
                    ok = false;
                    break;
                }
                static uint32_t diagnosticTransfers = 0u;
                if ([] { static const char *const cached = std::getenv("PS2X_CAPTURE_DIR"); return cached; }() && diagnosticTransfers++ < 128u)
                {
                    std::cerr << "[SIF DMA] src=0x" << std::hex << xfer.src
                              << " dst=0x" << xfer.dest << " attr=0x" << xfer.attr;
                    for (size_t word = 0u; word < std::min<size_t>(payload.size() / 4u, 16u); ++word)
                    {
                        uint32_t value = 0u;
                        std::memcpy(&value, payload.data() + word * 4u, 4u);
                        std::cerr << " w" << word << "=0x" << value;
                    }
                    std::cerr << std::dec << " bytes=" << sizeBytes << '\n';
                }
                if ((xfer.attr & 4) != 0 && payload.size() == 64u)
                {
                    uint32_t cmdData = 0u, iopBuffer = 0u;
                    {
                        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
                        cmdData = g_sifRegs[kSifRegMainAddr];
                    }
                    if (cmdData != 0u && canAccessEeCommandRam(rdram, cmdData, 32u) &&
                        readEeRange(rdram, cmdData + 8u, &iopBuffer, 4u) && iopBuffer == xfer.dest)
                        commandReplyDelivered = handleNativeRpcPacket(rdram, ctx, runtime, payload) || commandReplyDelivered;
                }
                if ((xfer.attr & 4) != 0 && payload.size() == 104u)
                    (void)handleIopReset(rdram, runtime, payload);
                // HLE IOP SIFCMD/RPC startup: acknowledge an actual RPC-init
                // command with SET_SREG(0, 1). Never patch the guest's wait loop
                // or mark RPC ready merely because a DMA completed.
                if ((xfer.attr & 4) != 0 && payload.size() == 16u)
                {
                    std::array<uint32_t, 4u> header{};
                    std::memcpy(header.data(), payload.data(), sizeof(header));
                    uint32_t cmdData = 0u;
                    {
                        std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
                        cmdData = g_sifRegs[kSifRegMainAddr];
                    }
                    uint32_t iopBuffer = 0u;
                    if ((header[0] & 0xffu) == payload.size() && (header[0] >> 8u) == 0u &&
                        header[2] == 0x80000002u && header[3] == 1u && cmdData != 0u &&
                        canAccessEeCommandRam(rdram, cmdData, 32u) &&
                        readEeRange(rdram, cmdData + 8u, &iopBuffer, 4u) && iopBuffer == xfer.dest)
                    {
                        const std::array<uint32_t, 6u> reply{24u, 0u, 0x80000001u, 0u, 0u, 1u};
                        const bool delivered = dispatchSifCommand(rdram, runtime, reply[2], reply.data(), sizeof(reply));
                        commandReplyDelivered = commandReplyDelivered || delivered;
                        if ([] { static const char *const cached = std::getenv("PS2X_CAPTURE_DIR"); return cached; }())
                            std::cerr << "[SIF RPC init] reply delivered=" << delivered << '\n';
                    }
                }
                if (runtime)
                {
                    PS2IopTransport::notifyTransfer(runtime, rdram, {
                                                                        ps2x::iop::SifTransferKind::SetDma,
                                                                        ps2x::iop::SifTransferPhase::AfterCopy,
                                                                        xfer.src,
                                                                        xfer.dest,
                                                                        static_cast<uint32_t>(xfer.size),
                                                                    });
                }
            }
        }

        if (!ok)
        {
            static uint32_t warnCount = 0;
            if (warnCount < 32u)
            {
                PS2_IF_AGRESSIVE_LOGS({
                    std::cerr << "sceSifSetDma failed dmat=0x" << std::hex << dmatAddr
                              << " count=0x" << count
                              << std::dec << std::endl;
                });
                ++warnCount;
            }
            setReturnS32(ctx, 0);
            return;
        }

        if (!commandReplyDelivered)
            ps2_syscalls::dispatchDmacHandlersForCause(rdram, runtime, 5u);

        setReturnS32(ctx, static_cast<int32_t>(allocateSifDmaTransferId()));
    }

    void sceSifSetIopAddr(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnU32(ctx, getRegU32(ctx, 5));
    }

    void sceSifSetReg(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t reg = getRegU32(ctx, 4);
        const uint32_t value = getRegU32(ctx, 5);
        uint32_t prev = 0u;
        bool shouldLog = false;
        {
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            auto it = g_sifRegs.find(reg);
            if (it != g_sifRegs.end())
            {
                prev = it->second;
            }
            g_sifRegs[reg] = (reg == kSifRegBootStatus) ? (prev & ~value) : value;
            shouldLog = shouldTraceSifReg(reg) && g_sifSetRegLogCount < 128u;
            if (shouldLog)
            {
                ++g_sifSetRegLogCount;
            }
        }
        if (shouldLog)
        {
            PS2_IF_AGRESSIVE_LOGS({
                auto flags = std::cerr.flags();
                std::cerr << "[sceSifSetReg] reg=0x" << std::hex << reg
                          << " prev=0x" << prev
                          << " value=0x" << value
                          << " pc=0x" << (ctx ? ctx->pc : 0u)
                          << " ra=0x" << (ctx ? getRegU32(ctx, 31) : 0u)
                          << std::dec << std::endl;
                std::cerr.flags(flags);
            });
        }
        setReturnU32(ctx, prev);
    }

    void sceSifSetRpcQueue(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ps2_syscalls::SifSetRpcQueue(rdram, ctx, runtime);
    }

    void sceSifSetSreg(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t reg = getRegU32(ctx, 4);
        const uint32_t value = getRegU32(ctx, 5);
        uint32_t prev = 0u;
        {
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            auto it = g_sifSregs.find(reg);
            if (it != g_sifSregs.end())
            {
                prev = it->second;
            }
            g_sifSregs[reg] = value;
        }
        setReturnU32(ctx, prev);
    }

    void sceSifSetSysCmdBuffer(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t newBuffer = getRegU32(ctx, 4);
        uint32_t prev = 0u;
        {
            std::lock_guard<std::mutex> lock(g_sifCmdStateMutex);
            prev = g_sifSysCmdBuffer;
            g_sifSysCmdBuffer = newBuffer;
        }
        setReturnU32(ctx, prev);
    }

    void sceSifStopDma(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }

    void sceSifSyncIop(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 1);
    }

    void sceSifWriteBackDCache(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        setReturnS32(ctx, 0);
    }
}

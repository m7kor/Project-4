#include "iop_rpc.h"

#include "../core/iop_cpu.h"
#include "../core/iop_kernel.h"
#include "../core/iop_memory.h"
#include "../imports/iop_cdvd.h"
#include "ps2x/iop/iop_host.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <limits>
#include <vector>
#include <iostream>
#include <unordered_map>
#include <set>

namespace ps2x::iop::detail
{
    IopRpcBridge::IopRpcBridge(IopHost &host, IopMemory &memory, IopKernel &kernel, IopCdvd &cdvd) noexcept
        : m_host(host), m_memory(memory), m_kernel(kernel), m_cdvd(cdvd)
    {
    }

    void IopRpcBridge::reset()
    {
        m_servers.clear();
        for (const auto &[token, request] : m_pendingRequests) m_kernel.cancelRpcCall(token);
        m_pendingRequests.clear();
        m_queueThreads.clear();
        m_iopClients.clear();
        m_nextClientRpcId = 1u;
        m_deferredCompletionTrace.fill(0u);
        m_nextDmaId = 1u;
        m_dmaTraceCount = 0u;
        m_rpcCaptureCount = 0u;
        m_sifInitialized = false;
    }

    bool IopRpcBridge::dispatchSifManImport(uint16_t ordinal, IopCpuState &cpu)
    {
        const auto setV0 = [&](uint32_t value)
        {
            cpu.gpr[2] = value;
        };
        switch (ordinal)
        {
        case 4: // sceSifDma2Init
        case 5: // sceSifInit
            m_sifInitialized = true;
            setV0(0u);
            return true;
        case 7: // sceSifSetDma
        {
            constexpr uint32_t kDescriptorSize = 16u;
            constexpr uint32_t kMaxDescriptors = 32u;
            const uint32_t descriptorAddress = cpu.gpr[4];
            const uint32_t descriptorCount = cpu.gpr[5];
            if (descriptorAddress == 0u || descriptorCount == 0u || descriptorCount > kMaxDescriptors)
            {
                setV0(0u);
                return true;
            }

            struct PendingTransfer
            {
                uint32_t source = 0u;
                uint32_t destination = 0u;
                uint32_t size = 0u;
            };

            std::array<uint32_t, kMaxDescriptors * 4u> descriptorWords{};
            const size_t descriptorBytes = static_cast<size_t>(descriptorCount) * kDescriptorSize;
            if (!m_memory.readRam(descriptorAddress, descriptorWords.data(), descriptorBytes))
            {
                setV0(0u);
                return true;
            }

            std::array<PendingTransfer, kMaxDescriptors> pending{};
            uint32_t pendingCount = 0u;
            uint32_t largestTransfer = 0u;
            for (uint32_t i = 0u; i < descriptorCount; ++i)
            {
                const uint32_t source = descriptorWords[i * 4u + 0u];
                const uint32_t destination = descriptorWords[i * 4u + 1u];
                const int32_t signedSize = static_cast<int32_t>(descriptorWords[i * 4u + 2u]);
                if (signedSize <= 0)
                    continue;

                const uint32_t size = static_cast<uint32_t>(signedSize);
                if (!m_memory.ownsRamRange(source, size))
                {
                    setV0(0u);
                    return true;
                }
                pending[pendingCount++] = {source, destination, size};
                largestTransfer = std::max(largestTransfer, size);
            }

            // IOP-side sceSifSetDma sends IOP RAM to the EE. Validate all EE
            // destinations before committing any write so a bad chain cannot
            // partially update guest memory, but maybe we could skip this check if we trust the EE-side SIF driver to validate the chain ?!
            // TODO check later
            std::vector<uint8_t> scratch(largestTransfer);
            for (uint32_t i = 0u; i < pendingCount; ++i)
            {
                const PendingTransfer &transfer = pending[i];
                if (!m_host.readGuest(transfer.destination, scratch.data(), transfer.size))
                {
                    setV0(0u);
                    return true;
                }
            }

            for (uint32_t i = 0u; i < pendingCount; ++i)
            {
                const PendingTransfer &transfer = pending[i];
                static const bool traceSif = std::getenv("PS2X_TRACE_SIF") != nullptr;
                if (traceSif)
                {
                    std::cerr << "[SIF IOP>EE] src=0x" << std::hex << transfer.source << " dst=0x"
                              << transfer.destination << " size=0x" << transfer.size << " w0=0x"
                              << m_memory.read32(transfer.source)
                              << " pc=0x" << cpu.pc << " ra=0x" << cpu.gpr[31];
                    if (transfer.size == 0x80u || transfer.size == 0x880u)
                    {
                        std::cerr << " words=";
                        for (uint32_t w = 0; w < 0x80u; w += 4u)
                            std::cerr << m_memory.read32(transfer.source + w) << ',';
                    }
                    else if (transfer.size <= 0x1000u)
                    {
                        // The 16 bytes before the source too: shows how an
                        // unaligned source relates to the data it carries.
                        std::cerr << " around=";
                        for (uint32_t w = 0; w < 0x30u; w += 4u)
                            std::cerr << m_memory.read32(transfer.source - 0x10u + w) << (w == 0xCu ? '|' : ',');
                    }
                    std::cerr << std::dec << std::endl;
                }
                if ([] { static const char *const cached = std::getenv("PS2X_CAPTURE_DIR"); return cached; }() && m_dmaTraceCount++ < 48u)
                {
                    std::ostringstream out;
                    out << "[IOP DMA to EE] src=0x" << std::hex << transfer.source
                        << " dst=0x" << transfer.destination << " size=0x" << transfer.size
                        << " word0=0x" << m_memory.read32(transfer.source);
                    m_host.log(LogLevel::Info, out.str());
                }
                if (!m_memory.readRam(transfer.source, scratch.data(), transfer.size) || !m_host.writeGuest(transfer.destination, scratch.data(), transfer.size))
                {
                    setV0(0u);
                    return true;
                }
            }

            const uint32_t dmaId = m_nextDmaId++;
            if (m_nextDmaId == 0u || m_nextDmaId > static_cast<uint32_t>(std::numeric_limits<int32_t>::max()))
            {
                m_nextDmaId = 1u;
            }
            setV0(dmaId);
            return true;
        }
        case 8: // sceSifDmaStat
            setV0(0xFFFFFFFFu);
            return true;
        case 29: // sceSifCheckInit
            setV0(m_sifInitialized ? 1u : 0u);
            return true;
        default:
            setV0(0u);
            return true;
        }
    }

    bool IopRpcBridge::dispatchSifCmdImport(uint16_t ordinal, IopCpuState &cpu)
    {
        const auto setV0 = [&](uint32_t value)
        {
            cpu.gpr[2] = value;
        };
        switch (ordinal)
        {
        case 4: // InitCmd
        case 5:
        case 6:
        case 7:
        case 8:
        case 9:
        case 10:
        case 11:
        case 14: // InitRpc
            setV0(0);
            return true;
        case 15: // sceSifBindRpc(client, sid, mode)
        {
            static const bool clientsEnabled = [] {
                const char *v = std::getenv("PS2X_IOP_RPC_CLIENT");
                return !(v && *v == '0');
            }();
            if (!clientsEnabled)
            {
                setV0(0);
                return true;
            }
            // Packet layout follows SifRpcBindPkt_t; the EE server replies with
            // RPC_END (0x80000008) carrying the server and its buffers.
            const uint32_t client = cpu.gpr[4];
            const uint32_t sid = cpu.gpr[5];
            const uint32_t mode = cpu.gpr[6];
            if (client == 0u || !m_memory.ownsRamRange(client, 0x28u))
            {
                setV0(static_cast<uint32_t>(-1));
                return true;
            }
            for (uint32_t offset = 0u; offset < 0x28u; offset += 4u)
                m_memory.write32(client + offset, 0u);
            const uint32_t rpcId = m_nextClientRpcId++;
            m_memory.write32(client + 0x04u, rpcId);
            m_memory.write32(client + 0x10u, 0x80000009u);
            std::array<uint32_t, 16> words{};
            words[5] = client;
            words[6] = rpcId;
            words[7] = client;
            words[8] = sid;
            auto &bindState = m_iopClients[client];
            bindState.bindSid = sid;
            bindState.callPending = false;
            if (!sendRpcPacket(0x80000009u, words, 0u, 0u, 0u))
            {
                setV0(static_cast<uint32_t>(-1));
                return true;
            }
            setV0(0u);
            if ((mode & 1u) == 0u)
                waitClient(cpu, client);
            return true;
        }
        case 16: // sceSifCallRpc(client, fno, mode, send, ssize, receive, rsize, end, param)
        {
            const uint32_t client = cpu.gpr[4];
            const uint32_t function = cpu.gpr[5];
            const uint32_t mode = cpu.gpr[6];
            const uint32_t send = cpu.gpr[7];
            const uint32_t sp = cpu.gpr[29];
            const uint32_t sendSize = m_memory.read32(sp + 0x10u);
            const uint32_t receive = m_memory.read32(sp + 0x14u);
            const uint32_t receiveSize = m_memory.read32(sp + 0x18u);
            const uint32_t endFunction = m_memory.read32(sp + 0x1Cu);
            const uint32_t endParameter = m_memory.read32(sp + 0x20u);
            if (client == 0u || !m_memory.ownsRamRange(client, 0x28u) || m_iopClients.find(client) == m_iopClients.end())
            {
                setV0(static_cast<uint32_t>(-0xE)); // not bound
                return true;
            }
            const uint32_t server = m_memory.read32(client + 0x24u);
            const uint32_t serverBuffer = m_memory.read32(client + 0x14u);
            const uint32_t rpcId = m_nextClientRpcId++;
            m_memory.write32(client + 0x04u, rpcId);
            m_memory.write32(client + 0x10u, 0x8000000Au);
            m_memory.write32(client + 0x1Cu, endFunction);
            m_memory.write32(client + 0x20u, endParameter);
            auto &state = m_iopClients[client];
            state.endFunction = endFunction;
            state.endParameter = endParameter;
            if (endFunction != 0u)
                std::cerr << "[ps2xIOP:warning] sceSifCallRpc end function 0x" << std::hex << endFunction << std::dec
                          << " is not run" << std::endl;
            std::array<uint32_t, 16> words{};
            words[5] = client;
            words[6] = rpcId;
            words[7] = client;
            words[8] = function;
            words[9] = sendSize;
            words[10] = receive;
            words[11] = receiveSize;
            words[12] = receive != 0u ? 1u : 0u;
            words[13] = server;
            if (server == 0u)
            {
                // The bind ran before the EE registered its server (its thread
                // had not started yet). Bind again and send this call once
                // the EE answers with the server.
                state.callPending = true;
                state.pendingCall = words;
                state.pendingSend = send;
                state.pendingSendSize = sendSize;
                std::array<uint32_t, 16> bind{};
                bind[5] = client;
                bind[6] = rpcId;
                bind[7] = client;
                bind[8] = state.bindSid;
                m_memory.write32(client + 0x10u, 0x80000009u);
                (void)sendRpcPacket(0x80000009u, bind, 0u, 0u, 0u);
                setV0(0u);
                if ((mode & 1u) == 0u)
                    waitClient(cpu, client);
                return true;
            }
            if (!sendRpcPacket(0x8000000Au, words, send, serverBuffer, sendSize))
            {
                setV0(static_cast<uint32_t>(-1));
                return true;
            }
            setV0(0u);
            if ((mode & 1u) == 0u)
                waitClient(cpu, client);
            return true;
        }
        case 12: // sceSifSendCmd
        case 13: // isceSifSendCmd
        {
            constexpr uint32_t kHeaderSize = 16u;
            constexpr uint32_t kMaxPacketSize = 112u;
            const uint32_t commandId = cpu.gpr[4];
            const uint32_t packetAddress = cpu.gpr[5];
            const uint32_t packetSize = cpu.gpr[6];
            const uint32_t extraSource = cpu.gpr[7];
            const uint32_t stackPointer = cpu.gpr[29];
            const uint32_t extraDestination = m_memory.read32(stackPointer + 16u);
            const int32_t signedExtraSize = static_cast<int32_t>(m_memory.read32(stackPointer + 20u));

            if (packetAddress == 0u || packetSize < kHeaderSize || packetSize > kMaxPacketSize ||
                !m_memory.ownsRamRange(packetAddress, packetSize))
            {
                setV0(0u);
                return true;
            }

            std::array<uint8_t, kMaxPacketSize> packet{};
            if (!m_memory.readRam(packetAddress, packet.data(), packetSize))
            {
                setV0(0u);
                return true;
            }

            uint32_t extraSize = 0u;
            if (signedExtraSize > 0)
            {
                extraSize = static_cast<uint32_t>(signedExtraSize);
                if (extraSource == 0u || extraDestination == 0u ||
                    !m_memory.ownsRamRange(extraSource, extraSize) ||
                    !m_host.writeGuest(extraDestination, m_memory.ram().data() + IopMemory::physicalAddress(extraSource), extraSize))
                {
                    setV0(0u);
                    return true;
                }
            }

            const uint32_t sizeWord = packetSize | (extraSize << 8u);
            std::memcpy(packet.data() + 0u, &sizeWord, sizeof(sizeWord));
            std::memcpy(packet.data() + 4u, &extraDestination, sizeof(extraDestination));
            std::memcpy(packet.data() + 8u, &commandId, sizeof(commandId));

            const bool delivered = m_host.sendSifCommand(commandId, packet.data(), packetSize);
            static const bool traceSif = std::getenv("PS2X_TRACE_SIF") != nullptr;
            if (traceSif)
            {
                uint32_t words[4] = {};
                std::memcpy(words, packet.data() + 16u, std::min<uint32_t>(packetSize - 16u, 16u));
                std::cerr << "[SIF IOP cmd] id=0x" << std::hex << commandId << " size=0x" << packetSize
                          << " extra=0x" << extraSize << " ra=0x" << cpu.gpr[31] << " body=" << words[0] << ','
                          << words[1] << ',' << words[2] << ',' << words[3] << " delivered=" << delivered << std::dec
                          << std::endl;
            }
            if (!delivered)
            {
                // A command without an EE handler is still a completed DMA on  real hardware. Only malformed packets fail above.
            }

            const uint32_t dmaId = m_nextDmaId++;
            if (m_nextDmaId == 0u || m_nextDmaId > static_cast<uint32_t>(std::numeric_limits<int32_t>::max()))
                m_nextDmaId = 1u;
            setV0(dmaId);
            return true;
        }
        case 17: // sceSifRegisterRpc
        {
            RpcServer server;
            server.serverData = cpu.gpr[4];
            server.sid = cpu.gpr[5];
            server.function = cpu.gpr[6];
            server.gp = cpu.gpr[28];
            server.buffer = cpu.gpr[7];
            const uint32_t stackPointer = cpu.gpr[29];
            server.callback = m_memory.read32(stackPointer + 16u);
            server.callbackBuffer = m_memory.read32(stackPointer + 20u);
            server.queue = m_memory.read32(stackPointer + 24u);
            m_servers[server.sid] = server;
            if (server.serverData != 0u)
            {
                m_memory.write32(server.serverData + 0x20u, server.sid);
                m_memory.write32(server.serverData + 0x28u, server.function);
                m_memory.write32(server.serverData + 0x2Cu, server.buffer);
            }
            setV0(server.serverData);
            return true;
        }
        case 18:
            setV0(0);
            return true;
        case 19: // SetRpcQueue
            if (cpu.gpr[4] && m_memory.ownsRamRange(cpu.gpr[4], 24u))
            {
                m_queueThreads[cpu.gpr[4]] = static_cast<int>(cpu.gpr[5]);
                m_memory.write32(cpu.gpr[4], cpu.gpr[5]);
                for (uint32_t offset = 4u; offset < 24u; offset += 4u)
                    m_memory.write32(cpu.gpr[4] + offset, 0u);
            }
            setV0(cpu.gpr[4]);
            return true;
        case 20:
        case 21:
            setV0(0);
            return true;
        case 22: // RpcLoop
            m_kernel.parkRpcCurrent(cpu);
            setV0(0);
            return true;
        case 23: // sceSifGetOtherData(rd, eeSrc, iopDest, size, mode)
        {
            // PS2SDK SifRpcReceiveData_t has a 16-byte header followed by src/dest/size.
            // This bridge completes transfers synchronously, including NOWAIT requests.
            const uint32_t receiveData = cpu.gpr[4];
            const uint32_t source = cpu.gpr[5];
            const uint32_t destination = cpu.gpr[6];
            const uint32_t size = cpu.gpr[7];
            const uint32_t descriptorPhysical = IopMemory::physicalAddress(receiveData);
            const uint32_t destinationPhysical = IopMemory::physicalAddress(destination);
            // Validate all IOP ranges before allocating, reading EE RAM, or writing anything.
            if (receiveData == 0u || descriptorPhysical > IopMemory::RamSize - 28u ||
                size > IopMemory::RamSize || destinationPhysical > IopMemory::RamSize ||
                size > IopMemory::RamSize - destinationPhysical)
            {
                setV0(static_cast<uint32_t>(-1));
                return true;
            }
            std::vector<uint8_t> buffer(size);
            if (size != 0u && !m_host.readGuest(source, buffer.data(), size))
            {
                setV0(static_cast<uint32_t>(-1));
                return true;
            }
            if (size != 0u) (void)m_memory.writeRam(destination, buffer.data(), size);
            // pkt_addr == NULL marks a completed request; no outstanding packet is allocated.
            m_memory.write32(receiveData, 0u);
            m_memory.write32(receiveData + 16u, source);
            m_memory.write32(receiveData + 20u, destination);
            m_memory.write32(receiveData + 24u, size);
            setV0(0u);
            return true;
        }
        case 24: // RemoveRpc
        {
            const uint32_t serverData = cpu.gpr[4];
            for (auto server = m_servers.begin(); server != m_servers.end(); ++server)
            {
                if (server->second.serverData == serverData)
                {
                    m_servers.erase(server);
                    break;
                }
            }
            setV0(0);
            return true;
        }
        case 25:
        case 26:
        case 27:
        case 28:
        case 29:
            setV0(0);
            return true;
        default:
            return false;
        }
    }

    RpcResult IopRpcBridge::handleRpc(const RpcRequest &request, IopGuestExecutor &executor)
    {
        RpcResult result{};
        // PS2X_TRACE_RPC_CENSUS: one line per EE->IOP call (RE4 makes only a
        // few hundred per minute), to compare which requests a stalled run
        // stops sending.
        static const bool rpcCensus = std::getenv("PS2X_TRACE_RPC_CENSUS") != nullptr;
        if (rpcCensus)
        {
            static uint64_t total = 0;
            std::cerr << "[IOP RPC] n=" << ++total << std::hex << " sid=0x" << request.sid << " fn=0x"
                      << request.function << " mode=0x" << request.mode << " send=0x" << request.send.size
                      << " recv=0x" << request.receive.size << std::dec << std::endl;
        }
        const auto serverIt = m_servers.find(request.sid);
        if (serverIt == m_servers.end() || serverIt->second.function == 0u)
            return m_cdvd.handleRpc(request);

        RpcServer &server = serverIt->second;
        if (request.deferredNative)
        {
            if (!m_queueThreads.contains(server.queue) ||
                !m_kernel.hasThread(m_queueThreads.at(server.queue)) || m_pendingRequests.size() >= 1024u ||
                m_nextRequestToken == UINT64_MAX ||
                (request.send.size && (!server.buffer || !m_memory.ownsRamRange(server.buffer, request.send.size))) ||
                request.send.size > 16384u || request.receive.size > 16384u ||
                request.nativeEndPacket[0] != 64u || request.nativeEndPacket[2] != 0x80000008u)
                return result;
            PendingRequest pending{request, server, std::vector<uint8_t>(request.send.size), false};
            if (request.send.size && !m_host.readGuest(request.send.address, pending.send.data(), pending.send.size()))
                return result;
            m_pendingRequests.emplace(++m_nextRequestToken, std::move(pending));
            result.handled = true;
            result.deferredNative = true;
            result.serverDispatchPolicy = ServerDispatchPolicy::Suppress;
            result.callbackPolicy = CallbackPolicy::Suppress;
            return result;
        }
        // Opt-in, bounded snapshots of actual IOP RAM around a selected original RPC.
        // SID and function must both match; no guest memory or scheduling is changed.
        const char *captureDirectory = [] { static const char *const cached = std::getenv("PS2X_CAPTURE_DIR"); return cached; }();
        const char *captureSelection = [] { static const char *const cached = std::getenv("PS2X_IOP_RPC_CAPTURE"); return cached; }();
        bool capture = false;
        if (captureDirectory && *captureDirectory && captureSelection && m_rpcCaptureCount < 4u)
        {
            char *sidEnd = nullptr;
            const unsigned long long sid = std::strtoull(captureSelection, &sidEnd, 0);
            if (sidEnd != captureSelection && *sidEnd == ':')
            {
                char *functionEnd = nullptr;
                const unsigned long long function = std::strtoull(sidEnd + 1, &functionEnd, 0);
                capture = functionEnd != sidEnd + 1 && *functionEnd == '\0' &&
                          sid == request.sid && function == request.function;
            }
        }
        const uint32_t captureIndex = capture ? ++m_rpcCaptureCount : 0u;
        auto snapshot = [&](const char *phase, uint32_t reply, bool completed)
        {
            if (!capture) return;
            try
            {
                std::ostringstream stem;
                stem << "iop-rpc-" << std::hex << request.sid << '-' << request.function
                     << '-' << std::dec << captureIndex << '-' << phase;
                const auto file = std::filesystem::path(captureDirectory) / (stem.str() + ".bin");
                std::ofstream dump(file, std::ios::binary);
                dump.write(reinterpret_cast<const char *>(m_memory.ram().data()), IopMemory::RamSize);
                std::ostringstream message;
                message << "[IOP RPC snapshot] file=" << file.filename().string()
                        << " sid=0x" << std::hex << request.sid << " rpc=0x" << request.function
                        << " entry=0x" << server.function << " gp=0x" << server.gp
                        << " buffer=0x" << server.buffer << " server=0x" << server.serverData
                        << " reply=0x" << reply << " completed=" << completed
                        << " bytes=" << std::dec << (dump.good() ? IopMemory::RamSize : 0u);
                m_host.log(dump.good() ? LogLevel::Info : LogLevel::Warning, message.str());
            }
            catch (const std::exception &)
            {
                m_host.log(LogLevel::Warning, "[IOP RPC snapshot] unable to write diagnostic snapshot");
            }
        };
        if (request.send.size != 0u && server.buffer != 0u)
        {
            const uint32_t copySize = std::min<uint32_t>(request.send.size, IopMemory::RamSize - std::min(server.buffer, IopMemory::RamSize));
            if (copySize != 0u)
            {
                std::vector<uint8_t> payload(copySize);
                if (m_host.readGuest(request.send.address, payload.data(), payload.size()))
                    (void)m_memory.writeRam(server.buffer, payload.data(), payload.size());
            }
        }

        snapshot("before", 0u, false);
        uint32_t returnPointer = executor.executeGuestFunction(server.function,
                                                               request.function,
                                                               server.buffer,
                                                               request.send.size,
                                                               0u,
                                                               server.gp);
        snapshot("after", returnPointer, executor.lastGuestCallCompleted());
        if (!executor.lastGuestCallCompleted())
            return result;
        if (returnPointer == 0u)
            returnPointer = server.buffer;
        if (rpcCensus)
        {
            // Request words (as the server saw them) and the reply words.
            std::cerr << "[IOP RPC data] sid=0x" << std::hex << request.sid << " fn=0x" << request.function
                      << " send=";
            for (uint32_t i = 0; i < std::min<uint32_t>(request.send.size, 24u); i += 4u)
                std::cerr << m_memory.read32(server.buffer + i) << ',';
            std::cerr << " reply=";
            for (uint32_t i = 0; i < std::min<uint32_t>(request.receive.size, 16u); i += 4u)
                std::cerr << m_memory.read32(returnPointer + i) << ',';
            std::cerr << std::dec << std::endl;
        }
        if (request.receive.address != 0u && request.receive.size != 0u && returnPointer != 0u)
        {
            const uint32_t physical = IopMemory::physicalAddress(returnPointer);
            if (physical < IopMemory::RamSize)
            {
                const uint32_t copySize = std::min<uint32_t>(request.receive.size, IopMemory::RamSize - physical);
                (void)m_host.writeGuest(request.receive.address, m_memory.ram().data() + physical, copySize);
                if (copySize < request.receive.size)
                    (void)m_host.zeroGuest(request.receive.address + copySize, request.receive.size - copySize);
            }
        }

        result.handled = true;
        result.resultAddress = request.receive.address;
        result.serverDispatchPolicy = ServerDispatchPolicy::Suppress;
        result.signalNowaitCompletion = true;
        result.signalCompletion = true;
        return result;
    }

    void IopRpcBridge::dispatchPendingRequests(uint32_t returnSentinel)
    {
        if (m_pendingRequests.empty()) return;
        std::vector<uint64_t> cancelled;
        for (const auto &[token, pending] : m_pendingRequests)
            if (pending.active && !m_kernel.hasRpcCall(token)) cancelled.push_back(token);
        for (const auto token : cancelled) finishPendingRequest(token, 0u, true);
        // Ordered tokens preserve FIFO even when several services share a queue.
        std::set<uint32_t> queues;
        for (auto &[token, pending] : m_pendingRequests)
        {
            if (!queues.insert(pending.server.queue).second) continue;
            if (pending.active) continue;
            const auto queue = m_queueThreads.find(pending.server.queue);
            if (queue == m_queueThreads.end() || !m_kernel.canStartRpcCall(queue->second)) continue;
            if (!pending.send.empty())
                (void)m_memory.writeRam(pending.server.buffer, pending.send.data(), pending.send.size());
            pending.active = m_kernel.startRpcCall(queue->second, token, pending.server.function,
                pending.request.function, pending.server.buffer, pending.request.send.size,
                pending.server.gp, returnSentinel);
        }
    }

    void IopRpcBridge::finishPendingRequest(uint64_t token, uint32_t pointer, bool faulted)
    {
        const auto it = m_pendingRequests.find(token);
        if (it == m_pendingRequests.end()) return;
        auto pending = std::move(it->second);
        m_pendingRequests.erase(it);
        if (!pending.active || faulted)
        {
            m_host.log(LogLevel::Error, "[IOP call incomplete] deferred RPC faulted before return");
            return;
        }
        if (pointer == 0u) pointer = pending.server.buffer;
        const auto &request = pending.request;
        if (request.receive.size &&
            (!m_memory.ownsRamRange(pointer, request.receive.size) ||
             !m_host.writeGuest(request.receive.address,
                m_memory.ram().data() + IopMemory::physicalAddress(pointer), request.receive.size)))
        {
            m_host.log(LogLevel::Error, "[SIF RPC timing delivery failed] deferred output range unavailable");
            return;
        }
        if (!m_host.sendSifCommand(request.nativeEndPacket[2], request.nativeEndPacket.data(),
                                  sizeof(request.nativeEndPacket)))
        {
            m_host.log(LogLevel::Error, "[SIF RPC timing delivery failed] deferred completion unavailable");
            return;
        }
        if (const char *selection = [] { static const char *const cached = std::getenv("PS2X_TRACE_NATIVE_RPC_SID"); return cached; }())
        {
            char *end = nullptr;
            const auto sid = std::strtoull(selection, &end, 0);
            const auto index = std::min<uint32_t>(request.function, 256u);
            if (end != selection && *end == '\0' && sid == request.sid &&
                m_deferredCompletionTrace[index]++ < 8u)
            {
                std::ostringstream out;
                out << "[IOP deferred RPC complete] sid=0x" << std::hex << request.sid
                    << " function=0x" << request.function;
                if (request.receive.size >= 4u) out << " word0=0x" << m_memory.read32(pointer);
                m_host.log(LogLevel::Info, out.str());
            }
        }
    }

    void IopRpcBridge::onSifTransfer(const SifTransfer &transfer)
    {
        // The EE SIF transport owns the actual directional memory movement.
        // Services still receive both phases through IopSubsystem, but mirroring
        // IOP bytes through an equal-numbered EE address would alias two distinct
        // PS2 address spaces and can overwrite live game data.
        // PS2X_TRACE_SIF: one compact line per EE->IOP SIF transfer.
        // An EE server's RPC_END for one of our IOP clients lands in the IOP
        // command buffer like any other SIF command packet.
        if (transfer.phase == SifTransferPhase::AfterCopy && !m_iopClients.empty() && transfer.size >= 0x30u &&
            transfer.size <= 0x70u && m_memory.ownsRamRange(transfer.destinationAddress, 0x30u))
        {
            const uint32_t cid = m_memory.read32(transfer.destinationAddress + 8u);
            if (cid == 0x80000008u)
                completeClientRpc(transfer.destinationAddress);
            else if (cid == 0x8000000Au)
            {
                // An unbound client (its first bind ran before the EE server
                // existed) asks again on the next EE call: spaced like real
                // traffic, so the EE threads keep running in between.
                for (auto &[client, state] : m_iopClients)
                {
                    if (state.bindSid == 0u || m_memory.read32(client + 0x24u) != 0u ||
                        m_memory.read32(client + 0x10u) == 0x80000009u)
                        continue;
                    std::array<uint32_t, 16> bind{};
                    bind[5] = client;
                    bind[6] = m_memory.read32(client + 0x04u);
                    bind[7] = client;
                    bind[8] = state.bindSid;
                    m_memory.write32(client + 0x10u, 0x80000009u);
                    (void)sendRpcPacket(0x80000009u, bind, 0u, 0u, 0u);
                }
            }
        }
        static const bool trace = std::getenv("PS2X_TRACE_SIF") != nullptr;
        // Observe delivered PCM and SJ descriptors without changing transport.
        // Explicit destination range comes from the active RNA/SJRMT handles.
        if (transfer.phase == SifTransferPhase::AfterCopy || transfer.phase == SifTransferPhase::BeforeCopy)
        {
            struct PayloadTrace
            {
                std::FILE *file = nullptr;
                uint32_t start = 0, length = 0, sequence = 0;
                uint64_t bytes = 0;
                std::vector<uint8_t> source;
                PayloadTrace()
                {
                    const char *path = std::getenv("PS2X_SIF_PAYLOAD_RAW");
                    const char *range = std::getenv("PS2X_SIF_PAYLOAD_RANGE");
                    if (!path || !*path || !range) return;
                    char *end = nullptr;
                    const auto begin = std::strtoul(range, &end, 0);
                    if (end == range || *end != ':') return;
                    const char *count = end + 1;
                    const auto size = std::strtoul(count, &end, 0);
                    if (end == count || *end || !size || begin >= IopMemory::RamSize || size > IopMemory::RamSize - begin) return;
                    start = static_cast<uint32_t>(begin); length = static_cast<uint32_t>(size);
                    file = std::fopen(path, "wb");
                }
                ~PayloadTrace() { if (file) std::fclose(file); }
            };
            static PayloadTrace payload;
            const uint32_t dest = IopMemory::physicalAddress(transfer.destinationAddress);
            const bool descriptor = transfer.sourceAddress == 0x30EE00u && transfer.size == 0x880u;
            const bool overlaps = dest < uint64_t(payload.start) + payload.length &&
                uint64_t(dest) + transfer.size > payload.start;
            if (payload.file && payload.bytes < 128u * 1024u * 1024u && (descriptor || overlaps) &&
                transfer.size && dest < IopMemory::RamSize && transfer.size <= IopMemory::RamSize - dest)
            {
                const bool before = transfer.phase == SifTransferPhase::BeforeCopy;
                const uint8_t *data = m_memory.ram().data() + dest;
                if (before)
                {
                    payload.source.resize(transfer.size);
                    if (!m_host.readGuest(transfer.sourceAddress, payload.source.data(), transfer.size)) return;
                    data = payload.source.data();
                }
                const uint32_t header[] = {0x50464953u, 1u, ++payload.sequence, transfer.sourceAddress,
                                          dest, transfer.size, (descriptor ? 1u : 0u) | (before ? 2u : 0u), 0u}; // SIFP v1
                std::fwrite(header, sizeof(header), 1, payload.file);
                std::fwrite(data, 1, transfer.size, payload.file);
                std::fflush(payload.file);
                payload.bytes += sizeof(header) + transfer.size;
            }
        }
        if (trace && transfer.phase == SifTransferPhase::AfterCopy)
        {
            std::cerr << "[SIF EE>IOP] src=0x" << std::hex << transfer.sourceAddress << " dst=0x"
                      << transfer.destinationAddress << " size=0x" << transfer.size << " w0=0x"
                      << m_memory.read32(transfer.destinationAddress);
            if (transfer.size <= 0x40u || transfer.size == 0x880u)
            {
                std::cerr << " words=";
                for (uint32_t w = 0; w < std::min<uint32_t>(transfer.size, 0x80u); w += 4u)
                    std::cerr << m_memory.read32(transfer.destinationAddress + w) << ',';
            }
            std::cerr << std::dec << std::endl;
        }
    }

    bool IopRpcBridge::sendRpcPacket(uint32_t commandId, std::array<uint32_t, 16> &words,
                                     uint32_t extraSource, uint32_t extraDestination, uint32_t extraSize)
    {
        if (extraSize != 0u)
        {
            if (extraSource == 0u || extraDestination == 0u || !m_memory.ownsRamRange(extraSource, extraSize) ||
                !m_host.writeGuest(extraDestination,
                                   m_memory.ram().data() + IopMemory::physicalAddress(extraSource), extraSize))
                return false;
        }
        constexpr uint32_t kPacketSize = 64u;
        words[0] = kPacketSize | (extraSize << 8u);
        words[1] = extraDestination;
        words[2] = commandId;
        words[3] = 0u;
        const bool delivered = m_host.sendSifCommand(commandId, words.data(), kPacketSize);
        static const bool traceSif = std::getenv("PS2X_TRACE_SIF") != nullptr;
        if (traceSif)
            std::cerr << "[SIF IOP rpc] cid=0x" << std::hex << commandId << " client=0x" << words[7] << " arg=0x"
                      << words[8] << " server=0x" << words[13] << " extra=0x" << extraSize << " delivered=" << delivered
                      << std::dec << std::endl;
        return delivered;
    }

    void IopRpcBridge::waitClient(IopCpuState &cpu, uint32_t client)
    {
        auto &state = m_iopClients[client];
        if (state.eventFlag == 0)
            state.eventFlag = m_kernel.createInternalEventFlag(0u, 0u, 0u);
        // WaitEventFlag(flag, 1, WEF_OR | WEF_CLEAR, NULL): returns KE_OK (0),
        // which is also sceSifBindRpc/sceSifCallRpc's success value.
        cpu.gpr[4] = static_cast<uint32_t>(state.eventFlag);
        cpu.gpr[5] = 1u;
        cpu.gpr[6] = 0x11u;
        cpu.gpr[7] = 0u;
        // Without a current thread (module start, interrupt-like contexts)
        // the wait cannot block (KE_CAN_NOT_WAIT): complete asynchronously,
        // the reply still updates the client when it arrives.
        if (!m_kernel.dispatchEventImport(10, cpu) || cpu.gpr[2] == static_cast<uint32_t>(-418))
            cpu.gpr[2] = 0u;
    }

    void IopRpcBridge::completeClientRpc(uint32_t packetAddress)
    {
        // SifRpcRendPkt_t: client at +0x1C, cid at +0x20, server/buff/cbuff after.
        const uint32_t client = m_memory.read32(packetAddress + 0x1Cu);
        const auto found = m_iopClients.find(client);
        if (found == m_iopClients.end())
            return;
        const uint32_t cid = m_memory.read32(packetAddress + 0x20u);
        if (cid == 0x80000009u)
        {
            m_memory.write32(client + 0x24u, m_memory.read32(packetAddress + 0x24u));
            m_memory.write32(client + 0x14u, m_memory.read32(packetAddress + 0x28u));
            m_memory.write32(client + 0x18u, m_memory.read32(packetAddress + 0x2Cu));
            auto &state = found->second;
            if (state.callPending && m_memory.read32(client + 0x24u) != 0u)
            {
                // Deferred call: now that the server is known, send it; the
                // waiter is woken by that call's RPC_END instead.
                state.callPending = false;
                state.pendingCall[13] = m_memory.read32(client + 0x24u);
                m_memory.write32(client + 0x10u, 0x8000000Au);
                (void)sendRpcPacket(0x8000000Au, state.pendingCall, state.pendingSend,
                                    m_memory.read32(client + 0x14u), state.pendingSendSize);
                return;
            }
        }
        m_memory.write32(client + 0x10u, 0u);
        m_memory.write32(client + 0x00u, 0u);
        static const bool traceSif = std::getenv("PS2X_TRACE_SIF") != nullptr;
        if (traceSif)
            std::cerr << "[SIF IOP rpc end] client=0x" << std::hex << client << " cid=0x" << cid << " server=0x"
                      << m_memory.read32(client + 0x24u) << std::dec << std::endl;
        if (found->second.eventFlag == 0)
            found->second.eventFlag = m_kernel.createInternalEventFlag(0u, 0u, 0u);
        (void)m_kernel.setInternalEventFlag(found->second.eventFlag, 1u);
    }

    void IopRpcBridge::removeServersInRange(uint32_t base, uint32_t size)
    {
        for (auto server = m_servers.begin(); server != m_servers.end();)
        {
            const uint32_t function = IopMemory::physicalAddress(server->second.function);
            if (function >= base && function < base + size)
            {
                for (auto pending = m_pendingRequests.begin(); pending != m_pendingRequests.end();)
                {
                    if (pending->second.server.sid != server->first) { ++pending; continue; }
                    m_kernel.cancelRpcCall(pending->first);
                    pending = m_pendingRequests.erase(pending);
                }
                server = m_servers.erase(server);
            }
            else
                ++server;
        }
    }

    bool IopRpcBridge::hasServer(uint32_t sid) const noexcept
    {
        const auto server = m_servers.find(sid);
        return (server != m_servers.end() && server->second.function != 0u) || IopCdvd::hasBuiltinRpc(sid);
    }
}

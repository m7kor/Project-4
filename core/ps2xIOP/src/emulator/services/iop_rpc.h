#pragma once

#include "ps2x/iop/iop_types.h"

#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <map>
#include <vector>

namespace ps2x::iop
{
    class IopHost;
}

namespace ps2x::iop::detail
{
    struct IopCpuState;
    class IopKernel;
    class IopMemory;
    class IopCdvd;

    class IopGuestExecutor
    {
    public:
        virtual ~IopGuestExecutor() = default;
        [[nodiscard]] virtual bool lastGuestCallCompleted() const noexcept { return true; }

        [[nodiscard]] virtual uint32_t executeGuestFunction(uint32_t address,
                                                            uint32_t a0,
                                                            uint32_t a1,
                                                            uint32_t a2,
                                                            uint32_t a3,
                                                            uint32_t gp) = 0;
        [[nodiscard]] virtual uint32_t executeGuestFunctionWithBudget(uint32_t address,
                                                                      uint32_t a0,
                                                                      uint32_t a1,
                                                                      uint32_t a2,
                                                                      uint32_t a3,
                                                                      uint32_t gp,
                                                                      uint32_t instructionBudget)
        {
            return executeGuestFunction(address, a0, a1, a2, a3, gp);
        }
    };

    class IopRpcBridge
    {
    public:
        IopRpcBridge(IopHost &host, IopMemory &memory, IopKernel &kernel, IopCdvd &cdvd) noexcept;

        void reset();
        [[nodiscard]] bool dispatchSifManImport(uint16_t ordinal, IopCpuState &cpu);
        [[nodiscard]] bool dispatchSifCmdImport(uint16_t ordinal, IopCpuState &cpu);
        [[nodiscard]] RpcResult handleRpc(const RpcRequest &request, IopGuestExecutor &executor);
        void onSifTransfer(const SifTransfer &transfer);
        void dispatchPendingRequests(uint32_t returnSentinel);
        void finishPendingRequest(uint64_t token, uint32_t result, bool faulted);
        void removeServersInRange(uint32_t base, uint32_t size);

        [[nodiscard]] bool hasServer(uint32_t sid) const noexcept;
        [[nodiscard]] size_t serverCount() const noexcept { return m_servers.size(); }

    private:
        struct RpcServer
        {
            uint32_t sid = 0;
            uint32_t serverData = 0;
            uint32_t function = 0;
            uint32_t gp = 0;
            uint32_t buffer = 0;
            uint32_t callback = 0;
            uint32_t callbackBuffer = 0;
            uint32_t queue = 0;
        };

        // IOP-side RPC clients of EE servers (sceSifBindRpc/sceSifCallRpc),
        // e.g. MCMAN notifying libmc's EE server after a fast read.
        struct IopClient
        {
            int eventFlag = 0;
            uint32_t endFunction = 0;
            uint32_t endParameter = 0;
            uint32_t bindSid = 0;
            // A call made before the EE server existed waits for a re-bind.
            bool callPending = false;
            std::array<uint32_t, 16> pendingCall{};
            uint32_t pendingSend = 0, pendingSendSize = 0;
        };
        [[nodiscard]] bool sendRpcPacket(uint32_t commandId, std::array<uint32_t, 16> &words,
                                         uint32_t extraSource, uint32_t extraDestination, uint32_t extraSize);
        void waitClient(IopCpuState &cpu, uint32_t client);
        void completeClientRpc(uint32_t packetAddress);
        std::unordered_map<uint32_t, IopClient> m_iopClients;
        uint32_t m_nextClientRpcId = 1u;

        IopHost &m_host;
        struct PendingRequest
        {
            RpcRequest request;
            RpcServer server;
            std::vector<uint8_t> send;
            bool active = false;
        };
        std::map<uint64_t, PendingRequest> m_pendingRequests;
        std::unordered_map<uint32_t, int> m_queueThreads;
        uint64_t m_nextRequestToken = 0u;
        std::array<uint32_t, 257> m_deferredCompletionTrace{};
        IopMemory &m_memory;
        IopKernel &m_kernel;
        IopCdvd &m_cdvd;
        std::unordered_map<uint32_t, RpcServer> m_servers;
        uint32_t m_nextDmaId = 1u;
        uint32_t m_dmaTraceCount = 0u;
        uint32_t m_rpcCaptureCount = 0u;
        bool m_sifInitialized = false;
    };
}

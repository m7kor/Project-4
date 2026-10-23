#pragma once

#include "ps2x/iop/iop_host.h"
#include "ps2x/iop/iop_types.h"

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace ps2x::iop::detail
{
    class IopEmulator
    {
    public:
        enum class GuestCallState { Rejected, Pending, Returned, Yielded, Faulted };
        struct GuestCallProgress
        {
            GuestCallState state = GuestCallState::Rejected;
            uint64_t token = 0u;
            uint32_t result = 0u;
            uint32_t instructions = 0u;
            uint32_t pc = 0u;
        };

        explicit IopEmulator(IopHost &host);
        ~IopEmulator();

        IopEmulator(const IopEmulator &) = delete;
        IopEmulator &operator=(const IopEmulator &) = delete;

        void reset();
        [[nodiscard]] ModuleLoadResult loadModule(std::string_view path, const void *arguments, uint32_t argumentSize);
        [[nodiscard]] ModuleLoadResult loadModuleBuffer(uint32_t guestAddress, const void *arguments, uint32_t argumentSize);
        [[nodiscard]] bool stopModule(int32_t moduleId, int32_t *result);
        void runEeCycles(uint64_t eeCycles) noexcept;
        uint32_t readAudio(int16_t *stereo, uint32_t frames);
        [[nodiscard]] RpcResult handleRpc(const RpcRequest &request);
        [[nodiscard]] bool hasRpcServer(uint32_t sid) const noexcept;
        void onSifTransfer(const SifTransfer &transfer);

        // Executor-owned continuations. A budget boundary preserves the complete
        // CPU state and an exclusive stack lease; it is not a completed call.
        [[nodiscard]] GuestCallProgress beginGuestCall(uint32_t address, uint32_t a0,
            uint32_t a1, uint32_t a2, uint32_t a3, uint32_t gp, uint32_t instructionBudget);
        [[nodiscard]] GuestCallProgress resumeGuestCall(uint64_t token, uint32_t instructionBudget);
        [[nodiscard]] bool cancelGuestCall(uint64_t token);

        [[nodiscard]] uint32_t allocateMemory(uint32_t size, uint32_t alignment = 16u);
        [[nodiscard]] bool freeMemory(uint32_t address);
        [[nodiscard]] bool readMemory(uint32_t address, void *destination, size_t size) const;
        [[nodiscard]] bool writeMemory(uint32_t address, const void *source, size_t size);
        [[nodiscard]] bool zeroMemory(uint32_t address, size_t size);
        [[nodiscard]] bool isMemoryRange(uint32_t address, size_t size) const;

        [[nodiscard]] uint64_t cycles() const noexcept;
        [[nodiscard]] uint64_t instructions() const noexcept;
        [[nodiscard]] uint32_t loadedModuleCount() const noexcept;
        [[nodiscard]] uint32_t threadCount() const noexcept;
        [[nodiscard]] uint32_t rpcServerCount() const noexcept;

    private:
        class Impl;
        std::unique_ptr<Impl> m_impl;
    };
}

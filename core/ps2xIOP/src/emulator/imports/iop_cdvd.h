#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string_view>
#include "ps2x/iop/iop_types.h"

namespace ps2x::iop
{
    class IopHost;
}

namespace ps2x::iop::detail
{
    struct IopCpuState;
    class IopKernel;
    class IopMemory;

    class IopCdvd
    {
    public:
        struct FileHandle { uint32_t lsn = 0u; uint32_t size = 0u; };
        struct CompletionCallback
        {
            uint32_t address = 0u;
            uint32_t gp = 0u;
            uint32_t reason = 0u;
        };

        IopCdvd(IopHost &host, IopMemory &memory, IopKernel &kernel);
        ~IopCdvd();

        IopCdvd(const IopCdvd &) = delete;
        IopCdvd &operator=(const IopCdvd &) = delete;

        void reset() noexcept;

        [[nodiscard]] bool dispatchImport(uint16_t ordinal, IopCpuState &cpu);
        [[nodiscard]] std::optional<FileHandle> openFile(std::string_view path);
        [[nodiscard]] size_t readFile(const FileHandle &file, uint32_t offset, uint8_t *destination, size_t size);
        [[nodiscard]] static bool hasBuiltinRpc(uint32_t sid) noexcept;
        [[nodiscard]] RpcResult handleRpc(const RpcRequest &request);
        [[nodiscard]] std::optional<CompletionCallback> takeCompletionCallback() noexcept;
        // Complete a guest-programmed DMA3 continuation of a DVD read.
        void serviceDma();

    private:
        class Impl;
        std::unique_ptr<Impl> m_impl;
    };
}

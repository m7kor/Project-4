#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <iostream>

// Opt-in observation of the exact RE4 TEXFLUSH/FINISH packet. No register
// reads, packet edits, scheduling changes, or synthetic completion.
namespace ps2x::diagnostics
{
    enum class FenceStage : unsigned { DmaCopy, MemorySubmit, GsEntry, GsDispatch, GpuEntry, Count };

    inline bool traceFencePacket(FenceStage stage, const void *data, uint32_t bytes)
    {
        static const uint64_t from = [] {
            const char *value = std::getenv("PS2X_GS_FENCE_PIPELINE_FROM");
            return value ? std::strtoull(value, nullptr, 0) : 0u;
        }();
        if (!from || !data || bytes != 48u)
            return false;
        constexpr std::array<uint64_t, 6> packet{0x1000000000008002ull, 0xeull, 0ull, 0x3full, 0ull, 0x61ull};
        if (std::memcmp(data, packet.data(), sizeof(packet)) != 0)
            return false;
        static std::array<std::atomic<uint64_t>, static_cast<unsigned>(FenceStage::Count)> counts{};
        const unsigned slot = static_cast<unsigned>(stage);
        const uint64_t index = counts[slot].fetch_add(1u, std::memory_order_relaxed) + 1u;
        if (index < from || index - from >= 4096u)
            return false;
        constexpr const char *names[]{"dma-copy", "memory-submit", "gs-entry", "gs-dispatch", "gpu-entry"};
        // One stdio operation keeps the record intact when the audio worker
        // writes diagnostics concurrently. Partial fields can mimic lost DMA.
        std::fprintf(stderr, "[GIF fence pipeline] stage=%s index=%llu bytes=%u\n",
                     names[slot], static_cast<unsigned long long>(index), bytes);
        return true;
    }
}

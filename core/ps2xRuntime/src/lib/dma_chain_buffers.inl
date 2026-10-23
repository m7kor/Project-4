// SPDX-License-Identifier: GPL-3.0-or-later
// Adapted design idea: KIexster/god-of-war-recomp, ps2recomp-dma-buffers,
// 1307cd4a. Pending transfers retain exclusive ownership until consumed.
namespace ps2x::dma_buffers
{
    struct Pool
    {
        std::mutex mutex;
        std::array<std::vector<uint8_t>, 4> buffers;
        size_t count = 0, bytes = 0;
        uint64_t reused = 0;
    };

    constexpr size_t kMaxCachedBytes = 32u * 1024u * 1024u;
    Pool &pool()
    {
        static Pool value;
        return value;
    }

    bool referenceMode()
    {
        static const bool enabled = [] {
            const char *value = std::getenv("PS2X_DMA_BUFFERS_REFERENCE");
            return value && *value == '1';
        }();
        return enabled;
    }

    std::vector<uint8_t> take()
    {
        if (referenceMode())
            return {};
        auto &state = pool();
        std::lock_guard<std::mutex> lock(state.mutex);
        if (!state.count)
            return {};
        auto result = std::move(state.buffers[--state.count]);
        state.bytes -= result.capacity();
        result.clear();
        ++state.reused;
        return result;
    }

    void give(std::vector<uint8_t> &&buffer)
    {
        if (referenceMode() || !buffer.capacity())
            return;
        auto &state = pool();
        std::lock_guard<std::mutex> lock(state.mutex);
        if (state.count == state.buffers.size() || buffer.capacity() > kMaxCachedBytes - state.bytes)
            return;
        buffer.clear();
        state.bytes += buffer.capacity();
        state.buffers[state.count++] = std::move(buffer);
    }
}

// Private diagnostics/test observations, declared only by their .cpp callers.
uint64_t ps2xDmaChainBuffersReused()
{
    auto &state = ps2x::dma_buffers::pool();
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.reused;
}

size_t ps2xDmaChainBuffersCachedBytes()
{
    auto &state = ps2x::dma_buffers::pool();
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.bytes;
}

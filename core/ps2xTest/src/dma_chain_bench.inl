// Isolated DMA flatten/allocation probe. No renderer and no game-speed claim.
extern uint64_t ps2xDmaChainBuffersReused();
extern size_t ps2xDmaChainBuffersCachedBytes();
namespace
{
    int benchmarkDmaBuffers(int argc, char **argv)
    {
        uint32_t transfers = 120;
        if (argc != 2)
        {
            if (argc != 4 || std::string(argv[2]) != "--transfers")
                throw std::runtime_error("--dma-buffers [--transfers 4..10000]");
            const std::string value = argv[3];
            const auto parsed = std::from_chars(value.data(), value.data() + value.size(), transfers);
            if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || transfers < 4 || transfers > 10000)
                throw std::runtime_error("invalid DMA transfer count");
        }
        PS2Memory memory;
        if (!memory.initialize())
            throw std::runtime_error("DMA benchmark memory initialization failed");
        constexpr uint32_t tag = 0x40000u, payload = 0x100000u, qwc = 65535u, chunks = 3u;
        constexpr uint32_t largeBytes = qwc * 16u * chunks;
        auto *ram = memory.getRDRAM();
        for (uint32_t i = 0; i < qwc * 16u; ++i)
            ram[payload + i] = static_cast<uint8_t>(i * 13u + 7u);
        for (uint32_t i = 0; i < chunks; ++i)
        {
            const uint64_t value = qwc | (3ull << 28u) | (uint64_t(payload) << 32u);
            std::memcpy(ram + tag + i * 16u, &value, sizeof(value));
        }
        const uint64_t end = 7ull << 28u;
        std::memcpy(ram + tag + chunks * 16u, &end, sizeof(end));
        const uint32_t shortTag = tag + 0x100u;
        const uint64_t shortEnd = 1ull | (7ull << 28u);
        std::memcpy(ram + shortTag, &shortEnd, sizeof(shortEnd));
        std::memcpy(ram + shortTag + 16u, ram + payload, 16u);
        bool validateAll = true;
        uint32_t expectedBytes = largeBytes, calls = 0;
        uint64_t bytes = 0, hash = 0xCBF29CE484222325ull;
        memory.setGifPacketCallback([&](const uint8_t *data, uint32_t size) {
            if (size != expectedBytes)
                throw std::runtime_error("DMA benchmark delivered stale or truncated data");
            if (validateAll)
            {
                const uint32_t partBytes = qwc * 16u;
                for (uint32_t at = 0; at < size; at += partBytes)
                    if (std::memcmp(data + at, ram + payload, std::min(partBytes, size - at)))
                        throw std::runtime_error("DMA benchmark payload differs");
            }
            else if (std::memcmp(data, ram + payload, 16u) ||
                     std::memcmp(data + size - 16u, ram + payload + (size == 16u ? 0u : qwc * 16u - 16u), 16u))
                throw std::runtime_error("DMA benchmark endpoints differ");
            hash = (hash ^ size) * 0x100000001B3ull;
            bytes += size;
            ++calls;
        });
        const auto send = [&](bool large) {
            expectedBytes = large ? largeBytes : 16u;
            memory.writeIORegister(0x1000A030u, large ? tag : shortTag);
            memory.writeIORegister(0x1000A000u, 0x104u);
        };
        send(true);
        send(false); // Full byte checks warm up both lengths outside timing.
        validateAll = false;
        bytes = hash = calls = 0;
        hash = 0xCBF29CE484222325ull;
        const auto beforeReuse = ps2xDmaChainBuffersReused();
        const auto start = std::chrono::steady_clock::now();
        for (uint32_t i = 0; i < transfers; ++i)
            send(i % 2u == 0);
        const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        if (calls != transfers)
            throw std::runtime_error("DMA benchmark did not deliver every transfer");
        std::printf("{\"mode\":\"dma-buffers\",\"transfers\":%u,\"bytes\":%llu,\"result\":\"%016llx\",\"reused\":%llu,\"cached_bytes\":%zu,\"seconds\":%.9f,\"ns_per_byte\":%.6f,\"full_byte_validation\":\"both warmup lengths; timed endpoints and lengths\"}\n",
                    calls, static_cast<unsigned long long>(bytes), static_cast<unsigned long long>(hash),
                    static_cast<unsigned long long>(ps2xDmaChainBuffersReused() - beforeReuse),
                    ps2xDmaChainBuffersCachedBytes(), seconds, seconds * 1e9 / bytes);
        return 0;
    }
}

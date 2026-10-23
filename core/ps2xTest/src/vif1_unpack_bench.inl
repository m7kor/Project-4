// Isolated VIF packet decode/unpack benchmark; no game-speed claim.
extern uint64_t ps2xVif1UnpackFastCalls();
namespace
{
    int benchmarkVifUnpack(int argc, char **argv)
    {
        uint32_t transfers = 10000u;
        if (argc != 2)
        {
            if (argc != 4 || std::string(argv[2]) != "--transfers")
                throw std::runtime_error("--vif-unpack [--transfers 10..1000000]");
            const std::string value = argv[3];
            const auto parsed = std::from_chars(value.data(), value.data() + value.size(), transfers);
            if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || transfers < 10u || transfers > 1000000u)
                throw std::runtime_error("invalid VIF transfer count");
        }
        PS2Memory memory;
        if (!memory.initialize())
            throw std::runtime_error("VIF benchmark memory initialization failed");
        uint64_t hash = 0xCBF29CE484222325ull;
        double seconds = 0;
        uint64_t vectors = 0;
        const uint64_t before = ps2xVif1UnpackFastCalls();
        const auto append = [](std::vector<uint8_t> &packet, uint32_t word) {
            const size_t position = packet.size();
            packet.resize(position + 4u);
            std::memcpy(packet.data() + position, &word, 4u);
        };
        for (uint32_t width = 0; width < 2; ++width)
            for (const uint32_t count : {16u, 64u, 256u})
                for (const uint32_t cycle : {0x0101u, 0x0103u, 0x0304u})
                    for (const bool zeroExtend : {false, true})
                    {
                        std::vector<uint8_t> packet;
                        append(packet, 0x01000000u | cycle);
                        append(packet, 0x05000000u);
                        const uint32_t address = 1018u;
                        append(packet, ((0x6Cu | width) << 24u) | ((count & 0xFFu) << 16u) |
                                       (zeroExtend ? 0x4000u : 0u) | address);
                        const uint32_t stride = width ? 8u : 16u;
                        for (uint32_t byte = 0; byte < count * stride; ++byte)
                            packet.push_back(static_cast<uint8_t>(byte * 137u + 193u));
                        std::vector<uint8_t> expected(PS2_VU1_DATA_SIZE, 0xA6u);
                        const uint32_t cl = cycle & 0xFFu, wl = cycle >> 8u;
                        for (uint32_t vector = 0; vector < count; ++vector)
                        {
                            const uint32_t dest = (address + vector / wl * cl + vector % wl) & 0x3FFu;
                            for (uint32_t lane = 0; lane < 4; ++lane)
                            {
                                uint32_t expanded;
                                if (!width)
                                    std::memcpy(&expanded, packet.data() + 12u + vector * stride + lane * 4u, 4u);
                                else
                                {
                                    uint16_t raw;
                                    std::memcpy(&raw, packet.data() + 12u + vector * stride + lane * 2u, 2u);
                                    expanded = zeroExtend ? static_cast<uint32_t>(raw)
                                                          : static_cast<uint32_t>(static_cast<int32_t>(static_cast<int16_t>(raw)));
                                }
                                std::memcpy(expected.data() + dest * 16u + lane * 4u, &expanded, 4u);
                            }
                        }
                        std::memset(memory.getVU1Data(), 0xA6, PS2_VU1_DATA_SIZE);
                        memory.processVIF1Data(packet.data(), static_cast<uint32_t>(packet.size()));
                        if (std::memcmp(memory.getVU1Data(), expected.data(), PS2_VU1_DATA_SIZE))
                            throw std::runtime_error("VIF warmup differs from the independent lane oracle");
                        const auto start = std::chrono::steady_clock::now();
                        for (uint32_t transfer = 0; transfer < transfers; ++transfer)
                            memory.processVIF1Data(packet.data(), static_cast<uint32_t>(packet.size()));
                        seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
                        vectors += static_cast<uint64_t>(transfers) * count;
                        if (std::memcmp(memory.getVU1Data(), expected.data(), PS2_VU1_DATA_SIZE))
                            throw std::runtime_error("VIF timed output differs from the independent lane oracle");
                        for (uint32_t byte = 0; byte < PS2_VU1_DATA_SIZE; ++byte)
                            hash = (hash ^ memory.getVU1Data()[byte]) * 0x100000001B3ull;
                    }
        std::printf("{\"mode\":\"vif-unpack\",\"transfers_per_case\":%u,\"cases\":36,\"vectors\":%llu,"
                    "\"seconds\":%.9f,\"ns_per_vector\":%.6f,\"result\":\"%016llx\",\"fast_calls\":%llu}\n",
                    transfers, static_cast<unsigned long long>(vectors), seconds, seconds * 1e9 / vectors,
                    static_cast<unsigned long long>(hash),
                    static_cast<unsigned long long>(ps2xVif1UnpackFastCalls() - before));
        return 0;
    }
}

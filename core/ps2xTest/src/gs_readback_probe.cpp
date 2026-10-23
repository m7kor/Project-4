// Procedural GPU presentation probe: no game data or memory card is used.
#include "runtime/gs/gs_parallel_bridge.h"
#include "runtime/gs/gs_types.h"
#include "runtime/ps2_memory.h"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

int main(int argc, char **argv)
{
    if (argc != 2)
    {
        std::cerr << "usage: ps2x_gs_readback_probe output-directory\n";
        return 2;
    }
    const std::filesystem::path output(argv[1]);
    if (std::filesystem::exists(output))
    {
        std::cerr << "Existing probe output is preserved\n";
        return 2;
    }
    std::filesystem::create_directories(output);
    ParallelGsBridge bridge;
    if (!bridge.init({}, 1)) return 3;
    std::ofstream metadata(output / "frames.jsonl");
    for (unsigned i = 0; i < 16; ++i)
    {
        // Reinitialization must safely retire a still-pending readback.
        if (i == 12 && !bridge.init({}, 1)) return 3;
        const uint32_t sourceWidth = i >= 4 && i < 8 ? 128u : 64u;
        const uint32_t sourceHeight = i >= 4 && i < 8 ? 64u : 32u;
        const uint32_t fbw = sourceWidth / 64u;
        const uint32_t fbp = (i & 1u) * 8u;
        std::vector<uint8_t> source(size_t(sourceWidth) * sourceHeight * 4u);
        for (uint32_t y = 0; y < sourceHeight; ++y)
            for (uint32_t x = 0; x < sourceWidth; ++x)
            {
                uint8_t *p = source.data() + (size_t(y) * sourceWidth + x) * 4u;
                p[0] = static_cast<uint8_t>(i * 17u + x * 3u);
                p[1] = static_cast<uint8_t>(i * 11u + y * 5u);
                p[2] = static_cast<uint8_t>(x ^ y ^ (i * 13u));
                p[3] = 0x80u;
            }
        // CT32 host upload: DBP uses 256-byte units, DISPFB uses 8 KiB pages.
        bridge.uploadImage((uint64_t(fbp * 32u) << 32) | (uint64_t(fbw) << 48),
                           0, uint64_t(sourceWidth) | (uint64_t(sourceHeight) << 32),
                           0, source.data(), static_cast<uint32_t>(source.size()));
        GSRegisters regs{};
        regs.pmode = 0x8065u; // One enabled circuit, opaque output.
        regs.smode1 = i >= 4 && i < 8 ? 0x740836504ull : 0x740834504ull;
        regs.dispfb1 = uint64_t(fbp) | (uint64_t(fbw) << 9);
        // NTSC display origin and five video-clock samples per input pixel.
        regs.display1 = 636u | (51ull << 12) | (4ull << 23) |
                        (uint64_t(sourceWidth * 5u - 1u) << 32) | (uint64_t(sourceHeight - 1u) << 44);
        GSPresentationRequest request{};
        request.vsyncTick = 100u + i;
        request.pmode = regs.pmode;
        request.dispfb1 = regs.dispfb1;
        request.display1 = regs.display1;
        GSPresentationRequest presented{};
        std::vector<uint8_t> pixels;
        uint32_t width = 0, height = 0;
        if (!bridge.vsync(regs, static_cast<uint32_t>(request.vsyncTick), pixels,
                          width, height, &request, &presented) || !width || !height)
        {
            std::cerr << "Missing scanout at " << i << '\n';
            return 4;
        }
        std::ofstream image(output / ("frame-" + std::to_string(i) + ".rgba"), std::ios::binary);
        image.write(reinterpret_cast<const char *>(pixels.data()), static_cast<std::streamsize>(pixels.size()));
        if (!image) return 5;
        metadata << "{\"index\":" << i << ",\"presented_tick\":" << presented.vsyncTick
                 << ",\"width\":" << width << ",\"height\":" << height
                 << ",\"dispfb1\":" << presented.dispfb1
                 << ",\"display1\":" << presented.display1 << "}\n";
    }
    return metadata ? 0 : 6;
}

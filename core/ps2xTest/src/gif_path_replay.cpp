// Real GPU regression: a split IMAGE on PATH2 cannot consume PATH3 FINISH.
#include "runtime/gs/gs_parallel_bridge.h"
#include <array>
#include <cstdint>
#include <iostream>

struct Result { uint32_t middle, final; bool initialized; };
Result replay(bool merged)
{
    ParallelGsBridge gs;
    uint32_t finishes = 0;
    ParallelGsBridge::Signals signals;
    signals.finish = [&](uint64_t) { ++finishes; return false; };
    if (!gs.init(signals, 1)) return {0, 0, false};
    gs.writeRegister(0x50, (8ull << 32) | (1ull << 48)); // CT32 destination.
    gs.writeRegister(0x51, 0);
    gs.writeRegister(0x52, 16ull | (16ull << 32)); // 1024 bytes = 64 qwords.
    gs.writeRegister(0x53, 0);
    const uint32_t imagePath = merged ? 3u : 2u;
    const std::array<uint64_t, 2> image{64ull | 0x8000ull | (2ull << 58), 0};
    const std::array<uint64_t, 6> fence{0x1000000000008002ull, 0xeull, 0ull, 0x3full, 0ull, 0x61ull};
    gs.gifTransfer(image.data(), sizeof(image), imagePath);
    gs.gifTransfer(fence.data(), sizeof(fence), 3u);
    const uint32_t middle = finishes;
    const std::array<uint64_t, 128> pixels{};
    // With the old merged route, the fence's three qwords became image data.
    gs.gifTransfer(pixels.data(), merged ? sizeof(pixels) - sizeof(fence) : sizeof(pixels), imagePath);
    gs.gifTransfer(fence.data(), sizeof(fence), imagePath);
    return {middle, finishes, true};
}

int main()
{
    const Result old = replay(true), fixed = replay(false);
    std::cout << "{\"merged_middle\":" << old.middle << ",\"merged_final\":" << old.final
              << ",\"separate_middle\":" << fixed.middle << ",\"separate_final\":" << fixed.final << "}\n";
    return old.initialized && fixed.initialized && old.middle == 0u && old.final == 1u
           && fixed.middle == 1u && fixed.final == 2u ? 0 : 1;
}

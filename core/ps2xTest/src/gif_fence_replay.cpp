// Replays a caller-supplied GIF fence on the production CPU and Vulkan paths.
// No game executable, content fixture, or memory card is loaded.
#include "runtime/gs/gs_frontend.h"
#include "runtime/gs/gs_parallel_bridge.h"
#include "runtime/ps2_memory.h"
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

int main(int argc, char **argv)
{
    if (argc != 2) { std::cerr << "usage: ps2x_gif_fence_replay packet.bin\n"; return 2; }
    const auto bytes = std::filesystem::file_size(argv[1]);
    if (bytes != 48u) { std::cerr << "Expected a 48-byte TEXFLUSH/FINISH fence\n"; return 2; }
    std::array<uint64_t, 6> packet{};
    std::ifstream input(argv[1], std::ios::binary);
    input.read(reinterpret_cast<char *>(packet.data()), sizeof(packet));
    constexpr std::array<uint64_t, 6> expected{0x1000000000008002ull, 0xeull, 0ull, 0x3full, 0ull, 0x61ull};
    if (!input || packet != expected) { std::cerr << "Unexpected fence contents\n"; return 2; }
    // The CPU reference is the same parser used by the runtime's CPU backend.
    std::vector<uint8_t> vram(4u * 1024u * 1024u);
    GSRegisters regs{};
    GS cpu;
    cpu.init(vram.data(), static_cast<uint32_t>(vram.size()), &regs);
    cpu.processGIFPacket(reinterpret_cast<const uint8_t *>(packet.data()), sizeof(packet));
    const bool cpuFinish = (regs.csr.load() & 2u) != 0u;
    uint32_t gpuFinishes = 0u;
    ParallelGsBridge::Signals signals;
    signals.finish = [&](uint64_t) { ++gpuFinishes; return false; };
    ParallelGsBridge gpu;
    if (!gpu.init(signals, 1)) { std::cerr << "Vulkan backend unavailable\n"; return 3; }
    gpu.gifTransfer(packet.data(), sizeof(packet));
    std::cout << "{\"cpu_finish\":" << (cpuFinish ? "true" : "false")
              << ",\"gpu_finish_callbacks\":" << gpuFinishes << ",\"packet_bytes\":" << bytes << "}\n";
    return cpuFinish && gpuFinishes == 1u ? 0 : 4;
}

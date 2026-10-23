// Procedural CSC throughput fixture. Identical output is required in both
// PS2X_IPU_CSC_BIT_READER=1 and the default byte-copy mode; this is not game FPS.
#include "runtime/ps2_ipu.h"
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>

namespace {
struct Host final : Ps2IpuHost {
    uint32_t regs[2][4]{};
    uint8_t *ipuDmaPointer(uint32_t, uint32_t) override { return nullptr; }
    uint32_t &ipuDmaRegister(int c, int r) override { return regs[c == 4][r & 3]; }
    void ipuDmaComplete(int) override {}
    bool ipuDmaSuspended() override { return false; }
    void ipuRaiseInterrupt() override {}
};
}
int main() {
    Host host;
    Ps2Ipu ipu(host);
    std::array<uint8_t, 384> input;
    std::array<uint8_t, 1024> output;
    uint32_t random = 0x12345678u;
    for (auto &byte : input) {
        random = random * 1664525u + 1013904223u;
        byte = static_cast<uint8_t>(random >> 24);
    }
    constexpr unsigned blocks = 500000;
    uint64_t checksum = 0;
    const auto start = std::chrono::steady_clock::now();
    for (unsigned i = 0; i < blocks; ++i) {
        ipu.testFeed(input.data(), input.size());
        ipu.writeRegister(0x10002000u, 0x70000001u);
        if (ipu.busy() || ipu.testReadOutput(output.data(), output.size()) != output.size()) return 1;
        checksum += output[i % output.size()];
    }
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    std::cout << "{\"blocks\":" << blocks << ",\"milliseconds\":" << ms
              << ",\"checksum\":" << checksum << ",\"bit_reader\":"
              << (std::getenv("PS2X_IPU_CSC_BIT_READER") ? "true" : "false") << "}\n";
}

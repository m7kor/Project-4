// The GS cache suites build gs_frontend.cpp without paraLLEl-GS (Vulkan).
// This stub makes the GPU backend unavailable, so the frontend keeps the CPU
// GS exactly as when no Vulkan device exists.
#include "runtime/gs/gs_parallel_bridge.h"

struct ParallelGsBridge::Impl
{
};

ParallelGsBridge::ParallelGsBridge() = default;
ParallelGsBridge::~ParallelGsBridge() = default;
bool ParallelGsBridge::init(const Signals &, uint32_t) { return false; }
void ParallelGsBridge::gifTransfer(const void *, size_t, uint32_t) {}
void ParallelGsBridge::writeRegister(uint8_t, uint64_t) {}
void ParallelGsBridge::uploadImage(uint64_t, uint64_t, uint64_t, uint64_t, const uint8_t *, uint32_t) {}
uint32_t ParallelGsBridge::readTransfer(uint8_t *, uint32_t) { return 0u; }
const uint8_t *ParallelGsBridge::mapVramRead() { return nullptr; }
uint8_t *ParallelGsBridge::mapVramWrite() { return nullptr; }
void ParallelGsBridge::endVramWrite() {}
void ParallelGsBridge::flush() {}
bool ParallelGsBridge::vsync(const GSRegisters &, uint32_t, std::vector<uint8_t> &, uint32_t &, uint32_t &,
                            const GSPresentationRequest *, GSPresentationRequest *)
{
    return false;
}

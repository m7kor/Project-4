#pragma once

// GPU GS: paraLLEl-GS (LGPL-3.0+, Arntzen Software AS) behind a small bridge.
// The GS frontend forwards GIF transfers (including packet fragments) here when
// PS2X_GS_BACKEND=parallel; paraLLEl-GS rasterizes them with Vulkan compute
// shaders. SIGNAL/FINISH/LABEL come back synchronously while a packet is
// parsed, so CSR interrupt timing is the same as with the CPU renderer. At
// each vsync the scanout image is read back into host memory for the existing
// presentation path. No Vulkan types leak out of this header.

#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

struct GSRegisters;
struct GSPresentationRequest;

class ParallelGsBridge
{
public:
    struct Signals
    {
        std::function<bool(uint64_t)> signal, finish, label;
    };

    ParallelGsBridge();
    ~ParallelGsBridge();

    // Creates the Vulkan device and the GS. Returns false (and logs why) when
    // no suitable GPU or driver is available; the caller keeps the CPU GS.
    bool init(const Signals &signals, uint32_t superSampling);

    void gifTransfer(const void *data, size_t bytes, uint32_t pathId = 3u);
    void writeRegister(uint8_t address, uint64_t value);
    // Host -> local image upload as one GIF IMAGE packet (TRX registers first).
    void uploadImage(uint64_t bitbltbuf, uint64_t trxpos, uint64_t trxreg, uint64_t trxdir,
                     const uint8_t *data, uint32_t bytes);
    // GS -> host transfer data (TRXDIR = 1), in 16-byte units.
    uint32_t readTransfer(uint8_t *dst, uint32_t maxBytes);
    // Synchronized view of the 4 MB local memory.
    const uint8_t *mapVramRead();
    uint8_t *mapVramWrite();
    void endVramWrite();
    void flush();

    // Scans out a field as tightly packed RGBA8. After bootstrap the buffered
    // path returns the preceding image with its own presentation metadata.
    bool vsync(const GSRegisters &priv, uint32_t field, std::vector<uint8_t> &rgba,
               uint32_t &width, uint32_t &height,
               const GSPresentationRequest *request = nullptr,
               GSPresentationRequest *presentedRequest = nullptr);

private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};

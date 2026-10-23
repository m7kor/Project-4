#include "runtime/gs/gs_parallel_bridge.h"
#include "runtime/ps2_memory.h"
#include "runtime/gs/gs_types.h"
#include "gs_fence_trace.h"

#include "gs_interface.hpp"
#include "context.hpp"
#include "device.hpp"
#include "command_buffer.hpp"
#include "thread_id.hpp"

#include <atomic>
#include <array>
#include <cassert>
#include <charconv>

#include <algorithm>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <string>
#include <iostream>

using namespace Vulkan;
using namespace ParallelGS;

namespace
{
    class BridgeSignals final : public SignalInterface
    {
    public:
        ParallelGsBridge::Signals callbacks;
        uint64_t *signalCount = nullptr, *finishCount = nullptr, *labelCount = nullptr;
        bool on_signal(uint64_t payload) override { ++*signalCount; return callbacks.signal && callbacks.signal(payload); }
        bool on_finish(uint64_t payload) override { ++*finishCount; return callbacks.finish && callbacks.finish(payload); }
        bool on_label(uint64_t payload) override { ++*labelCount; return callbacks.label && callbacks.label(payload); }
    };

    // Granite needs every calling thread registered with an index below
    // set_num_thread_indices(). GS calls come from the GS worker and, for
    // synchronous packets and VBlank, the EE thread.
    constexpr unsigned kThreadIndices = 4;
    void registerCallingThread()
    {
        static std::atomic<unsigned> next{0};
        thread_local bool registered = false;
        if (!registered)
        {
            Util::register_thread_index(next.fetch_add(1) % kThreadIndices);
            registered = true;
        }
    }

    template <typename Bits>
    void assignRaw(Bits &dst, uint64_t value)
    {
        // The register fields live in the low 64 bits of each struct; a few are
        // 4 bytes, and SMODE2Bits pads to 12 (its first word sums to 33 bits).
        std::memset(&dst, 0, sizeof(Bits));
        std::memcpy(&dst, &value, sizeof(Bits) < sizeof(value) ? sizeof(Bits) : sizeof(value));
    }
}

struct ParallelGsBridge::Impl
{
    Context context;
    Device device;
    GSInterface gs;
    BridgeSignals signals;
    struct ReadbackFrame
    {
        BufferHandle buffer;
        ImageHandle image;
        Fence fence;
        VkDeviceSize capacity = 0;
        uint32_t width = 0, height = 0;
        GSPresentationRequest request{};
        bool pending = false;
    };
    ReadbackFrame readbacks[2];
    unsigned readbackNext = 0;
    // Diagnostics, printed every 600 vsyncs.
    uint64_t transfers = 0, transferBytes = 0, uploads = 0, finishes = 0, signalCount = 0, labels = 0;
    uint64_t vsyncs = 0, scanouts = 0, resyncs = 0;
    bool vramMappedForWrite = false;
    bool preserveContinuations = false;
    std::string packetCapturePrefix;
    uint64_t packetCaptureFrom = 0, packetCaptureCount = 0;
};

ParallelGsBridge::ParallelGsBridge() = default;

ParallelGsBridge::~ParallelGsBridge()
{
    if (m_impl)
    {
        m_impl->gs.flush();
        m_impl->device.wait_idle();
    }
}

bool ParallelGsBridge::init(const Signals &signals, uint32_t superSampling)
{
    auto impl = std::make_unique<Impl>();
    impl->preserveContinuations = std::getenv("PS2X_GS_PRESERVE_CONTINUATIONS") != nullptr;
    if (const char *prefix = std::getenv("PS2X_GS_CAPTURE_TRANSFER_PREFIX"))
    {
        const auto parse = [](const char *name, uint64_t &value) {
            const char *text = std::getenv(name);
            if (!text || !*text) return false;
            const char *end = text + std::strlen(text);
            const auto result = std::from_chars(text, end, value);
            return result.ec == std::errc{} && result.ptr == end;
        };
        if (*prefix && parse("PS2X_GS_CAPTURE_TRANSFER_FROM", impl->packetCaptureFrom) &&
            parse("PS2X_GS_CAPTURE_TRANSFER_COUNT", impl->packetCaptureCount) &&
            impl->packetCaptureFrom > 0 && impl->packetCaptureCount > 0 && impl->packetCaptureCount <= 128 &&
            impl->packetCaptureFrom <= UINT64_MAX - impl->packetCaptureCount + 1)
            impl->packetCapturePrefix = prefix;
        else
            std::cerr << "[gs:capture:error] Invalid bounded packet capture settings; capture disabled\n";
    }
    if (!Context::init_loader(nullptr))
    {
        std::cerr << "[gs:gpu] Vulkan loader not found; using the CPU GS" << std::endl;
        return false;
    }
    registerCallingThread();
    impl->context.set_num_thread_indices(kThreadIndices);
    if (!impl->context.init_instance_and_device(nullptr, 0, nullptr, 0,
                                                CONTEXT_CREATION_ENABLE_PUSH_DESCRIPTOR_BIT |
                                                    CONTEXT_CREATION_ENABLE_DESCRIPTOR_HEAP_BIT |
                                                    CONTEXT_CREATION_ENABLE_DESCRIPTOR_BUFFER_BIT))
    {
        std::cerr << "[gs:gpu] no suitable Vulkan device; using the CPU GS" << std::endl;
        return false;
    }
    impl->device.set_context(impl->context);
    impl->device.init_frame_contexts(4);

    GSOptions options = {};
    switch (superSampling)
    {
    case 2: options.super_sampling = SuperSampling::X2; break;
    case 4: options.super_sampling = SuperSampling::X4; break;
    case 8: options.super_sampling = SuperSampling::X8; break;
    case 16: options.super_sampling = SuperSampling::X16; break;
    default: options.super_sampling = SuperSampling::X1; break;
    }
    if (!impl->gs.init(&impl->device, options))
    {
        std::cerr << "[gs:gpu] paraLLEl-GS initialization failed; using the CPU GS" << std::endl;
        return false;
    }
    impl->signals.callbacks = signals;
    impl->signals.signalCount = &impl->signalCount;
    impl->signals.finishCount = &impl->finishes;
    impl->signals.labelCount = &impl->labels;
    impl->gs.set_signal_interface(&impl->signals);
    std::cerr << "[gs:gpu] paraLLEl-GS on " << impl->device.get_gpu_properties().deviceName
              << " (super-sampling x" << (superSampling ? superSampling : 1u) << ")" << std::endl;
    if (m_impl)
    {
        m_impl->gs.flush();
        m_impl->device.wait_idle();
    }
    m_impl = std::move(impl);
    return true;
}

void ParallelGsBridge::gifTransfer(const void *data, size_t bytes, uint32_t pathId)
{
    if (pathId < 1u || pathId > 3u)
        return;
    const uint32_t pathIndex = pathId - 1u;
    registerCallingThread();
    // Preserve each GIF path's tag/image continuation. Merging paths lets an
    // unfinished IMAGE on one path swallow another path's FINISH packet.
    ++m_impl->transfers;
    static const bool trace = std::getenv("PS2X_TRACE_PATH3") != nullptr;
    if (trace && (bytes <= 128u || (m_impl->transfers > 31850u && m_impl->transfers < 31870u)))
    {
        std::cerr << "[gs:gpu] transfer #" << m_impl->transfers << " bytes=" << bytes << " finish=" << m_impl->finishes << " head=";
        const auto *b = static_cast<const uint8_t *>(data);
        char hex[4];
        for (size_t i = 0; i < std::min<size_t>(bytes, 128u); ++i)
        {
            std::snprintf(hex, sizeof(hex), "%02x", b[i]);
            std::cerr << hex;
        }
        std::cerr << std::endl;
    }
    m_impl->transferBytes += bytes;
    // DMA/VIF transfers may end inside PACKED, REGLIST or IMAGE payloads.
    // GSInterface retains loop/reg for each path; transfer boundaries are not
    // GIF tag boundaries. Resetting here reinterprets vertices as new tags.
    auto &path = m_impl->gs.get_gif_path(pathIndex);
    const bool capturePacket = !m_impl->packetCapturePrefix.empty() &&
        m_impl->transfers >= m_impl->packetCaptureFrom &&
        m_impl->transfers - m_impl->packetCaptureFrom < m_impl->packetCaptureCount;
    // Fixed little-endian uint64 header, followed by the complete input bytes.
    // State snapshots: before reset, effective parser entry, parser exit.
    std::array<uint64_t, 20> captureHeader;
    const auto captureState = [&](size_t first) {
        static_assert(sizeof(path.tag) == 16);
        captureHeader[first] = path.loop;
        captureHeader[first + 1] = path.reg;
        std::memcpy(captureHeader.data() + first + 2, &path.tag, sizeof(path.tag));
    };
    if (capturePacket)
    {
        captureHeader[0] = 0x3143525453473250ull; // "P2GSTRC1"
        captureHeader[1] = 1;
        captureHeader[2] = m_impl->transfers;
        captureHeader[3] = pathId;
        captureHeader[4] = bytes;
        captureHeader[5] = m_impl->vsyncs;
        captureHeader[6] = m_impl->finishes;
        captureHeader[7] = 0;
        captureState(8);
    }
    const bool traceFence = ps2x::diagnostics::traceFencePacket(ps2x::diagnostics::FenceStage::GpuEntry, data, static_cast<uint32_t>(bytes));
    if (traceFence)
        std::cerr << "[GIF fence GPU state] path=" << pathId << " transfer=" << m_impl->transfers << " finish=" << m_impl->finishes
                  << " loop=" << path.loop << " nloop=" << path.tag.NLOOP << " reg=" << path.reg
                  << " flg=" << path.tag.FLG << '\n';
    // Strict preservation exposes malformed state in RE4's current stream.
    // Keep established packet-boundary compatibility while investigating the
    // producer ordering; strict mode is an explicit diagnostic option only.
    if (!m_impl->preserveContinuations && path.loop != path.tag.NLOOP && path.tag.FLG != GIFTagBits::IMAGE)
    {
        if (trace || m_impl->resyncs < 8u)
            std::cerr << "[gs:gpu] PATH" << pathId << " resync #" << m_impl->resyncs << " before transfer #" << m_impl->transfers
                      << " (loop " << path.loop << " of " << path.tag.NLOOP << ", reg " << path.reg
                      << ", flg " << path.tag.FLG << ")" << std::endl;
        ++m_impl->resyncs;
        if (capturePacket) captureHeader[7] = 1;
        path.loop = path.tag.NLOOP;
        path.reg = 0;
    }
    const bool imagePendingBefore = path.loop != path.tag.NLOOP;
    if (trace && imagePendingBefore)
        std::cerr << "[gs:gpu] transfer #" << m_impl->transfers << " bytes=" << bytes << " continues IMAGE ("
                  << (path.tag.NLOOP - path.loop) << " qwords left)" << std::endl;
    static const bool traceFbp0 = std::getenv("PS2X_TRACE_GPU_FBP0") != nullptr;
    static int fbp0Logged = 0;
    static bool blitDumped = false;
    if (traceFbp0)
    {
        // A+D qwords anywhere in the packet: low word data, high word address.
        const auto *q = static_cast<const uint64_t *>(data);
        for (size_t i = 0; i + 1 < bytes / 8u; i += 2)
            if ((q[i + 1] & 0xFFu) == 0x50u && (q[i + 1] >> 8) == 0u && ((q[i] >> 32) & 0x3FFFu) < 0xE00u)
            {
                ++fbp0Logged;
                std::cerr << "[gs:gpu] transfer #" << m_impl->transfers << " vsync " << m_impl->vsyncs << " BITBLTBUF=0x" << std::hex
                          << q[i] << std::dec << " (DBP below page 112)" << std::endl;
                break;
            }
            else if ((q[i + 1] & 0xFFu) == 0x53u && (q[i + 1] >> 8) == 0u && (q[i] & 3u) != 0u)
            {
                ++fbp0Logged;
                std::cerr << "[gs:gpu] transfer #" << m_impl->transfers << " vsync " << m_impl->vsyncs << " TRXDIR=" << (q[i] & 3u) << std::endl;
                break;
            }
            else if ((q[i + 1] & 0xFFu) == 0x4cu && (q[i] & 0x1FFu) == 0u && (q[i + 1] >> 8) == 0u && bytes == 1936u &&
                     (m_impl->vsyncs % 120u) < 2u)
            {
                for (size_t k = 0; k + 1 < bytes / 8u; k += 2)
                    if ((q[k + 1] & 0xFFu) == 0x00u && q[k] == 0x116u && k + 3 < bytes / 8u)
                    {
                        std::cerr << "[gs:gpu] vsync " << m_impl->vsyncs << " display copy RGBAQ=0x" << std::hex << q[k + 2]
                                  << std::dec << std::endl;
                        break;
                    }
                break;
            }
            else if ((q[i + 1] & 0xFFu) == 0x4cu && (q[i] & 0x1FFu) == 0u && (q[i + 1] >> 8) == 0u && bytes == 1936u && m_impl->vsyncs >= 600u && !blitDumped)
            {
                blitDumped = true;
                std::cerr << "[gs:gpu] blit packet:" << std::endl;
                char line[64];
                for (size_t k = 0; k < bytes / 16u; ++k)
                {
                    std::snprintf(line, sizeof(line), "  %03zu %016llx %016llx", k,
                                  static_cast<unsigned long long>(q[2 * k + 1]), static_cast<unsigned long long>(q[2 * k]));
                    std::cerr << line << std::endl;
                }
                ++fbp0Logged;
                std::cerr << "[gs:gpu] transfer #" << m_impl->transfers << " bytes=" << bytes << " sets FRAME_1=0x" << std::hex
                          << q[i] << std::dec << " at qword " << i / 2 << std::endl;
                break;
            }
    }
    if (capturePacket) captureState(12);
    m_impl->gs.gif_transfer(pathIndex, data, bytes);
    if (capturePacket)
    {
        captureState(16);
        const std::string fileName = m_impl->packetCapturePrefix + "-" +
            std::to_string(m_impl->transfers) + "-path" + std::to_string(pathId) + ".giftrace";
        std::FILE *file = bytes <= PS2_RAM_SIZE ? std::fopen(fileName.c_str(), "wbx") : nullptr;
        bool written = false;
        if (file)
        {
            written = std::fwrite(captureHeader.data(), sizeof(uint64_t), captureHeader.size(), file) == captureHeader.size() &&
                std::fwrite(data, 1, bytes, file) == bytes;
            written = std::fclose(file) == 0 && written;
        }
        if (!written)
        {
            std::cerr << "[gs:capture:error] Capture failed without overwriting existing files: " << fileName << '\n';
            m_impl->packetCapturePrefix.clear();
        }
        else
            std::cerr << "[gs:capture] transfer=" << m_impl->transfers << " path=" << pathId
                      << " bytes=" << bytes << " resync=" << captureHeader[7] << '\n';
    }
    static int dumps = 0;
    if (path.loop != path.tag.NLOOP && path.tag.FLG == 3u && dumps < 3)
    {
        ++dumps;
        std::cerr << "[gs:gpu] transfer #" << m_impl->transfers << " bytes=" << bytes
                  << " left a FLG=3 tag pending; qwords:" << std::endl;
        const auto *q = static_cast<const uint64_t *>(data);
        char line[64];
        for (size_t i = 0; i < std::min<size_t>(bytes / 16u, 256u); ++i)
        {
            std::snprintf(line, sizeof(line), "  %03zu %016llx %016llx", i,
                          static_cast<unsigned long long>(q[2 * i + 1]), static_cast<unsigned long long>(q[2 * i]));
            std::cerr << line << std::endl;
        }
    }
    if (trace && path.loop != path.tag.NLOOP && path.tag.FLG == GIFTagBits::IMAGE)
        std::cerr << "[gs:gpu] transfer #" << m_impl->transfers << " bytes=" << bytes << " leaves IMAGE pending ("
                  << (path.tag.NLOOP - path.loop) << " of " << path.tag.NLOOP << " qwords left)" << std::endl;
}

void ParallelGsBridge::writeRegister(uint8_t address, uint64_t value)
{
    registerCallingThread();
    static const bool trace = std::getenv("PS2X_TRACE_GPU_FBP0") != nullptr;
    static int logged = 0;
    if (trace && address == 0x4c && (value & 0x1FFu) == 0u && logged < 20)
    {
        ++logged;
        std::cerr << "[gs:gpu] writeRegister FRAME_1=0x" << std::hex << value << std::dec << " (direct)" << std::endl;
    }
    m_impl->gs.write_register(static_cast<RegisterAddr>(address), value);
}

void ParallelGsBridge::uploadImage(uint64_t bitbltbuf, uint64_t trxpos, uint64_t trxreg, uint64_t trxdir,
                                   const uint8_t *data, uint32_t bytes)
{
    ++m_impl->uploads;
    writeRegister(0x50, bitbltbuf);
    writeRegister(0x51, trxpos);
    writeRegister(0x52, trxreg);
    writeRegister(0x53, trxdir);
    // NLOOP is 15 bits: an image larger than 32767 qwords (512 KB, e.g. a full
    // 640x448 frame) must be split into several IMAGE tags, or the excess is
    // parsed as GIF tags and the path's state machine is lost.
    constexpr uint32_t kMaxQwordsPerTag = 0x7FFFu;
    const uint32_t qwords = (bytes + 15u) / 16u;
    std::vector<uint8_t> packet;
    uint32_t done = 0;
    while (done < qwords)
    {
        const uint32_t chunk = std::min(kMaxQwordsPerTag, qwords - done);
        const bool last = done + chunk == qwords;
        packet.assign(16u + static_cast<size_t>(chunk) * 16u, 0u);
        // GIFtag: NLOOP = chunk, EOP on the last tag, FLG = IMAGE (2).
        const uint64_t tag = static_cast<uint64_t>(chunk) | (uint64_t(last) << 15) | (2ull << 58);
        std::memcpy(packet.data(), &tag, sizeof(tag));
        const size_t offset = static_cast<size_t>(done) * 16u;
        const size_t copy = std::min<size_t>(static_cast<size_t>(chunk) * 16u, bytes - offset);
        std::memcpy(packet.data() + 16u, data + offset, copy);
        gifTransfer(packet.data(), packet.size());
        done += chunk;
    }
}

uint32_t ParallelGsBridge::readTransfer(uint8_t *dst, uint32_t maxBytes)
{
    registerCallingThread();
    const uint32_t qwords = maxBytes / 16u;
    if (qwords == 0u)
        return 0u;
    m_impl->gs.read_transfer_fifo(dst, qwords);
    return qwords * 16u;
}

const uint8_t *ParallelGsBridge::mapVramRead()
{
    registerCallingThread();
    return static_cast<const uint8_t *>(m_impl->gs.map_vram_read(0, 4u * 1024u * 1024u));
}

uint8_t *ParallelGsBridge::mapVramWrite()
{
    registerCallingThread();
    m_impl->vramMappedForWrite = true;
    return static_cast<uint8_t *>(m_impl->gs.map_vram_write(0, 4u * 1024u * 1024u));
}

void ParallelGsBridge::endVramWrite()
{
    registerCallingThread();
    if (m_impl->vramMappedForWrite)
        m_impl->gs.end_vram_write(0, 4u * 1024u * 1024u);
    m_impl->vramMappedForWrite = false;
}

void ParallelGsBridge::flush()
{
    registerCallingThread();
    m_impl->gs.flush();
}

bool ParallelGsBridge::vsync(const GSRegisters &priv, uint32_t field, std::vector<uint8_t> &rgba,
                             uint32_t &width, uint32_t &height,
                             const GSPresentationRequest *request,
                             GSPresentationRequest *presentedRequest)
{
    registerCallingThread();
    auto &gs = m_impl->gs;
    auto &device = m_impl->device;
    gs.flush();
    auto &state = gs.get_priv_register_state();
    assignRaw(state.pmode, priv.pmode);
    // A game that never called SetGsCrt (or a state restored before it ran)
    // still needs a video standard to scan out; NTSC interlaced as the BIOS sets.
    assignRaw(state.smode1, priv.smode1 != 0u ? priv.smode1 : 0x740834504ull);
    assignRaw(state.smode2, priv.smode2);
    assignRaw(state.srfsh, priv.srfsh);
    assignRaw(state.synch1, priv.synch1);
    assignRaw(state.synch2, priv.synch2);
    assignRaw(state.syncv, priv.syncv);
    assignRaw(state.dispfb1, priv.dispfb1);
    assignRaw(state.display1, priv.display1);
    assignRaw(state.dispfb2, priv.dispfb2);
    assignRaw(state.display2, priv.display2);
    assignRaw(state.extbuf, priv.extbuf);
    assignRaw(state.extdata, priv.extdata);
    assignRaw(state.extwrite, priv.extwrite);
    assignRaw(state.bgcolor, priv.bgcolor);

    // PS2X_GPU_VRAM_DUMP_AT=<vsync>: write the 4 MB GPU VRAM (swizzled, as the
    // GS stores it) to gpu-vram-<vsync>.bin for tools/diagnostics/gs_vram_view.py.
    static const long dumpAt = [] {
        const char *v = std::getenv("PS2X_GPU_VRAM_DUMP_AT");
        return v ? std::strtol(v, nullptr, 10) : -1L;
    }();
    if (dumpAt >= 0 && m_impl->vsyncs == static_cast<uint64_t>(dumpAt))
    {
        const void *vram = gs.map_vram_read(0, 4u * 1024u * 1024u);
        const std::string name = "gpu-vram-" + std::to_string(dumpAt) + ".bin";
        if (FILE *f = std::fopen(name.c_str(), "wb"))
        {
            std::fwrite(vram, 1, 4u * 1024u * 1024u, f);
            std::fclose(f);
            std::cerr << "[gs:gpu] VRAM dumped to " << name << std::endl;
        }
    }

    VSyncInfo info = {};
    info.phase = field & 1u;
    info.force_progressive = true;
    info.anti_blur = true;
    info.overscan = false;
    info.crtc_offsets = false;
    info.adapt_to_internal_horizontal_resolution = false;
    info.raw_circuit_scanout = true;
    info.high_resolution_scanout = false;
    info.dst_layout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    info.dst_stage = VK_PIPELINE_STAGE_2_COPY_BIT;
    info.dst_access = VK_ACCESS_2_TRANSFER_READ_BIT;
    ScanoutResult scanout = gs.vsync(info);
    if (scanout.image)
        ++m_impl->scanouts;
    if (++m_impl->vsyncs % 600u == 0u)
        std::cerr << "[gs:gpu] vsyncs=" << m_impl->vsyncs << " scanouts=" << m_impl->scanouts
                  << " transfers=" << m_impl->transfers << " bytes=" << m_impl->transferBytes
                  << " uploads=" << m_impl->uploads << " finish=" << m_impl->finishes
                  << " signal=" << m_impl->signalCount << " label=" << m_impl->labels
                  << " resyncs=" << m_impl->resyncs << std::endl;
    bool ok = false;
    static const bool pipelined = [] {
        const char *value = std::getenv("PS2X_GS_READBACK_SYNC");
        return !(value && *value == '1');
    }();
    auto &current = m_impl->readbacks[m_impl->readbackNext];
    auto &previous = m_impl->readbacks[m_impl->readbackNext ^ 1u];
    Impl::ReadbackFrame *ready = pipelined && previous.pending ? &previous : nullptr;
    if (scanout.image)
    {
        assert(!current.pending);
        current.width = scanout.image->get_width();
        current.height = scanout.image->get_height();
        const VkDeviceSize size = VkDeviceSize(current.width) * current.height * 4u;
        if (!current.buffer || current.capacity < size)
        {
            BufferCreateInfo buffer = {};
            buffer.domain = BufferDomain::CachedHost;
            buffer.size = size;
            buffer.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
            current.buffer = device.create_buffer(buffer);
            current.capacity = size;
        }
        // Retain the image and buffer until their own copy fence completes.
        // The next scanout may have a different size or display source.
        current.image = scanout.image;
        current.request = request ? *request : GSPresentationRequest{};
        if (!request) current.request.vsyncTick = field;
        auto cmd = device.request_command_buffer();
        cmd->copy_image_to_buffer(*current.buffer, *current.image, 0, {0, 0, 0}, {current.width, current.height, 1}, 0, 0,
                                  {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1});
        cmd->barrier(VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT,
                     VK_PIPELINE_STAGE_HOST_BIT, VK_ACCESS_HOST_READ_BIT);
        device.submit(cmd, &current.fence);
        current.pending = true;
        // Bootstrap with the first completed image; thereafter consume the
        // preceding submission while the GPU prepares the current image.
        if (!ready || !pipelined) ready = &current;
    }
    if (ready)
    {
        ready->fence->wait();
        width = ready->width;
        height = ready->height;
        const VkDeviceSize size = VkDeviceSize(width) * height * 4u;
        const auto *pixels = static_cast<const uint8_t *>(
            device.map_host_buffer(*ready->buffer, MEMORY_ACCESS_READ_BIT, 0, size));
        rgba.assign(pixels, pixels + size);
        // The window and the captures expect opaque pixels; GS alpha is 0..0x80.
        for (size_t i = 3; i < rgba.size(); i += 4)
            rgba[i] = 0xFFu;
        device.unmap_host_buffer(*ready->buffer, MEMORY_ACCESS_READ_BIT, 0, size);
        if (presentedRequest) *presentedRequest = ready->request;
        if (ready != &current || !pipelined)
        {
            ready->pending = false;
            ready->fence.reset();
            ready->image.reset();
        }
        ok = true;
    }
    if (scanout.image) m_impl->readbackNext ^= 1u;
    device.next_frame_context();
    return ok;
}

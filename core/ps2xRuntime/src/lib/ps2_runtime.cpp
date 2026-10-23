#include "ps2_runtime.h"
#include "runtime/ps2_save_storage.h"
#include "runtime/ps2_vu1_execution.h"
#include "runtime/ps2_vu_control.h"
#include "runtime/ps2_call_capture_plan.h"
namespace ps2_syscalls { void resetDeci2State(PS2Runtime *runtime); }
#if defined(PS2X_GUEST_PC_PROFILE)
#include "GuestPcProfile.h"
#endif
#include "ps2_log.h"
#include "ps2_stubs.h"
#include "ps2_syscalls.h"
#include "game_overrides.h"
#include "ps2_runtime_macros.h"
#include "runtime/gs/gs_frontend.h"
#include "runtime/ee_scheduler.h"
#include "runtime/ps2_ipu.h"
#include "ThreadNaming.h"
#include "Kernel/Stubs/Audio.h"
#include "Kernel/Stubs/GS.h"
#include "Kernel/Stubs/MPEG.h"
#include "ps2_host_backend.h"
#include "ps2_iop_host.h"
#include "ps2x/iop/iop_subsystem.h"
#include "audio/host_audio_stretch.h"
extern std::atomic<uint64_t> g_ps2DisplayFlips;

uint32_t ps2ReadVuFbrst(const PS2Runtime &runtime, const R5900Context &)
{
    return runtime.cpu().vu0_fbrst;
}

uint32_t ps2ReadVuStatus(const PS2Runtime &runtime, const R5900Context &)
{
    return runtime.cpu().vu0_vpu_stat;
}

void ps2WriteVuFbrst(PS2Runtime &runtime, R5900Context &context, uint32_t value)
{
    auto &hardware = runtime.cpu();
    hardware.vu0_fbrst = value & 0x0C0Cu;
    // The reset action bits do not latch. Reset only the selected unit's
    // status/control byte and VIF wait flag; it is not a cold register reset.
    if (value & 2u) {
        runtime.vu0().controlReset();
        hardware.vu0_vpu_stat &= ~0xFFu;
        hardware.vu0_fbrst &= ~0xFFu;
        runtime.memory().vif0_regs.stat &= ~4u;
    }
    if (value & 0x200u) {
        runtime.vu1().controlReset();
        hardware.vu0_vpu_stat &= ~0xFF00u;
        hardware.vu0_fbrst &= ~0xFF00u;
        runtime.memory().vif1_regs.stat &= ~4u;
    }
    context.vu0_fbrst = hardware.vu0_fbrst;
    context.vu0_vpu_stat = hardware.vu0_vpu_stat;
}

#include <iostream>
#include <iomanip>
#include <stdexcept>
#include <fstream>
#include <algorithm>
#include <array>
#include <cstring>
#include <cstdlib>
#include <limits>
#include <chrono>
#include <cmath>
#include <atomic>
#include <mutex>
#include <charconv>
#include <thread>
#include <unordered_map>
#include <sstream>

namespace ps2_stubs
{
    void resetSifState();
}

#define ELF_MAGIC 0x464C457F // "\x7FELF" in little endian
#define ET_EXEC 2            // Executable file
#define EM_MIPS 8            // MIPS architecture
#define PT_LOAD 1            // Loadable segment

static constexpr int FB_WIDTH = 640;
static constexpr int FB_HEIGHT = 512;
static constexpr int DEFAULT_DISPLAY_HEIGHT = 448;
static constexpr uint32_t DEFAULT_FB_SIZE = FB_WIDTH * FB_HEIGHT * 4;
static constexpr uint32_t DEFAULT_FB_ADDR = (PS2_RAM_SIZE - DEFAULT_FB_SIZE - 0x10000u);
#if defined(PLATFORM_VITA)
static constexpr int HOST_WINDOW_WIDTH = 960;
static constexpr int HOST_WINDOW_HEIGHT = 544;
#else
static constexpr int HOST_WINDOW_WIDTH = FB_WIDTH;
static constexpr int HOST_WINDOW_HEIGHT = DEFAULT_DISPLAY_HEIGHT;
#endif
struct ElfHeader
{
    uint32_t magic;
    uint8_t elf_class;
    uint8_t endianness;
    uint8_t version;
    uint8_t os_abi;
    uint8_t abi_version;
    uint8_t padding[7];
    uint16_t type;
    uint16_t machine;
    uint32_t version2;
    uint32_t entry;
    uint32_t phoff;
    uint32_t shoff;
    uint32_t flags;
    uint16_t ehsize;
    uint16_t phentsize;
    uint16_t phnum;
    uint16_t shentsize;
    uint16_t shnum;
    uint16_t shstrndx;
};

struct ProgramHeader
{
    uint32_t type;
    uint32_t offset;
    uint32_t vaddr;
    uint32_t paddr;
    uint32_t filesz;
    uint32_t memsz;
    uint32_t flags;
    uint32_t align;
};

namespace
{
    constexpr uint32_t kGuestHeapDefaultBase = 0x00100000u;
    constexpr uint32_t kGuestHeapDefaultAlignment = 16u;
    constexpr uint32_t kGuestHeapSafetyPad = 0x1000u;
    constexpr uint32_t kGuestHeapHardLimit = 0x01F00000u;
    // HLE-private pages above the syscall mirrors and below normal EE text.
    // ELF loading and host heap allocation explicitly exclude this window.
    constexpr uint32_t kRuntimeArenaBase = 0x00080000u;
    constexpr uint32_t kRuntimeArenaEnd = 0x00100000u;

    constexpr uint32_t COP0_CAUSE_EXCCODE_MASK = 0x0000007Cu;
    constexpr uint32_t COP0_CAUSE_BD = 0x80000000u;
    constexpr uint32_t COP0_STATUS_EXL = 0x00000002u;
    constexpr uint32_t COP0_STATUS_BEV = 0x00400000u;
    constexpr uint32_t EXCEPTION_VECTOR_GENERAL = 0x80000080u;
    constexpr uint32_t EXCEPTION_VECTOR_TLB_REFILL = 0x80000000u;
    constexpr uint32_t EXCEPTION_VECTOR_BOOT = 0xBFC00200u;

    struct DispatchHistory
    {
        std::array<uint32_t, 64> pcs{};
        uint32_t next = 0u;
        bool wrapped = false;
    };

    thread_local DispatchHistory g_dispatchHistory;

    bool computeFileCrc32(const std::string &path, uint32_t &crcOut)
    {
        std::ifstream file(path, std::ios::binary);
        if (!file.is_open())
        {
            return false;
        }

        static const std::array<uint32_t, 256> table = []
        {
            std::array<uint32_t, 256> values{};
            for (uint32_t i = 0; i < values.size(); ++i)
            {
                uint32_t value = i;
                for (uint32_t bit = 0; bit < 8; ++bit)
                {
                    value = (value & 1u) ? (0xEDB88320u ^ (value >> 1u)) : (value >> 1u);
                }
                values[i] = value;
            }
            return values;
        }();

        uint32_t crc = 0xFFFFFFFFu;
        std::array<uint8_t, 16 * 1024> buffer{};
        while (file.good())
        {
            file.read(reinterpret_cast<char *>(buffer.data()), static_cast<std::streamsize>(buffer.size()));
            const std::streamsize count = file.gcount();
            for (std::streamsize i = 0; i < count; ++i)
            {
                crc = table[(crc ^ buffer[static_cast<size_t>(i)]) & 0xFFu] ^ (crc >> 8u);
            }
        }
        if (file.bad())
        {
            return false;
        }
        crcOut = ~crc;
        return true;
    }

    void pushDispatchPc(uint32_t pc)
    {
        DispatchHistory &h = g_dispatchHistory;
        h.pcs[h.next] = pc;
        h.next = (h.next + 1u) % static_cast<uint32_t>(h.pcs.size());
        if (h.next == 0u)
        {
            h.wrapped = true;
        }
    }

    std::string formatDispatchHistory()
    {
        const DispatchHistory &h = g_dispatchHistory;
        const uint32_t count = h.wrapped ? static_cast<uint32_t>(h.pcs.size()) : h.next;
        if (count == 0u)
        {
            return "(empty)";
        }

        std::ostringstream oss;
        bool first = true;
        for (uint32_t i = 0u; i < count; ++i)
        {
            const uint32_t idx = (h.next + h.pcs.size() - count + i) % static_cast<uint32_t>(h.pcs.size());
            if (!first)
            {
                oss << " -> ";
            }
            first = false;
            oss << "0x" << std::hex << h.pcs[idx];
        }
        return oss.str();
    }

    uint32_t selectExceptionVector(const R5900Context *ctx, bool tlbRefill)
    {
        if (ctx->cop0_status & COP0_STATUS_BEV)
        {
            return EXCEPTION_VECTOR_BOOT;
        }
        return tlbRefill ? EXCEPTION_VECTOR_TLB_REFILL : EXCEPTION_VECTOR_GENERAL;
    }

    void seedVu0IdleSuccess(R5900Context *ctx)
    {
        if (!ctx)
        {
            return;
        }

        ctx->vu0_clip_flags = 0;
        ctx->vu0_clip_flags2 = 0;
        ctx->vu0_mac_flags = 0;
        ctx->vu0_status = 0;
        ctx->vu0_q = 1.0f;
        ctx->vu0_r = _mm_castsi128_ps(_mm_set1_epi32(0x3F800000));
        ctx->vu0_vpu_stat &= ~0xFFu;
        ctx->vu0_vpu_stat2 = 0;
    }

    void copyVu0ContextToState(const R5900Context *ctx, VU1State &state)
    {
        std::memset(&state, 0, sizeof(state));

        for (uint32_t i = 0; i < 32u; ++i)
        {
            _mm_storeu_ps(state.vf[i], ctx->vu0_vf[i]);
        }
        for (uint32_t i = 0; i < 16u; ++i)
        {
            state.vi[i] = static_cast<int16_t>(ctx->vi[i]);
        }

        _mm_storeu_ps(state.acc, ctx->vu0_acc);
        state.q = ctx->vu0_q;
        state.p = ctx->vu0_p;
        state.i = ctx->vu0_i;
        alignas(16) uint32_t rWords[4]{};
        _mm_storeu_si128(reinterpret_cast<__m128i *>(rWords), _mm_castps_si128(ctx->vu0_r));
        state.r = 0x3F800000u | (rWords[0] & 0x007FFFFFu);
        state.pc = ctx->vu0_pc;
        state.mac = ctx->vu0_mac_flags;
        state.clip = ctx->vu0_clip_flags;
        state.status = ctx->vu0_status;
        state.itop = ctx->vu0_itop;
        state.dBitEnabled = (ctx->vu0_fbrst & (1u << 2)) != 0u;
        state.tBitEnabled = (ctx->vu0_fbrst & (1u << 3)) != 0u;

        state.vf[0][0] = 0.0f;
        state.vf[0][1] = 0.0f;
        state.vf[0][2] = 0.0f;
        state.vf[0][3] = 1.0f;
        state.vi[0] = 0;
    }

    void copyVu0StateToContext(const VU1State &state, R5900Context *ctx)
    {
        for (uint32_t i = 0; i < 32u; ++i)
        {
            ctx->vu0_vf[i] = _mm_loadu_ps(state.vf[i]);
        }
        for (uint32_t i = 0; i < 16u; ++i)
        {
            ctx->vi[i] = static_cast<uint16_t>(state.vi[i]);
        }

        ctx->vu0_acc = _mm_loadu_ps(state.acc);
        ctx->vu0_q = state.q;
        ctx->vu0_p = state.p;
        ctx->vu0_i = state.i;
        ctx->vu0_r = _mm_castsi128_ps(_mm_set1_epi32(static_cast<int32_t>(state.r)));
        ctx->vu0_mac_flags = state.mac;
        ctx->vu0_clip_flags = state.clip;
        ctx->vu0_clip_flags2 = state.clip;
        ctx->vu0_status = static_cast<uint16_t>(state.status);
        ctx->vu0_itop = state.itop;
        ctx->vu0_pc = state.pc;
        ctx->vu0_tpc = state.pc;
        ctx->vu0_vpu_stat = (ctx->vu0_vpu_stat & ~0xFFu) | (state.stoppedByD ? (1u << 1) : 0u) | (state.stoppedByT ? (1u << 2) : 0u);
        ctx->vu0_vpu_stat2 = 0;

        ctx->vu0_vf[0] = _mm_set_ps(1.0f, 0.0f, 0.0f, 0.0f);
        ctx->vi[0] = 0;
    }

    void raiseCop0Exception(R5900Context *ctx, uint32_t exceptionCode, bool tlbRefill = false)
    {
        if (ctx->in_delay_slot)
        {
            ctx->cop0_epc = ctx->branch_pc;
            ctx->cop0_cause = (ctx->cop0_cause & ~COP0_CAUSE_EXCCODE_MASK) |
                              ((exceptionCode << 2) & COP0_CAUSE_EXCCODE_MASK) |
                              COP0_CAUSE_BD;
        }
        else
        {
            ctx->cop0_epc = ctx->pc;
            ctx->cop0_cause = (ctx->cop0_cause & ~(COP0_CAUSE_EXCCODE_MASK | COP0_CAUSE_BD)) |
                              ((exceptionCode << 2) & COP0_CAUSE_EXCCODE_MASK);
        }

        ctx->cop0_status |= COP0_STATUS_EXL;
        ctx->pc = selectExceptionVector(ctx, tlbRefill);
        ctx->in_delay_slot = false;
    }

    std::filesystem::path normalizeAbsolutePath(const std::filesystem::path &path)
    {
        if (path.empty())
        {
            return {};
        }

#if defined(PLATFORM_VITA)
        const std::string generic = path.generic_string();
        const std::size_t colon = generic.find(':');
        if (colon != std::string::npos && colon != 0u)
        {
            const std::size_t slash = generic.find_first_of("/\\");
            if (slash == std::string::npos || colon < slash)
            {
                return path.lexically_normal();
            }
        }
#endif

        std::error_code ec;
        const std::filesystem::path absolute = std::filesystem::absolute(path, ec);
        if (ec)
        {
            return path.lexically_normal();
        }
        return absolute.lexically_normal();
    }

    PS2Runtime::IoPaths &runtimeIoPaths()
    {
        static PS2Runtime::IoPaths paths = []()
        {
            PS2Runtime::IoPaths defaults;
            std::error_code ec;
            const std::filesystem::path cwd = std::filesystem::current_path(ec);
            defaults.elfDirectory = ec ? std::filesystem::path(".") : cwd.lexically_normal();
            defaults.hostRoot = defaults.elfDirectory;
            defaults.cdRoot = defaults.elfDirectory;
            defaults.mcRoot = ps2_saves::fileCardRoot(defaults.elfDirectory);
            return defaults;
        }();

        return paths;
    }

    std::string readGuestPrintableString(const uint8_t *rdram, uint32_t addr, size_t maxLen)
    {
        std::string out;
        if (!rdram || maxLen == 0)
        {
            return out;
        }

        out.reserve(std::min<size_t>(maxLen, 64));
        for (size_t i = 0; i < maxLen; ++i)
        {
            const char ch = static_cast<char>(rdram[(addr + static_cast<uint32_t>(i)) & PS2_RAM_MASK]);
            if (ch == '\0')
            {
                break;
            }
            if (ch >= 0x20 && ch < 0x7F)
            {
                out.push_back(ch);
            }
            else
            {
                out.push_back('.');
            }
        }
        return out;
    }
}

static void UploadFrame(Texture2D &tex, PS2Runtime *rt, uint32_t &outWidth, uint32_t &outHeight)
{
    static uint64_t s_lastPresentationTick = std::numeric_limits<uint64_t>::max();
    static uint32_t s_lastDisplayFbp = std::numeric_limits<uint32_t>::max();
    static uint32_t s_lastSourceFbp = std::numeric_limits<uint32_t>::max();
    static bool s_lastPreferred = false;
    static uint32_t s_lastWidth = 0u;
    static uint32_t s_lastHeight = 0u;
    static bool s_hasUploadedFrame = false;
    static std::vector<uint8_t> s_scratch;
    static std::vector<uint8_t> s_uploadBuffer(DEFAULT_FB_SIZE, 0u);

    // The EE executor publishes completed fields at VBlank. The host must
    // never sample live display registers/VRAM in the middle of guest drawing.
    const uint64_t currentTick = rt->gs().getDebugSnapshot().hostPresentationRequest.vsyncTick;
    if (s_hasUploadedFrame && currentTick == s_lastPresentationTick)
    {
        outWidth = (s_lastWidth != 0u) ? s_lastWidth : FB_WIDTH;
        outHeight = (s_lastHeight != 0u) ? s_lastHeight : DEFAULT_DISPLAY_HEIGHT;
        return;
    }
    s_lastPresentationTick = currentTick;

    s_scratch.clear();
    uint32_t width = 0u;
    uint32_t height = 0u;
    uint32_t displayFbp = 0u;
    uint32_t sourceFbp = 0u;
    bool usedPreferredDisplaySource = false;
    if (!rt->gs().copyLatchedHostPresentationFrame(s_scratch,
                                                   width,
                                                   height,
                                                   &displayFbp,
                                                   &sourceFbp,
                                                   &usedPreferredDisplaySource))
    {
        Image blank = GenImageColor(FB_WIDTH, FB_HEIGHT, BLACK);
        UpdateTexture(tex, blank.data);
        UnloadImage(blank);
        outWidth = FB_WIDTH;
        outHeight = DEFAULT_DISPLAY_HEIGHT;
        s_lastWidth = outWidth;
        s_lastHeight = outHeight;
        s_hasUploadedFrame = true;
        return;
    }

    PS2_IF_AGRESSIVE_LOGS({
        static uint32_t s_uploadDebugCount = 0u;
        if (s_uploadDebugCount < 128u ||
            displayFbp != s_lastDisplayFbp ||
            sourceFbp != s_lastSourceFbp ||
            usedPreferredDisplaySource != s_lastPreferred ||
            width != s_lastWidth ||
            height != s_lastHeight)
        {
            std::cout << "[frame:upload] idx=" << s_uploadDebugCount
                      << " tick=" << currentTick
                      << " displayFbp=" << displayFbp
                      << " sourceFbp=" << sourceFbp
                      << " size=" << width << "x" << height
                      << " preferred=" << static_cast<uint32_t>(usedPreferredDisplaySource ? 1u : 0u)
                      << std::endl;
        }
        ++s_uploadDebugCount;
    });
    s_lastDisplayFbp = displayFbp;
    s_lastSourceFbp = sourceFbp;
    s_lastPreferred = usedPreferredDisplaySource;
    s_lastWidth = width;
    s_lastHeight = height;

    std::fill(s_uploadBuffer.begin(), s_uploadBuffer.end(), 0u);
    if (!s_scratch.empty() && width != 0u && height != 0u)
    {
        const uint32_t copyWidth = std::min<uint32_t>(width, FB_WIDTH);
        const uint32_t copyHeight = std::min<uint32_t>(height, FB_HEIGHT);
        const size_t srcRowBytes = static_cast<size_t>(width) * 4u;
        const size_t dstRowBytes = static_cast<size_t>(FB_WIDTH) * 4u;
        const size_t copyRowBytes = static_cast<size_t>(copyWidth) * 4u;
        for (uint32_t y = 0; y < copyHeight; ++y)
        {
            const size_t srcOffset = static_cast<size_t>(y) * srcRowBytes;
            const size_t dstOffset = static_cast<size_t>(y) * dstRowBytes;
            if (srcOffset + copyRowBytes > s_scratch.size() ||
                dstOffset + copyRowBytes > s_uploadBuffer.size())
            {
                break;
            }
            std::memcpy(s_uploadBuffer.data() + dstOffset, s_scratch.data() + srcOffset, copyRowBytes);
        }
    }

    UpdateTexture(tex, s_uploadBuffer.data());
    outWidth = width;
    outHeight = height;
    s_hasUploadedFrame = true;
}

namespace
{
#if !defined(PLATFORM_VITA)
    // Host output of the native SPU2 (kzspu2 mixes 48 kHz stereo into a
    // ring buffer). raylib pulls it from its audio thread; the lock keeps the
    // callback away from an IOP subsystem that is being torn down.
    std::mutex g_hostAudioMutex;
    ps2x::iop::IopSubsystem *g_hostAudioIop = nullptr;
    AudioStream g_hostAudioStream{};
    bool g_hostAudioStreamLoaded = false;

    // PS2X_AUDIO_WAV=<prefix>: records <prefix>-spu2.wav (raw SPU2 output) and
    // <prefix>-out.wav (what the speakers get) for offline analysis.
    class WavRecorder
    {
    public:
        explicit WavRecorder(const std::string &path) : m_file(std::fopen(path.c_str(), "wb"))
        {
            if (m_file)
                writeHeader();
        }
        ~WavRecorder()
        {
            if (!m_file)
                return;
            writeHeader();
            std::fclose(m_file);
        }
        void write(const int16_t *stereo, uint32_t frames)
        {
            if (!m_file || !frames)
                return;
            std::fwrite(stereo, sizeof(int16_t) * 2u, frames, m_file);
            m_frames += frames;
            if ((m_frames & 0xFFFFu) < frames) // keep the header valid if the process is killed
                writeHeader();
        }

    private:
        void writeHeader()
        {
            const long position = std::ftell(m_file);
            const uint32_t data = static_cast<uint32_t>(m_frames * 4u);
            const uint32_t riff = 36u + data, fmt = 16u, rate = 48000u, byteRate = rate * 4u;
            const uint16_t pcm = 1u, channels = 2u, align = 4u, bits = 16u;
            std::fseek(m_file, 0, SEEK_SET);
            std::fwrite("RIFF", 1, 4, m_file); std::fwrite(&riff, 4, 1, m_file);
            std::fwrite("WAVEfmt ", 1, 8, m_file); std::fwrite(&fmt, 4, 1, m_file);
            std::fwrite(&pcm, 2, 1, m_file); std::fwrite(&channels, 2, 1, m_file);
            std::fwrite(&rate, 4, 1, m_file); std::fwrite(&byteRate, 4, 1, m_file);
            std::fwrite(&align, 2, 1, m_file); std::fwrite(&bits, 2, 1, m_file);
            std::fwrite("data", 1, 4, m_file); std::fwrite(&data, 4, 1, m_file);
            std::fseek(m_file, position > 44 ? position : 44, SEEK_SET);
        }
        std::FILE *m_file = nullptr;
        uint64_t m_frames = 0;
    };

    void hostAudioCallback(void *buffer, unsigned int frames)
    {
        static HostAudioSoundTouch stretcher;
        static const char *wavPrefix = std::getenv("PS2X_AUDIO_WAV");
        static std::unique_ptr<WavRecorder> rawWav =
            wavPrefix && *wavPrefix ? std::make_unique<WavRecorder>(std::string(wavPrefix) + "-spu2.wav") : nullptr;
        static std::unique_ptr<WavRecorder> outWav =
            wavPrefix && *wavPrefix ? std::make_unique<WavRecorder>(std::string(wavPrefix) + "-out.wav") : nullptr;
        auto *out = static_cast<int16_t *>(buffer);
        {
            std::lock_guard<std::mutex> lock(g_hostAudioMutex);
            if (g_hostAudioIop)
            {
                int16_t chunk[1024 * 2];
                for (;;)
                {
                    const uint32_t got = g_hostAudioIop->readAudio(chunk, 1024u);
                    stretcher.push(chunk, got);
                    if (rawWav)
                        rawWav->write(chunk, got);
                    if (got < 1024u)
                        break;
                }
            }
        }
        const uint32_t copied = stretcher.pull(out, frames);
        if (outWav)
            outWav->write(out, frames);
        // Missing source frames remain counted even when the stretch adapter
        // expands a partial block or fades a stopped producer to silence.
        static uint64_t requested = 0, delivered = 0, reported = 0;
        static int peak = 0;
        requested += frames;
        delivered += copied;
        for (uint32_t i = 0; i < frames * 2u; ++i)
            peak = std::max(peak, std::abs(static_cast<int>(out[i])));
        if (requested - reported >= 48000u * 5u)
        {
            std::fprintf(stderr, "[audio] requested=%llu delivered=%llu underrun=%llu tempo=%g peak=%d\n",
                         static_cast<unsigned long long>(requested), static_cast<unsigned long long>(delivered),
                         static_cast<unsigned long long>(requested - delivered), stretcher.tempo(), peak);
            reported = requested;
            peak = 0;
        }
    }

    void startHostAudio(ps2x::iop::IopSubsystem *iop)
    {
        if (g_hostAudioStreamLoaded || !iop || !IsAudioDeviceReady())
            return;
        if (const char *mute = std::getenv("PS2X_AUDIO_MUTE"); mute && *mute && *mute != '0')
            return;
        {
            std::lock_guard<std::mutex> lock(g_hostAudioMutex);
            g_hostAudioIop = iop;
        }
        SetAudioStreamBufferSizeDefault(1024);
        g_hostAudioStream = LoadAudioStream(48000u, 16u, 2u);
        if (!IsAudioStreamValid(g_hostAudioStream))
        {
            std::cerr << "[audio] host stream unavailable" << std::endl;
            return;
        }
        SetAudioStreamCallback(g_hostAudioStream, hostAudioCallback);
        PlayAudioStream(g_hostAudioStream);
        g_hostAudioStreamLoaded = true;
        std::cerr << "[audio] SPU2 output 48000 Hz stereo (PS2X_AUDIO_MUTE=1 disables)" << std::endl;
    }

    void stopHostAudio()
    {
        {
            std::lock_guard<std::mutex> lock(g_hostAudioMutex);
            g_hostAudioIop = nullptr;
        }
        if (g_hostAudioStreamLoaded)
        {
            StopAudioStream(g_hostAudioStream);
            UnloadAudioStream(g_hostAudioStream);
            g_hostAudioStreamLoaded = false;
        }
    }
#endif
}


PS2Runtime::PS2Runtime()
{
    m_iopHost = std::make_unique<PS2IopHostAdapter>(*this);
    m_iopSubsystem = std::make_unique<ps2x::iop::IopSubsystem>(*m_iopHost);

    m_eeScheduler = std::make_unique<EeScheduler>(*this);

    // Assign rather than memset: R5900Context's constructor zeroes itself and
    // then applies the COP0 reset values, which a memset here would discard.
    m_cpuContext = R5900Context{};

    // R0 is always zero in MIPS
    m_cpuContext.r[0] = _mm_set1_epi32(0);
    m_cpuContext.vu0_vf[0] = _mm_set_ps(1.0f, 0.0f, 0.0f, 0.0f);
    m_cpuContext.vu0_q = 1.0f;
    m_cpuContext.vu0_r = _mm_castsi128_ps(_mm_set1_epi32(0x3F800000));

    // Stack pointer (SP) and global pointer (GP) will be set by the loaded ELF

    m_loadedModules.clear();
    m_guestHeapBlocks.clear();
    m_guestHeapBase = kGuestHeapDefaultBase;
    m_guestHeapEnd = kGuestHeapDefaultBase;
    m_guestHeapLimit = std::min(kGuestHeapHardLimit, PS2_RAM_SIZE);
    m_guestHeapSuggestedBase = kGuestHeapDefaultBase;
    m_guestHeapConfigured = false;
    m_asyncCallbackStackFloor = kRuntimeArenaBase;
    m_asyncCallbackStackTop = kRuntimeArenaEnd;
    m_nativeRpcScratch = 0u;
}

void PS2Runtime::setDebugUiCallbacks(DebugUiCallback initCallback,
                                     DebugUiCallback drawCallback,
                                     DebugUiCallback shutdownCallback,
                                     void *userData)
{
    if (m_debugUiInitialized && m_debugUiShutdownCallback)
    {
        m_debugUiShutdownCallback(*this, m_debugUiUserData);
        m_debugUiInitialized = false;
    }

    m_debugUiInitCallback = initCallback;
    m_debugUiDrawCallback = drawCallback;
    m_debugUiShutdownCallback = shutdownCallback;
    m_debugUiUserData = userData;
}

PS2Runtime::~PS2Runtime()
{
    ps2_syscalls::resetDeci2State(this);
    try
    {
        requestStop();
#if !defined(PLATFORM_VITA)
        stopHostAudio();
#endif
        m_iopSubsystem.reset();
        m_iopHost.reset();
#if defined(PLATFORM_VITA)
        m_audioBackend.stopAll();
        m_audioBackend.setAudioReady(false);
#else
        if (IsAudioDeviceReady())
        {
            CloseAudioDevice();
            m_audioBackend.setAudioReady(false);
        }
#endif
        if (m_debugUiInitialized && m_debugUiShutdownCallback)
        {
            m_debugUiShutdownCallback(*this, m_debugUiUserData);
            m_debugUiInitialized = false;
        }

        if (IsWindowReady())
        {
            CloseWindow();
        }

        m_loadedModules.clear();
    }
    catch (const std::exception &e)
    {
        std::cerr << "[~PS2Runtime] cleanup exception: " << e.what() << std::endl;
    }
    catch (...)
    {
        std::cerr << "[~PS2Runtime] cleanup exception: unknown" << std::endl;
    }
}

ps2x::iop::ModuleLoadResult PS2Runtime::loadIopModule(std::string_view path, const void *arguments, uint32_t argumentSize)
{
    auto scope = m_iopHost->enterCall(nullptr, m_memory.getRDRAM());
    return m_iopSubsystem->loadModule(path, arguments, argumentSize);
}

ps2x::iop::ModuleLoadResult PS2Runtime::loadIopModuleBuffer(uint32_t guestAddress, const void *arguments, uint32_t argumentSize)
{
    auto scope = m_iopHost->enterCall(nullptr, m_memory.getRDRAM());
    return m_iopSubsystem->loadModuleBuffer(guestAddress, arguments, argumentSize);
}

bool PS2Runtime::stopIopModule(int32_t moduleId, int32_t *result)
{
    auto scope = m_iopHost->enterCall(nullptr, m_memory.getRDRAM());
    return m_iopSubsystem->stopModule(moduleId, result);
}

ps2x::iop::RpcAbi PS2Runtime::selectIopRpcAbi(const ps2x::iop::RpcAbiRequest &request) const
{
    return m_iopSubsystem->selectRpcAbi(request);
}

bool PS2Runtime::canBindIopRpc(uint32_t sid) const noexcept
{
    return m_iopSubsystem->canBindRpc(sid);
}

ps2x::iop::RpcResult PS2Runtime::handleIopRpc(uint8_t *rdram, R5900Context *ctx, ps2x::iop::RpcRequest request)
{
    auto scope = m_iopHost->enterCall(ctx, rdram);
    request.callToken = scope.token();
    return m_iopSubsystem->handleRpc(request);
}

void PS2Runtime::notifyIopSifTransfer(uint8_t *rdram, const ps2x::iop::SifTransfer &transfer)
{
    auto scope = m_iopHost->enterCall(nullptr, rdram);
    m_iopSubsystem->onSifTransfer(transfer);
}

void PS2Runtime::advanceIopEeCycles(uint64_t eeCycles) noexcept
{
    m_iopSubsystem->runEeCycles(eeCycles);
}

void PS2Runtime::resetIop()
{
    m_iopSubsystem->reset();
}

ps2x::iop::DebugSnapshot PS2Runtime::iopDebugSnapshot() const
{
    return m_iopSubsystem->debugSnapshot();
}

uint32_t PS2Runtime::allocateIopMemory(uint32_t size, uint32_t alignment)
{
    return m_iopSubsystem ? m_iopSubsystem->allocateMemory(size, alignment) : 0u;
}

bool PS2Runtime::freeIopMemory(uint32_t address)
{
    return m_iopSubsystem && m_iopSubsystem->freeMemory(address);
}

bool PS2Runtime::readIopMemory(uint32_t address, void *destination, size_t size) const
{
    return m_iopSubsystem && m_iopSubsystem->readMemory(address, destination, size);
}

bool PS2Runtime::writeIopMemory(uint32_t address, const void *source, size_t size)
{
    return m_iopSubsystem && m_iopSubsystem->writeMemory(address, source, size);
}

bool PS2Runtime::zeroIopMemory(uint32_t address, size_t size)
{
    return m_iopSubsystem && m_iopSubsystem->zeroMemory(address, size);
}

bool PS2Runtime::isIopMemoryRange(uint32_t address, size_t size) const
{
    return m_iopSubsystem && m_iopSubsystem->isMemoryRange(address, size);
}

namespace
{
    void traceVu1Mscal(uint32_t startPc, uint64_t vu1Cycles);
}


namespace
{
    // PS2X_VU1_SNAPSHOT=<dir> (+ PS2X_VU1_SNAPSHOT_FROM=<vsync>): before each
    // VU1 MSCAL write [header][VU1State][code][data] for tools/vu1 bench and
    // compiler verification; at most 400 files. Game data: never publish.
    struct Vu1SnapshotHeader
    {
        uint32_t magic = 0x53315556u; // "VU1S"
        uint32_t version = 1u;
        uint32_t startPc = 0, top = 0, itop = 0;
        uint32_t stateBytes = sizeof(VU1State), codeBytes = 0, dataBytes = 0;
        uint64_t vsync = 0;
    };

    void writeVu1Snapshot(const VU1State &state, const uint8_t *code, uint32_t codeBytes,
                          const uint8_t *data, uint32_t dataBytes, uint32_t startPc,
                          uint32_t top, uint32_t itop, uint64_t vsync)
    {
        static const char *const dir = std::getenv("PS2X_VU1_SNAPSHOT");
        if (!dir || !*dir)
            return;
        static const uint64_t from = [] {
            const char *v = std::getenv("PS2X_VU1_SNAPSHOT_FROM");
            return v ? std::strtoull(v, nullptr, 0) : 0ull;
        }();
        static uint32_t written = 0;
        if (vsync < from || written >= 400u || !code || !data)
            return;
        char name[64];
        std::snprintf(name, sizeof(name), "/vu1snap_%05u.bin", written);
        if (std::FILE *f = std::fopen((std::string(dir) + name).c_str(), "wb"))
        {
            Vu1SnapshotHeader header;
            header.startPc = startPc;
            header.top = top;
            header.itop = itop;
            header.codeBytes = codeBytes;
            header.dataBytes = dataBytes;
            header.vsync = vsync;
            std::fwrite(&header, sizeof(header), 1, f);
            std::fwrite(&state, sizeof(state), 1, f);
            std::fwrite(code, 1, codeBytes, f);
            std::fwrite(data, 1, dataBytes, f);
            std::fclose(f);
            ++written;
        }
    }
}

bool PS2Runtime::syncCoreSubsystems()
{
    uint8_t *const rdram = m_memory.getRDRAM();
    uint8_t *const gsVram = m_memory.getGSVRAM();
    if (!rdram || !gsVram)
    {
        return false;
    }

    if (m_boundRdram == rdram && m_boundGSVram == gsVram)
    {
        return true;
    }

    m_gs.init(gsVram, static_cast<uint32_t>(PS2_GS_VRAM_SIZE), &m_memory.gs());
    m_gifArbiter.setProcessPathPacketFn([this](GifPathId pathId, const uint8_t *data, uint32_t size)
                                    {
                                        // Opt-in bounded raw packet evidence. The published
                                        // PC is a sampled location, not the DMA issuing PC.
                                        static const bool trace = std::getenv("PS2X_TRACE_GIF") != nullptr;
                                        static std::atomic<uint32_t> count{0u};
                                        if (trace)
                                        {
                                            const uint32_t index = count.fetch_add(1u, std::memory_order_relaxed);
                                            if (index < 512u)
                                            {
                                                std::ostringstream line;
                                                line << "[GIF packet] index=" << index << " size=" << size
                                                     << " published_pc=0x" << std::hex << m_debugPc.load(std::memory_order_relaxed)
                                                     << " prefix=";
                                                // Capture whole startup command packets while
                                                // bounding stderr to 4 MiB of hex at most.
                                                for (uint32_t i = 0; data && i < std::min(size, 4096u); ++i)
                                                    line << std::setw(2) << std::setfill('0') << static_cast<unsigned>(data[i]);
                                                std::cerr << line.str() << '\n';
                                            }
                                            else if (index == 512u)
                                                std::cerr << "[GIF packet trace capped] limit=512\n";
                                        }
                                        m_gs.processGIFPacket(data, size, pathId);
                                    });
    m_memory.setGifArbiter(&m_gifArbiter);
    // This shell still runs synchronously on EE. The executor receives only
    // captured control and returns a value: it never reaches into the scheduler
    // or mutates an EE context. Async wiring must enqueue that executor and
    // retire its completion on EE, rather than moving this shell to the worker.
    const auto executeOnEe = [this](PS2Vu1Command command, uint32_t startPC, uint32_t top, uint32_t itop) {
        R5900Context *cpuContext = m_eeScheduler ? m_eeScheduler->currentContext() : nullptr;
        if (!cpuContext) cpuContext = &m_cpuContext;
        const PS2Vu1RunControl control{m_cpuContext.vu0_fbrst,
                                      m_eeScheduler ? m_eeScheduler->currentVSyncTick() : 0u};
        const auto completion = executePS2Vu1Command(m_vu1, m_memory, m_gs, command, control,
                                                     startPC, top, itop, 65536,
            [this, startPC, top, itop](const VU1State &state, const PS2Vu1RunControl &captured) {
                traceVu1Mscal(startPC, state.cycles);
                writeVu1Snapshot(state, m_memory.getVU1Code(), PS2_VU1_CODE_SIZE,
                                 m_memory.getVU1Data(), PS2_VU1_DATA_SIZE, startPC, top, itop, captured.eeVsync);
            });
        m_cpuContext.vu0_vpu_stat = completion.mergeStatus(m_cpuContext.vu0_vpu_stat);
        cpuContext->vu0_vpu_stat = m_cpuContext.vu0_vpu_stat;
        cpuContext->vu0_fbrst = m_cpuContext.vu0_fbrst;
        // Publish after status retirement. postEvent owns the request and
        // dispatches its guest handler on EE at the next safe checkpoint;
        // it never retains this context or enters guest code from VIF/VU1.
        if (completion.requestsInterrupt())
            m_eeScheduler->postEvent({EeEventType::Intc, 7u, 0u});
    };
    m_memory.setVu1MscalCallback([executeOnEe](uint32_t startPC, uint32_t top, uint32_t itop) {
        executeOnEe(PS2Vu1Command::Start, startPC, top, itop);
    });
    m_memory.setVu1MscntCallback([executeOnEe](uint32_t top, uint32_t itop) {
        executeOnEe(PS2Vu1Command::Continue, 0, top, itop);
    });
    resetIop();
    m_vu0.reset();
    m_vu1.reset();

    m_boundRdram = rdram;
    m_boundGSVram = gsVram;
    return true;
}

bool PS2Runtime::initialize(const char *title)
{
    try
    {
        if (!m_memory.initialize())
        {
            std::cerr << "Failed to initialize PS2 memory" << std::endl;
            return false;
        }

        if (!syncCoreSubsystems())
        {
            std::cerr << "Failed to bind runtime core subsystems" << std::endl;
            return false;
        }
#if defined(PLATFORM_VITA)
        InitWindow(HOST_WINDOW_WIDTH, HOST_WINDOW_HEIGHT, title); // raylib vita does not support audio
#else
        // EE and audio run on separate threads. Keep polling host input and
        // advancing presentation even when minimized; otherwise raylib waits
        // inside EndDrawing while the game keeps running with stale input.
        SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_WINDOW_ALWAYS_RUN);
        InitWindow(HOST_WINDOW_WIDTH, HOST_WINDOW_HEIGHT, title);
        if (const char *replay = std::getenv("PS2X_NATIVE_PAD_REPLAY"); replay && *replay)
        {
            const std::string replayTitle = std::string(title) + " | INPUT REPLAY - physical controller disabled";
            SetWindowTitle(replayTitle.c_str());
        }
        InitAudioDevice();
        m_audioBackend.setAudioReady(IsAudioDeviceReady());
        startHostAudio(m_iopSubsystem.get());
#endif
        SetTargetFPS(60);
        m_padBackend.initializeHostMappings();
        if (m_debugUiInitCallback)
        {
            m_debugUiInitCallback(*this, m_debugUiUserData);
            m_debugUiInitialized = true;
        }

#if !defined(PLATFORM_VITA)
        // raylib clears FLAG_WINDOW_MINIMIZED during InitWindow. Request it
        // after host initialization so the regression run is actually iconic.
        if (const char *minimized = std::getenv("PS2X_START_MINIMIZED"); minimized && *minimized == '1')
            MinimizeWindow();
#endif
        return true;
    }
    catch (const std::exception &e)
    {
        std::cerr << "Failed to initialize PS2 runtime: " << e.what() << std::endl;
    }
    catch (...)
    {
        std::cerr << "Failed to initialize PS2 runtime: unknown exception" << std::endl;
    }

    return false;
}

bool PS2Runtime::loadELF(const std::string &elfPath)
{
    ps2_syscalls::resetDeci2State(this);
    configureIoPathsFromElf(elfPath);

    std::ifstream file(elfPath, std::ios::binary);
    if (!file)
    {
        std::cerr << "Failed to open ELF file: " << elfPath << std::endl;
        return false;
    }

    file.seekg(0, std::ios::end);
    const std::streamoff fileSize = file.tellg();
    if (fileSize < static_cast<std::streamoff>(sizeof(ElfHeader)))
    {
        std::cerr << "ELF file is too small: " << elfPath << std::endl;
        return false;
    }
    file.seekg(0, std::ios::beg);

    ElfHeader header{};
    if (!file.read(reinterpret_cast<char *>(&header), sizeof(header)))
    {
        std::cerr << "Failed to read ELF header from: " << elfPath << std::endl;
        return false;
    }

    if (header.magic != ELF_MAGIC)
    {
        std::cerr << "Invalid ELF magic number" << std::endl;
        return false;
    }

    if (header.elf_class != 1u || header.endianness != 1u)
    {
        std::cerr << "Unsupported ELF format (expected 32-bit little-endian)." << std::endl;
        return false;
    }

    if (header.machine != EM_MIPS || header.type != ET_EXEC)
    {
        std::cerr << "Not a MIPS executable ELF file" << std::endl;
        return false;
    }

    if (header.phnum != 0u && header.phentsize < sizeof(ProgramHeader))
    {
        std::cerr << "Unsupported ELF program-header entry size: " << header.phentsize << std::endl;
        return false;
    }

    const uint64_t programHeaderTableEnd =
        static_cast<uint64_t>(header.phoff) +
        static_cast<uint64_t>(header.phnum) * static_cast<uint64_t>(header.phentsize);
    if (programHeaderTableEnd > static_cast<uint64_t>(fileSize))
    {
        std::cerr << "ELF program-header table is out of range." << std::endl;
        return false;
    }

    clearNativeModules();
    m_cpuContext.pc = header.entry;
    m_debugPc.store(m_cpuContext.pc, std::memory_order_relaxed);

    uint32_t maxLoadedRdramEnd = kGuestHeapDefaultBase;
    uint32_t moduleBase = std::numeric_limits<uint32_t>::max();
    uint32_t moduleEnd = 0u;
    bool loadedAnySegment = false;

    for (uint16_t i = 0; i < header.phnum; i++)
    {
        const uint64_t phOffset =
            static_cast<uint64_t>(header.phoff) +
            static_cast<uint64_t>(i) * static_cast<uint64_t>(header.phentsize);
        if (phOffset + sizeof(ProgramHeader) > static_cast<uint64_t>(fileSize))
        {
            std::cerr << "ELF program header " << i << " is out of range." << std::endl;
            return false;
        }

        ProgramHeader ph{};
        file.seekg(static_cast<std::streamoff>(phOffset), std::ios::beg);
        if (!file.read(reinterpret_cast<char *>(&ph), sizeof(ph)))
        {
            std::cerr << "Failed to read ELF program header " << i << std::endl;
            return false;
        }

        if (ph.type != PT_LOAD || ph.memsz == 0u)
        {
            continue;
        }

        if (ph.filesz > ph.memsz)
        {
            std::cerr << "ELF segment " << i << " has filesz > memsz." << std::endl;
            return false;
        }

        const uint64_t segmentFileEnd = static_cast<uint64_t>(ph.offset) + static_cast<uint64_t>(ph.filesz);
        if (segmentFileEnd > static_cast<uint64_t>(fileSize))
        {
            std::cerr << "ELF segment " << i << " exceeds file bounds." << std::endl;
            return false;
        }

        const bool scratch =
            ph.vaddr >= PS2_SCRATCHPAD_BASE &&
            ph.vaddr < (PS2_SCRATCHPAD_BASE + PS2_SCRATCHPAD_SIZE);

        uint32_t physAddr = 0u;
        try
        {
            physAddr = m_memory.translateAddress(ph.vaddr);
        }
        catch (const std::exception &e)
        {
            std::cerr << "Failed to translate ELF segment " << i
                      << " virtual address 0x" << std::hex << ph.vaddr
                      << std::dec << ": " << e.what() << std::endl;
            return false;
        }
        const uint64_t regionSize = scratch ? static_cast<uint64_t>(PS2_SCRATCHPAD_SIZE)
                                            : static_cast<uint64_t>(PS2_RAM_SIZE);
        const uint64_t segmentMemEnd = static_cast<uint64_t>(physAddr) + static_cast<uint64_t>(ph.memsz);
        if (segmentMemEnd > regionSize)
        {
            std::cerr << "ELF segment " << i << " exceeds "
                      << (scratch ? "scratchpad" : "RDRAM")
                      << " bounds (vaddr=0x" << std::hex << ph.vaddr
                      << " memsz=0x" << ph.memsz << std::dec << ")." << std::endl;
            return false;
        }

        if (!scratch && physAddr < kRuntimeArenaEnd && segmentMemEnd > kRuntimeArenaBase)
        {
            std::cerr << "ELF segment overlaps the HLE-private runtime arena." << std::endl;
            return false;
        }

        uint8_t *destBase = scratch ? m_memory.getScratchpad() : m_memory.getRDRAM();
        if (!destBase)
        {
            std::cerr << "ELF segment " << i << " has no destination memory backing." << std::endl;
            return false;
        }

        uint8_t *dest = destBase + physAddr;
        if (ph.filesz > 0u)
        {
            file.seekg(static_cast<std::streamoff>(ph.offset), std::ios::beg);
            if (!file.read(reinterpret_cast<char *>(dest), ph.filesz))
            {
                std::cerr << "Failed to read ELF segment " << i << " payload." << std::endl;
                return false;
            }
        }

        if (ph.memsz > ph.filesz)
        {
            std::memset(dest + ph.filesz, 0, ph.memsz - ph.filesz);
        }

        RUNTIME_LOG("Loading segment: 0x" << std::hex << ph.vaddr
                                          << " - 0x" << (static_cast<uint64_t>(ph.vaddr) + static_cast<uint64_t>(ph.memsz))
                                          << " (filesz: 0x" << ph.filesz
                                          << ", memsz: 0x" << ph.memsz << ")"
                                          << std::dec << std::endl);

        if (!scratch)
        {
            maxLoadedRdramEnd = std::max(maxLoadedRdramEnd, static_cast<uint32_t>(segmentMemEnd));
        }

        if (ph.flags & 0x1u) // PF_X
        {
            const uint64_t execEnd = static_cast<uint64_t>(ph.vaddr) + static_cast<uint64_t>(ph.filesz);
            if (execEnd <= std::numeric_limits<uint32_t>::max())
            {
                m_memory.registerCodeRegion(ph.vaddr, static_cast<uint32_t>(execEnd));
            }
        }

        loadedAnySegment = true;
        moduleBase = std::min(moduleBase, ph.vaddr);
        const uint64_t segmentVirtualEnd = static_cast<uint64_t>(ph.vaddr) + static_cast<uint64_t>(ph.memsz);
        const uint32_t clampedVirtualEnd =
            (segmentVirtualEnd > std::numeric_limits<uint32_t>::max())
                ? std::numeric_limits<uint32_t>::max()
                : static_cast<uint32_t>(segmentVirtualEnd);
        moduleEnd = std::max(moduleEnd, clampedVirtualEnd);
    }

    if (!loadedAnySegment)
    {
        std::cerr << "ELF contains no loadable PT_LOAD segments." << std::endl;
        return false;
    }

    if (maxLoadedRdramEnd > PS2_RAM_SIZE)
    {
        maxLoadedRdramEnd = PS2_RAM_SIZE;
    }

    const uint32_t paddedEnd = (maxLoadedRdramEnd > (PS2_RAM_SIZE - kGuestHeapSafetyPad))
                                   ? PS2_RAM_SIZE
                                   : (maxLoadedRdramEnd + kGuestHeapSafetyPad);
    const uint32_t suggestedHeapBase = alignGuestHeapValue(paddedEnd, kGuestHeapDefaultAlignment);
    {
        std::lock_guard<std::mutex> lock(m_guestHeapMutex);
        if (!m_guestHeapConfigured)
        {
            const uint32_t hardLimit = std::min(kGuestHeapHardLimit, PS2_RAM_SIZE);
            m_guestHeapSuggestedBase = std::min(suggestedHeapBase, hardLimit);
            m_guestHeapBase = m_guestHeapSuggestedBase;
            m_guestHeapEnd = m_guestHeapSuggestedBase;
            m_guestHeapLimit = hardLimit;
        }
    }
    {
        std::lock_guard<std::mutex> lock(m_asyncCallbackStackMutex);
        m_asyncCallbackStackFloor = kRuntimeArenaBase;
        m_asyncCallbackStackTop = kRuntimeArenaEnd;
        m_nativeRpcScratch = 0u;
    }

    LoadedModule module;
    module.name = elfPath.substr(elfPath.find_last_of("/\\") + 1);
    module.baseAddress = (moduleBase == std::numeric_limits<uint32_t>::max()) ? 0x00100000u : moduleBase;
    module.size = (moduleEnd > module.baseAddress) ? static_cast<size_t>(moduleEnd - module.baseAddress) : 0u;
    module.active = true;

    m_loadedModules.push_back(module);

    uint32_t elfCrc32 = 0u;
    const bool elfCrc32Valid = computeFileCrc32(elfPath, elfCrc32);
    if (!elfCrc32Valid)
    {
        std::cerr << "[ps2xIOP] failed to compute ELF CRC32 for '" << elfPath << "'" << std::endl;
    }
    ps2x::iop::GameIdentity identity;
    identity.elfName = module.name;
    identity.entryPoint = m_cpuContext.pc;
    identity.crc32 = elfCrc32;
    std::string romError;
    if (!m_romDevice.configure(identity, &romError))
    {
        std::cerr << "[ROM0] failed to configure profile: " << romError << std::endl;
        return false;
    }

    m_iopSubsystem->reset();

    ps2_game_overrides::applyMatching(*this,
                                      elfPath,
                                      m_cpuContext.pc,
                                      elfCrc32,
                                      elfCrc32Valid);

    RUNTIME_LOG("ELF file loaded successfully. Entry point: 0x" << std::hex << m_cpuContext.pc << std::dec);
    return true;
}

const PS2Runtime::IoPaths &PS2Runtime::getIoPaths()
{
    return runtimeIoPaths();
}

void PS2Runtime::setIoPaths(const IoPaths &paths)
{
    IoPaths normalized = paths;
    normalized.elfPath = normalizeAbsolutePath(normalized.elfPath);
    normalized.elfDirectory = normalizeAbsolutePath(normalized.elfDirectory);
    normalized.hostRoot = normalizeAbsolutePath(normalized.hostRoot);
    normalized.cdRoot = normalizeAbsolutePath(normalized.cdRoot);
    normalized.mcRoot = normalizeAbsolutePath(normalized.mcRoot);
    normalized.cdImage = normalizeAbsolutePath(normalized.cdImage);

    if (normalized.elfDirectory.empty() && !normalized.elfPath.empty())
    {
        normalized.elfDirectory = normalized.elfPath.parent_path();
    }

    if (normalized.hostRoot.empty())
    {
        normalized.hostRoot = normalized.elfDirectory;
    }
    if (normalized.cdRoot.empty())
    {
        normalized.cdRoot = normalized.elfDirectory;
    }
    if (normalized.mcRoot.empty())
    {
        normalized.mcRoot = ps2_saves::fileCardRoot(normalized.elfDirectory);
    }

    runtimeIoPaths() = normalized;
}

void PS2Runtime::configureIoPathsFromElf(const std::string &elfPath)
{
    IoPaths paths = runtimeIoPaths();
    paths.elfPath = normalizeAbsolutePath(std::filesystem::path(elfPath));
    if (!paths.elfPath.empty())
    {
        paths.elfDirectory = paths.elfPath.parent_path();
    }

    if (!paths.elfDirectory.empty())
    {
        paths.hostRoot = paths.elfDirectory;
        paths.cdRoot = paths.elfDirectory;
        ps2_saves::migrateLegacyStorage(paths.elfDirectory);
        paths.mcRoot = ps2_saves::fileCardRoot(paths.elfDirectory);
    }

    setIoPaths(paths);
}

namespace
{
    bool generatedFunctionTableSlot(uint32_t address, uint32_t &slot)
    {
        if ((address & 3u) != 0u || g_ps2RecompiledFunctionTableSlotCount == 0u)
        {
            return false;
        }

        if (address < g_ps2RecompiledFunctionTableBase || address >= g_ps2RecompiledFunctionTableEnd)
        {
            return false;
        }

        const uint32_t offset = address - g_ps2RecompiledFunctionTableBase;
        slot = offset >> 2;
        return slot < g_ps2RecompiledFunctionTableSlotCount;
    }
}

static PS2Runtime::RecompiledFunction sparseLookupFunction(uint32_t address)
{
    if (g_ps2RecompiledFunctionSparseCount == 0u)
    {
        return nullptr;
    }

    uint32_t low = 0u;
    uint32_t high = g_ps2RecompiledFunctionSparseCount;
    while (low < high)
    {
        const uint32_t mid = low + (high - low) / 2u;
        const uint32_t probe = g_ps2RecompiledFunctionSparseAddress[mid];
        if (probe == address)
        {
            return g_ps2RecompiledFunctionSparseTarget[mid];
        }
        if (probe < address)
        {
            low = mid + 1u;
        }
        else
        {
            high = mid;
        }
    }
    return nullptr;
}

bool PS2Runtime::replaceFunction(uint32_t address, RecompiledFunction func)
{
    if (m_nativeModuleRamGeneration == m_memory.rdramGeneration()
        && m_nativeModules.containsAddress(address)) return false;
    uint32_t slot = 0u;
    if (!generatedFunctionTableSlot(address, slot))
    {
        std::cerr << "[function-table] cannot replace guest PC 0x" << std::hex << address
                  << ": outside generated dense table [0x" << g_ps2RecompiledFunctionTableBase
                  << ", 0x" << g_ps2RecompiledFunctionTableEnd << ")"
                  << std::dec << std::endl;
        return false;
    }

    g_ps2RecompiledFunctionTable[slot] = func;
    return true;
}

bool PS2Runtime::registerFunction(uint32_t address, RecompiledFunction func)
{
    return replaceFunction(address, func);
}

bool PS2Runtime::bindNativeModule(uint32_t base, const ps2x::NativeModuleDescriptor& descriptor,
                                  std::string* reason)
{
    if (m_nativeModuleRamGeneration != m_memory.rdramGeneration()) clearNativeModules();
    if (!m_memory.getRDRAM())
    {
        if (reason) *reason = "runtime RAM is not initialized";
        return false;
    }
    const uint64_t end = uint64_t(base) + descriptor.imageSize;
    if ((base & 3u) || !descriptor.imageSize || end > m_memory.rdramSize()
        || end > PS2_RAM_SIZE)
    {
        if (reason) *reason = "native module is outside runtime RAM";
        return false;
    }
    // Never hide an existing main-executable entry, including an entry that
    // lies in module data rather than its compiled bodies.
    for (uint64_t address = base; address < end; address += 4)
    {
        uint32_t slot = 0;
        if ((generatedFunctionTableSlot(uint32_t(address), slot)
             && g_ps2RecompiledFunctionTable[slot]) || sparseLookupFunction(uint32_t(address)))
        {
            if (reason) *reason = "native module overlaps a main-executable function";
            return false;
        }
    }
    return m_nativeModules.bind(base, descriptor,
        {m_memory.getRDRAM(), m_memory.rdramSize()}, reason);
}

bool PS2Runtime::unbindNativeModule(uint32_t base)
{
    return m_nativeModules.unbind(base);
}

void PS2Runtime::setGuestBranchObserver(uint32_t sourcePc, GuestBranchObserver observer)
{
    if (sourcePc & 3u) throw std::invalid_argument("Unaligned guest branch observer source");
    if (!observer) { m_guestBranchObservers.erase(sourcePc); return; }
    auto owned = std::make_shared<const GuestBranchObserver>(std::move(observer));
    m_guestBranchObservers.insert_or_assign(sourcePc, std::move(owned));
}

void PS2Runtime::clearNativeModules()
{
    m_nativeModules.clear();
    m_nativeModuleRamGeneration = m_memory.rdramGeneration();
}

void PS2Runtime::invokeNativeModule(uint8_t* ram, R5900Context* ctx, PS2Runtime* runtime)
{
    if (!runtime || !ctx) return;
    const uint32_t target = ctx->pc;
    if (runtime->m_nativeModuleRamGeneration != runtime->m_memory.rdramGeneration()
        || !runtime->m_nativeModules.lookup(target).invoke(ram, ctx, runtime))
    {
        // Includes unload during a native body. Do not manufacture a return
        // or allow dispatchGuestBranch to continue a now-invalid image.
        runtime->reportMissingFunction(ram, ctx, target, 0,
            GuestBranchKind::IndirectJump, "native-module-invalidated");
        runtime->requestStop();
        ctx->pc = 0;
    }
}

bool PS2Runtime::hasFunction(uint32_t address) const
{
    // Binding rejects overlaps with main-executable entries. Resolve the
    // common dense-table case without querying dynamic module lifetimes.
    uint32_t slot = 0u;
    if (generatedFunctionTableSlot(address, slot) && g_ps2RecompiledFunctionTable[slot] != nullptr)
        return true;
    if (m_nativeModuleRamGeneration == m_memory.rdramGeneration()
        && m_nativeModules.hasFunction(address)) return true;
    return sparseLookupFunction(address) != nullptr;
}

const char *describeGuestBranchKind(PS2Runtime::GuestBranchKind kind)
{
    switch (kind)
    {
    case PS2Runtime::GuestBranchKind::DirectJump:
        return "DirectJump";
    case PS2Runtime::GuestBranchKind::DirectCall:
        return "DirectCall";
    case PS2Runtime::GuestBranchKind::IndirectJump:
        return "IndirectJump";
    case PS2Runtime::GuestBranchKind::IndirectCall:
        return "IndirectCall";
    case PS2Runtime::GuestBranchKind::Return:
        return "Return";
    default:
        return "Unknown";
    }
}

PS2Runtime::RecompiledFunction PS2Runtime::lookupFunction(uint32_t address)
{
    pushDispatchPc(address);

    uint32_t slot = 0u;
    if (generatedFunctionTableSlot(address, slot))
    {
        RecompiledFunction fn = g_ps2RecompiledFunctionTable[slot];
        if (fn != nullptr)
        {
            return fn;
        }
    }

    if (m_nativeModuleRamGeneration == m_memory.rdramGeneration()
        && m_nativeModules.hasFunction(address)) return invokeNativeModule;

    if (RecompiledFunction fn = sparseLookupFunction(address))
    {
        return fn;
    }

    std::cerr << "Error: No exact recompiled function for guest PC 0x" << std::hex << address
              << " tableBase=0x" << g_ps2RecompiledFunctionTableBase
              << " tableEnd=0x" << g_ps2RecompiledFunctionTableEnd
              << " codeRegion=" << (m_memory.isCodeAddress(address) ? "yes" : "no")
              << " trace=" << formatDispatchHistory()
              << std::dec << std::endl;

    static RecompiledFunction missingFunction = [](uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        const uint32_t badPc = ctx->pc;
        runtime->reportMissingFunction(rdram,
                                       ctx,
                                       badPc,
                                       0u,
                                       PS2Runtime::GuestBranchKind::IndirectJump,
                                       "dispatch");
    };

    return missingFunction;
}

void PS2Runtime::setMissingFunctionPolicy(MissingFunctionPolicy policy)
{
    m_missingFunctionPolicy.store(static_cast<uint32_t>(policy), std::memory_order_release);
}

PS2Runtime::MissingFunctionPolicy PS2Runtime::missingFunctionPolicy() const
{
    return static_cast<MissingFunctionPolicy>(m_missingFunctionPolicy.load(std::memory_order_acquire));
}

void PS2Runtime::resetMissingFunctionReportOnce()
{
    m_missingFunctionReported.store(false, std::memory_order_release);
}

void PS2Runtime::reportMissingFunction(uint8_t *rdram,
                                       R5900Context *ctx,
                                       uint32_t targetPc,
                                       uint32_t sourcePc,
                                       GuestBranchKind kind,
                                       const char *debugName)
{
    const MissingFunctionPolicy policy = missingFunctionPolicy();

    // PATCH 16: a distinct target earns its own line. The old single latch made
    // every hole after the first invisible, and one build cycle per hole is
    // twelve minutes per discovery. `firstReport` still gates the one-time
    // banner and the BreakOnce policy below; `newTarget` gates the detail dump.
    bool newTarget = false;
    {
        std::lock_guard<std::mutex> lock(m_missingTargetMutex);
        if (std::find(m_missingTargetsReported.begin(), m_missingTargetsReported.end(),
                      targetPc) == m_missingTargetsReported.end()
            && m_missingTargetsReported.size() < kMissingTargetReportCap) {
            m_missingTargetsReported.push_back(targetPc);
            newTarget = true;
        }
    }
    const bool firstReport = !m_missingFunctionReported.exchange(true, std::memory_order_acq_rel);

    const uint32_t pc = ctx->pc;
    const uint32_t ra = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[31], 0));
    const uint32_t sp = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[29], 0));
    const uint32_t gp = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[28], 0));
    const uint32_t a0 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[4], 0));
    const uint32_t a1 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[5], 0));
    const uint32_t a2 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[6], 0));
    const uint32_t a3 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[7], 0));
    const uint32_t s0 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[16], 0));
    const uint32_t s1 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[17], 0));
    const uint32_t v0 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[2], 0));
    const uint32_t v1 = static_cast<uint32_t>(_mm_extract_epi32(ctx->r[3], 0));

    auto readGuestU32At = [rdram](uint32_t addr, uint32_t &out) -> bool
    {
        // TODO this !rdram exist only because of test fix those test later
        if (!rdram || addr > PS2_RAM_SIZE - sizeof(uint32_t))
        {
            out = 0u;
            return false;
        }

        std::memcpy(&out, rdram + addr, sizeof(uint32_t));
        return true;
    };

    auto readGuestU32Offset = [&readGuestU32At](uint32_t base, uint32_t offset, uint32_t &out) -> bool
    {
        if (base > PS2_RAM_SIZE - sizeof(uint32_t) || offset > PS2_RAM_SIZE - sizeof(uint32_t) - base)
        {
            out = 0u;
            return false;
        }

        return readGuestU32At(base + offset, out);
    };

    uint32_t a0Word0 = 0u;
    uint32_t a0Word4 = 0u;
    uint32_t a0Word8 = 0u;
    uint32_t a0WordC = 0u;
    const bool a0Readable =
        readGuestU32Offset(a0, 0x00u, a0Word0) &&
        readGuestU32Offset(a0, 0x04u, a0Word4) &&
        readGuestU32Offset(a0, 0x08u, a0Word8) &&
        readGuestU32Offset(a0, 0x0cu, a0WordC);

    uint32_t s0Word0 = 0u;
    uint32_t s0Word4 = 0u;
    uint32_t s0Word8 = 0u;
    uint32_t s0WordC = 0u;
    const bool s0Readable =
        readGuestU32Offset(s0, 0x00u, s0Word0) &&
        readGuestU32Offset(s0, 0x04u, s0Word4) &&
        readGuestU32Offset(s0, 0x08u, s0Word8) &&
        readGuestU32Offset(s0, 0x0cu, s0WordC);

    uint32_t recordWord0 = 0u;
    uint32_t recordWord4 = 0u;
    uint32_t recordWord8 = 0u;
    uint32_t recordWordC = 0u;
    const bool recordReadable =
        s0Readable && s0Word4 != 0u &&
        readGuestU32Offset(s0Word4, 0x00u, recordWord0) &&
        readGuestU32Offset(s0Word4, 0x04u, recordWord4) &&
        readGuestU32Offset(s0Word4, 0x08u, recordWord8) &&
        readGuestU32Offset(s0Word4, 0x0cu, recordWordC);

    uint32_t vtableSlot0 = 0u;
    uint32_t vtableSlot4 = 0u;
    uint32_t vtableSlot8 = 0u;
    uint32_t vtableSlotC = 0u;
    const bool vtableReadable =
        a0Readable && a0Word0 != 0u &&
        readGuestU32Offset(a0Word0, 0x00u, vtableSlot0) &&
        readGuestU32Offset(a0Word0, 0x04u, vtableSlot4) &&
        readGuestU32Offset(a0Word0, 0x08u, vtableSlot8) &&
        readGuestU32Offset(a0Word0, 0x0cu, vtableSlotC);

    if (newTarget)
    {
        std::ostringstream oss;
        oss << "[guest-branch:missing-target] " << (m_missingTargetsReported.size() > 1 ? "also " : "")
            << "kind=" << describeGuestBranchKind(kind)
            << " op=" << (debugName ? debugName : "<unknown>")
            << " source=0x" << std::hex << sourcePc
            << " target=0x" << targetPc
            << " pc=0x" << pc
            << " ra=0x" << ra
            << " sp=0x" << sp
            << " gp=0x" << gp
            << " a0=0x" << a0
            << " a1=0x" << a1
            << " a2=0x" << a2
            << " a3=0x" << a3
            << " s0=0x" << s0
            << " s1=0x" << s1
            << " v0=0x" << v0
            << " v1=0x" << v1
            << " a0Readable=" << (a0Readable ? "yes" : "no")
            << " a0[0]=0x" << a0Word0
            << " a0[4]=0x" << a0Word4
            << " a0[8]=0x" << a0Word8
            << " a0[c]=0x" << a0WordC
            << " s0Readable=" << (s0Readable ? "yes" : "no")
            << " s0[0]=0x" << s0Word0
            << " s0[4]=0x" << s0Word4
            << " s0[8]=0x" << s0Word8
            << " s0[c]=0x" << s0WordC
            << " recordReadable=" << (recordReadable ? "yes" : "no")
            << " record[0]=0x" << recordWord0
            << " record[4]=0x" << recordWord4
            << " record[8]=0x" << recordWord8
            << " record[c]=0x" << recordWordC
            << " vtableReadable=" << (vtableReadable ? "yes" : "no")
            << " vtbl[0]=0x" << vtableSlot0
            << " vtbl[4]=0x" << vtableSlot4
            << " vtbl[8]=0x" << vtableSlot8
            << " vtbl[c]=0x" << vtableSlotC
            << " codeRegion=" << (m_memory.isCodeAddress(targetPc) ? "yes" : "no")
            << " policy=" << static_cast<uint32_t>(policy)
            << " trace=" << formatDispatchHistory()
            << std::dec;

        static std::mutex s_missingFunctionLogMutex;
        {
            std::lock_guard<std::mutex> lock(s_missingFunctionLogMutex);
            std::cerr << oss.str() << std::endl;
        }
    }

    if (firstReport && policy == MissingFunctionPolicy::BreakOnce)
    {
#if defined(_MSC_VER)
        __debugbreak();
#endif // TODO others breakpoints
    }

    if (ctx)
    {
        ctx->pc = targetPc;
    }

    if (policy == MissingFunctionPolicy::Stop)
    {
        requestStop();
    }
}

namespace
{
// Runs only on the EE executor. Observe nested transfers as well as the
// scheduler boundaries; a reported PC is an observation, not a store PC.
void traceGuestBoundaryWords(uint8_t *rdram, const R5900Context *ctx,
                             uint32_t sourcePc, uint32_t targetPc, const char *phase)
{
    struct Probe
    {
        std::vector<uint32_t> addresses;
        std::vector<uint32_t> values;
        uint32_t rows = 0;
        uint32_t previousSource = 0;
        uint32_t previousTarget = 0;
        bool initialized = false;
        Probe()
        {
            const char *cursor = std::getenv("PS2X_TRACE_GUEST_WORDS");
            while (cursor && *cursor && addresses.size() < 16u)
            {
                char *end = nullptr;
                const unsigned long address = std::strtoul(cursor, &end, 0);
                if (end == cursor || address > PS2_RAM_SIZE - 4u ||
                    (address & 3u) || (*end && *end != ','))
                {
                    std::cerr << "[EE boundary] Invalid aligned physical RAM address\n";
                    addresses.clear();
                    break;
                }
                addresses.push_back(static_cast<uint32_t>(address));
                cursor = *end == ',' ? end + 1 : end;
            }
            values.resize(addresses.size());
        }
    };
    static thread_local Probe probe;
    if (probe.addresses.empty() || probe.rows >= 8192u || !rdram || !ctx) return;
    bool changed = !probe.initialized;
    std::array<uint32_t, 16> current{};
    for (size_t i = 0; i < probe.addresses.size(); ++i)
    {
        current[i] = Ps2FastRead32(rdram, probe.addresses[i]);
        changed = changed || current[i] != probe.values[i];
    }
    if (changed)
    {
        std::ostringstream out;
        out << "[EE boundary " << phase << "] source=0x" << std::hex << sourcePc
            << " target=0x" << targetPc << " pc=0x" << ctx->pc
            << " previous_source=0x" << probe.previousSource
            << " previous_target=0x" << probe.previousTarget;
        for (size_t i = 0; i < probe.addresses.size(); ++i)
        {
            out << " word_" << probe.addresses[i] << "=0x" << current[i];
            if (probe.initialized) out << " old=0x" << probe.values[i];
        }
        std::cerr << out.str() << '\n';
        if (++probe.rows == 8192u)
            std::cerr << "[EE boundary] Row limit reached; subsequent observations omitted\n";
    }
    for (size_t i = 0; i < probe.addresses.size(); ++i) probe.values[i] = current[i];
    probe.initialized = true;
    probe.previousSource = sourcePc;
    probe.previousTarget = targetPc;
}
}

extern uint64_t g_vu1XgkickPackets;
extern uint64_t g_vu1XgkickBytes;
uint64_t g_vu1Mscals = 0;

namespace
{
    // PS2X_TRACE_VU1: once per EE vsync, MSCAL count, distinct program
    // starts, VU1 cycles and XGKICK packets/bytes sent to the GS.
    void traceVu1Mscal(uint32_t startPc, uint64_t vu1Cycles)
    {
        static const bool enabled = std::getenv("PS2X_TRACE_VU1") != nullptr;
        if (!enabled)
            return;
        static uint64_t &mscals = g_vu1Mscals;
        static std::unordered_map<uint32_t, uint32_t> starts;
        ++mscals;
        ++starts[startPc];
        (void)vu1Cycles;
        static uint64_t lastReport = 0;
        if (mscals - lastReport >= 64u)
        {
            lastReport = mscals;
            std::cerr << "[VU1] mscals=" << mscals << " xgkick_packets=" << g_vu1XgkickPackets
                      << " xgkick_bytes=" << g_vu1XgkickBytes << " starts=" << std::hex;
            for (const auto &[pc, count] : starts)
                std::cerr << pc << ':' << std::dec << count << std::hex << ',';
            std::cerr << std::dec << std::endl;
            starts.clear();
        }
    }
}

bool PS2Runtime::dispatchGuestBranch(uint8_t *rdram,
                                     R5900Context *ctx,
                                     uint32_t targetPc,
                                     uint32_t sourcePc,
                                     uint32_t fallthroughPc,
                                     GuestBranchKind kind,
                                     const char *debugName)
{
    static const bool traceBoundaryWords = [] {
        const char *value = std::getenv("PS2X_TRACE_GUEST_WORDS");
        return value && *value;
    }();
    if (traceBoundaryWords)
        traceGuestBoundaryWords(rdram, ctx, sourcePc, targetPc, "transfer");
    ctx->pc = targetPc;
    const bool isCall = (kind == GuestBranchKind::DirectCall || kind == GuestBranchKind::IndirectCall);

    // Startup diagnostics are opt-in. Avoid all their local static guards,
    // vectors and trace argument copies on the ordinary transfer path.
    // Observers remain dynamic and must never be bypassed by this guard.
    static const bool dispatchDiagnosticsEnabled = [] {
        for (const char *name : {"PS2X_CALL_PROFILE_AT", "PS2X_WATCH_RANGE",
             "PS2X_CAPTURE_CALL_TARGET", "PS2X_CAPTURE_CALL_FROM", "PS2X_CAPTURE_CALL_PREFIX",
             "PS2X_CAPTURE_CALL_IOP", "PS2X_CAPTURE_CALL_FIELDS", "PS2X_TRACE_CALL_ARGS", "PS2X_TRACE_CALL_FROM",
             "PS2X_TRACE_CALLS", "PS2X_TRACE_CALL_SOURCES", "PS2X_TRACE_CALL_ARM", "PS2X_TRACE_CALL_MEMORY"})
            if (std::getenv(name) != nullptr) return true;
        return false;
    }();
    auto dispatchTransfer = [&](auto &&emitCallTrace) -> bool {
        // Every inter-function transfer is also a deterministic EE safe point.
        // Backward edges inside generated functions use eeCheckpointDue(), while
        // this charge bounds straight-line call chains that have no local loop.
        if (m_eeScheduler && m_eeScheduler->checkpointDue(EeScheduler::kGuestDispatchCycles))
        {
            return false;
        }

        if (!isCall)
        {
            // LODESTONE PATCH 11 — `$ra == 0` is the invocation-completion sentinel,
            // not a missing branch.
            //
            // A guest that installs its OWN syscall handler with SetSyscall (0x74)
            // is entered through EeScheduler's invocation path, which sets
            // `$ra = 0`. When that guest function does `jr $ra`, the PC becomes 0,
            // and 0 is precisely how EeScheduler recognises "this invocation is
            // finished" — it pops it and runs onComplete.
            //
            // Reporting that as `[guest-branch:missing-target]` is a false positive
            // on a path that is working, and it is an expensive one: `firstReport`
            // is a one-shot latch, so the single worst time to spend it is the
            // sentinel that fires on EVERY handler return. RE4 hit exactly this —
            // 0x2A1C88 returning was reported as a missing branch, which consumed
            // the latch and would hide the next real fault.
            //
            // 0 is never a real guest function: the EE loads at 0x00100000.
            if (targetPc == 0u)
            {
                ctx->pc = 0u;
                return false;
            }

            if (!hasFunction(targetPc))
            {
                reportMissingFunction(rdram, ctx, targetPc, sourcePc, kind, debugName);
            }

            ctx->pc = targetPc;
            return false;
        }

        if (!hasFunction(targetPc))
        {
            reportMissingFunction(rdram, ctx, targetPc, sourcePc, kind, debugName);

            const MissingFunctionPolicy policy = missingFunctionPolicy();

            if (policy == MissingFunctionPolicy::SkipCallDebug && isCall)
            {
                ctx->pc = fallthroughPc;
                return true;
            }

            if (policy == MissingFunctionPolicy::ContinueToTarget)
            {
                ctx->pc = targetPc;
                // if you need the app to keep open to open debug pannel change this to false
                return false;
            }

            return false;
        }

        RecompiledFunction targetFn = lookupFunction(targetPc);
        const uint32_t entryPc = ctx->pc;
        targetFn(rdram, ctx, this);
        if (traceBoundaryWords)
            traceGuestBoundaryWords(rdram, ctx, sourcePc, targetPc, "leave");
        emitCallTrace("leave");

        if (isStopRequested() || ctx->pc == 0u)
        {
            return false;
        }

        if (ctx->pc == entryPc)
        {
            ctx->pc = fallthroughPc;
        }

        return ctx->pc == fallthroughPc;
    };
    // A loader observer for a few call sites must not turn diagnostics on
    // for every unrelated transfer in the game.
    if (!dispatchDiagnosticsEnabled &&
        (m_guestBranchObservers.empty() || m_guestBranchObservers.find(sourcePc) == m_guestBranchObservers.end()))
        return dispatchTransfer([](const char *) {});

    // PS2X_CALL_PROFILE_AT=v1,v2,...: count guest call targets during each
    // listed EE vsync and print the full histogram when that vsync ends, so
    // two frames (working vs stalled) can be diffed function by function.
    static const std::vector<uint64_t> profileVsyncs = []
    {
        std::vector<uint64_t> out;
        const char *cursor = std::getenv("PS2X_CALL_PROFILE_AT");
        while (cursor && *cursor)
        {
            char *end = nullptr;
            out.push_back(std::strtoull(cursor, &end, 0));
            cursor = (end && *end == ',') ? end + 1 : nullptr;
        }
        return out;
    }();
    // PS2X_WATCH_RANGE=addr:len (len <= 128): compare that RAM range at every
    // guest call/return and log the transfer at which it changed, so the
    // writing function can be found without touching the store macros.
    static const std::pair<uint32_t, uint32_t> watchRange = []
    {
        const char *value = std::getenv("PS2X_WATCH_RANGE");
        if (!value)
            return std::pair<uint32_t, uint32_t>{0u, 0u};
        char *end = nullptr;
        const uint32_t address = static_cast<uint32_t>(std::strtoul(value, &end, 0)) & 0x1FFFFFFCu;
        const uint32_t length = (end && *end == ':') ? static_cast<uint32_t>(std::strtoul(end + 1, nullptr, 0)) : 16u;
        return std::pair<uint32_t, uint32_t>{address, std::min<uint32_t>(length & ~3u, 128u)};
    }();
    if (watchRange.second != 0u && rdram && watchRange.first + watchRange.second <= PS2_RAM_SIZE)
    {
        static uint8_t previous[128];
        static bool primed = false;
        static uint32_t changes = 0;
        const uint8_t *current = rdram + watchRange.first;
        if (!primed)
        {
            std::memcpy(previous, current, watchRange.second);
            primed = true;
        }
        else if (std::memcmp(previous, current, watchRange.second) != 0 && changes < 20000u)
        {
            ++changes;
            std::cerr << "[watch] v=" << m_eeScheduler->currentVSyncTick() << std::hex << " source=0x" << sourcePc
                      << " target=0x" << targetPc << " kind=" << static_cast<int>(kind) << " ra=0x"
                      << getRegU32(ctx, 31) << " words=";
            for (uint32_t offset = 0; offset < watchRange.second; offset += 4u)
            {
                uint32_t word = 0;
                std::memcpy(&word, current + offset, 4);
                std::cerr << word << ',';
            }
            std::cerr << std::dec << std::endl;
            std::memcpy(previous, current, watchRange.second);
        }
    }
    // Opt-in, one-shot integer-call snapshot. Preserve the actual input RAM
    // and registers so a decoder can be replayed without timing or IOP noise.
    // This is not a save state: FPU, device queues and VU micro pipelines are
    // absent. Macro VU registers are observed with the same EE-owned context.
    static const uint32_t captureTarget = [] {
        const char *value = std::getenv("PS2X_CAPTURE_CALL_TARGET");
        return value ? static_cast<uint32_t>(std::strtoul(value, nullptr, 0)) : 0u;
    }();
    static const uint64_t captureFrom = [] {
        const char *value = std::getenv("PS2X_CAPTURE_CALL_FROM");
        return value ? std::strtoull(value, nullptr, 0) : 0u;
    }();
    static PS2CallCapturePlan capturePlan = [] {
        PS2CallCapturePlan plan;
        const char *fields = std::getenv("PS2X_CAPTURE_CALL_FIELDS");
        if (!plan.configure(fields ? fields : "", captureFrom))
            std::cerr << "[call capture] invalid increasing field list; capture disabled\n";
        return plan;
    }();
    if (isCall && rdram && captureTarget && targetPc == captureTarget &&
        capturePlan.due(m_eeScheduler->currentVSyncTick()))
    {
        const char *prefix = std::getenv("PS2X_CAPTURE_CALL_PREFIX");
        if (prefix && *prefix)
        {
            const uint64_t requestedField = capturePlan.consume();
            const char *fields = std::getenv("PS2X_CAPTURE_CALL_FIELDS");
            const std::string outputPrefix = std::string(prefix) +
                (fields && *fields ? "-v" + std::to_string(requestedField) : "");
            const std::string ramPath = outputPrefix + ".ram.bin";
            const std::string jsonPath = outputPrefix + ".json";
            const char *captureIop = std::getenv("PS2X_CAPTURE_CALL_IOP");
            const bool captureIopRam = captureIop && std::string_view(captureIop) == "1";
            const std::string iopPath = outputPrefix + ".iop.ram.bin";
            if (std::ifstream(ramPath).good() || std::ifstream(jsonPath).good() ||
                (captureIopRam && std::ifstream(iopPath).good()))
                std::cerr << "[call capture] refusing existing snapshot " << outputPrefix << '\n';
            else
            {
                std::ofstream ram(ramPath, std::ios::binary);
                ram.write(reinterpret_cast<const char *>(rdram), PS2_RAM_SIZE);
                ram.close();
                // Observe the other side of the SJ exchange at this same EE
                // boundary. This does not advance IOP or capture its devices,
                // CPU contexts, or kernel state; it is not a save state.
                uint32_t iopRamBytes = 0u;
                if (captureIopRam)
                {
                    std::vector<uint8_t> iopRam(2u * 1024u * 1024u);
                    if (readIopMemory(0u, iopRam.data(), static_cast<uint32_t>(iopRam.size())))
                    {
                        std::ofstream iop(iopPath, std::ios::binary);
                        iop.write(reinterpret_cast<const char *>(iopRam.data()), iopRam.size());
                        if (iop.good()) iopRamBytes = static_cast<uint32_t>(iopRam.size());
                    }
                    if (iopRamBytes == 0u)
                        std::cerr << "[call capture] IOP RAM capture failed " << prefix << '\n';
                }
                std::ofstream metadata(jsonPath);
                metadata << "{\"schema\":1,\"ram_bytes\":" << PS2_RAM_SIZE
                         << ",\"iop_ram_bytes\":" << iopRamBytes
                         << ",\"requested_vsync\":" << requestedField
                         << ",\"vsync\":" << m_eeScheduler->currentVSyncTick()
                         << ",\"target\":" << targetPc << ",\"source\":" << sourcePc
                         << ",\"pc\":" << ctx->pc << ",\"sa\":" << ctx->sa
                         << ",\"hi_lo_hex\":[\"" << std::hex << ctx->hi << "\",\"" << ctx->lo
                         << "\",\"" << ctx->hi1 << "\",\"" << ctx->lo1 << "\"],\"gpr_hex\":[";
                for (unsigned reg = 0; reg < 32u; ++reg)
                {
                    uint64_t lanes[2];
                    std::memcpy(lanes, &ctx->r[reg], sizeof(lanes));
                    metadata << (reg ? "," : "") << "[\"" << lanes[0] << "\",\"" << lanes[1] << "\"]";
                }
                metadata << "],\"vu0_vf_hex\":[";
                for (unsigned reg = 0; reg < 32; ++reg) {
                    uint32_t lanes[4];
                    std::memcpy(lanes, &ctx->vu0_vf[reg], sizeof(lanes));
                    metadata << (reg ? "," : "") << "[";
                    for (unsigned lane = 0; lane < 4; ++lane)
                        metadata << (lane ? "," : "") << "\"" << lanes[lane] << "\"";
                    metadata << "]";
                }
                metadata << "],\"vu0_vi\":[" << std::dec;
                for (unsigned reg = 0; reg < 16; ++reg) metadata << (reg ? "," : "") << ctx->vi[reg];
                uint32_t qpi[3], acc[4];
                std::memcpy(&qpi[0], &ctx->vu0_q, 4);
                std::memcpy(&qpi[1], &ctx->vu0_p, 4);
                std::memcpy(&qpi[2], &ctx->vu0_i, 4);
                std::memcpy(acc, &ctx->vu0_acc, sizeof(acc));
                metadata << "],\"vu0_qpi_hex\":[" << std::hex;
                for (unsigned lane = 0; lane < 3; ++lane) metadata << (lane ? "," : "") << "\"" << qpi[lane] << "\"";
                metadata << "],\"vu0_acc_hex\":[";
                for (unsigned lane = 0; lane < 4; ++lane) metadata << (lane ? "," : "") << "\"" << acc[lane] << "\"";
                metadata << "],\"vu0_status\":" << std::dec << ctx->vu0_status
                         << ",\"vu0_mac\":" << ctx->vu0_mac_flags << ",\"vu0_clip\":" << ctx->vu0_clip_flags
                         << ",\"vu0_tpc\":" << ctx->vu0_tpc << ",\"fbrst\":" << ps2ReadVuFbrst(*this, *ctx)
                         << ",\"vpu_stat\":" << ps2ReadVuStatus(*this, *ctx) << "}\n";
                metadata.close();
                std::cerr << "[call capture] " << (ram && metadata ? "saved " : "write failed ") << outputPrefix << '\n';
            }
        }
    }
    // PS2X_TRACE_CALL_ARGS=<target>: once per EE vsync, print a call to that
    // target with a0 and the 0x60 bytes at *(a0+0x40) (CRI player -> SFD
    // handle), to watch a handle's state machine without editing guest code.
    static const uint32_t argTarget = []
    {
        const char *value = std::getenv("PS2X_TRACE_CALL_ARGS");
        return value ? static_cast<uint32_t>(std::strtoul(value, nullptr, 0)) : 0u;
    }();
    // PS2X_TRACE_CALL_FROM=<vsync>: from that vsync on, log every call to the
    // target (bounded) with a0/a1/a2 and the caller, instead of one per vsync.
    static const uint64_t argFrom = []
    {
        const char *value = std::getenv("PS2X_TRACE_CALL_FROM");
        return value ? std::strtoull(value, nullptr, 0) : UINT64_MAX;
    }();
    if (isCall && argTarget != 0u && targetPc == argTarget && argFrom != UINT64_MAX &&
        m_eeScheduler->currentVSyncTick() >= argFrom)
    {
        static uint32_t lines = 0;
        if (lines++ < 60000u)
            std::cerr << "[call each] v=" << m_eeScheduler->currentVSyncTick() << std::hex << " target=0x" << targetPc
                      << " from=0x" << sourcePc << " ra=0x" << getRegU32(ctx, 31) << " a0=0x" << getRegU32(ctx, 4)
                      << " a1=0x" << getRegU32(ctx, 5) << " a2=0x" << getRegU32(ctx, 6) << std::dec << std::endl;
    }
    if (isCall && argTarget != 0u && targetPc == argTarget && rdram && argFrom == UINT64_MAX)
    {
        static uint64_t lastVsync = UINT64_MAX;
        const uint64_t vsync = m_eeScheduler->currentVSyncTick();
        if (vsync != lastVsync)
        {
            lastVsync = vsync;
            const auto word = [&](uint32_t address)
            {
                uint32_t value = 0;
                address &= 0x1FFFFFFCu;
                if (address + 4u <= PS2_RAM_SIZE)
                    std::memcpy(&value, rdram + address, 4);
                return value;
            };
            const uint32_t a0 = getRegU32(ctx, 4);
            const uint32_t handle = word(a0 + 0x40u);
            std::cerr << "[call args] v=" << vsync << std::hex << " target=0x" << targetPc << " a0=0x" << a0
                      << " +294=" << word(a0 + 0x294u) << " +74=" << word(a0 + 0x74u) << " handle=0x" << handle
                      << " words=";
            for (uint32_t offset = 0; offset < 0x60u; offset += 4u)
                std::cerr << word(handle + offset) << ',';
            std::cerr << std::dec << std::endl;
        }
    }
    if (isCall && !profileVsyncs.empty())
    {
        static std::unordered_map<uint32_t, uint32_t> counts;
        static uint64_t profiling = UINT64_MAX;
        const uint64_t vsync = m_eeScheduler->currentVSyncTick();
        if (profiling != UINT64_MAX && vsync != profiling)
        {
            std::vector<std::pair<uint32_t, uint32_t>> rows(counts.begin(), counts.end());
            std::sort(rows.begin(), rows.end());
            std::cerr << "[call profile] v=" << profiling << " functions=" << rows.size() << std::hex;
            for (const auto &[address, count] : rows)
                std::cerr << ' ' << address << ':' << std::dec << count << std::hex;
            std::cerr << std::dec << std::endl;
            counts.clear();
            profiling = UINT64_MAX;
        }
        if (profiling == UINT64_MAX &&
            std::find(profileVsyncs.begin(), profileVsyncs.end(), vsync) != profileVsyncs.end())
            profiling = vsync;
        if (profiling == vsync)
            ++counts[targetPc];
    }
    if (!m_guestBranchObservers.empty())
    {
        const auto found = m_guestBranchObservers.find(sourcePc);
        if (found != m_guestBranchObservers.end())
        {
            // Hold an immutable callback alive even if it replaces/removes its
            // registration while observing this transfer.
            const auto observer = found->second;
            if (!(*observer)(rdram, ctx, this, sourcePc, targetPc, kind))
            {
                requestStop();
                ctx->pc = 0u;
                return false;
            }
        }
    }
    // Opt-in bounded probes of nested guest calls, which do not necessarily
    // appear in the scheduler's top-level dispatch trace.
    static const auto parseTraceAddresses = [](const char *name) {
        std::vector<uint32_t> result;
        const char *cursor = std::getenv(name);
        while (cursor && *cursor && result.size() < 16u)
        {
            char *end = nullptr;
            const unsigned long address = std::strtoul(cursor, &end, 0);
            if (end == cursor || address > UINT32_MAX || (address & 3u) || (*end && *end != ','))
                break;
            result.push_back(static_cast<uint32_t>(address));
            cursor = *end == ',' ? end + 1 : end;
        }
        return result;
    };
    static const auto traceTargets = parseTraceAddresses("PS2X_TRACE_CALLS");
    static const auto traceSources = parseTraceAddresses("PS2X_TRACE_CALL_SOURCES");
    static const auto traceArmTargets = parseTraceAddresses("PS2X_TRACE_CALL_ARM");
    static std::atomic<bool> traceArmed{traceArmTargets.empty()};
    if (!traceArmed.load(std::memory_order_relaxed) &&
        std::find(traceArmTargets.begin(), traceArmTargets.end(), targetPc) != traceArmTargets.end())
    {
        traceArmed.store(true, std::memory_order_relaxed);
        std::cerr << "[EE trace:armed] target=0x" << std::hex << targetPc
                  << " source=0x" << sourcePc << std::dec << '\n';
    }
    struct TraceMemoryWindow { uint32_t base; uint32_t offset; bool indirect; };
    static const auto traceMemory = [] {
        std::vector<TraceMemoryWindow> result;
        const char *cursor = std::getenv("PS2X_TRACE_CALL_MEMORY");
        while (cursor && *cursor && result.size() < 16u)
        {
            char *end = nullptr;
            const unsigned long base = std::strtoul(cursor, &end, 0);
            if (end == cursor || base > UINT32_MAX || (base & 3u)) break;
            const bool indirect = *end == ':';
            unsigned long offset = 0;
            if (indirect)
            {
                cursor = end + 1;
                offset = std::strtoul(cursor, &end, 0);
                if (end == cursor || offset > UINT32_MAX) break;
            }
            if (*end && *end != ',') break;
            result.push_back({static_cast<uint32_t>(base), static_cast<uint32_t>(offset), indirect});
            cursor = *end == ',' ? end + 1 : end;
        }
        return result;
    }();
    static std::atomic<uint32_t> traceCount{0u};
    const bool selectedTrace = traceArmed.load(std::memory_order_relaxed)
        && std::find(traceTargets.begin(), traceTargets.end(), targetPc) != traceTargets.end()
        && (traceSources.empty() || std::find(traceSources.begin(), traceSources.end(), sourcePc) != traceSources.end());
    const bool traceCall = selectedTrace && traceCount.fetch_add(1u, std::memory_order_relaxed) < 256u;
    const std::array<uint32_t, 4> traceArgs{getRegU32(ctx, 4), getRegU32(ctx, 5), getRegU32(ctx, 6), getRegU32(ctx, 7)};
    auto emitCallTrace = [&](const char *phase) {
        if (!traceCall) return;
        std::ostringstream out;
        out << "[EE call " << phase << "] target=0x" << std::hex << targetPc << " source=0x" << sourcePc
            << " pc=0x" << ctx->pc << " v0=0x" << getRegU32(ctx, 2);
        out << " fallthrough=0x" << fallthroughPc;
        if (std::string_view(phase) == "leave")
        {
            // A nested call can unwind at a scheduler checkpoint. Its current
            // v0 is a function result only if dispatch actually returned.
            const bool returned = !isStopRequested() && ctx->pc != 0u &&
                (ctx->pc == fallthroughPc || ctx->pc == targetPc);
            out << " returned=" << (returned ? 1 : 0);
        }
        for (size_t i = 0; i < traceArgs.size(); ++i)
        {
            out << " a" << i << "=0x" << traceArgs[i];
            // Only inspect real physical RAM addresses; no MMIO reads or
            // guessed virtual aliases in diagnostics.
            if (rdram && traceArgs[i] >= 0x1000u && traceArgs[i] <= PS2_RAM_SIZE - 64u)
            {
                out << " bytes" << i << '=';
                for (size_t j = 0; j < 64u; ++j)
                {
                    const unsigned value = rdram[traceArgs[i] + j];
                    if (value < 16u) out << '0';
                    out << value;
                }
            }
        }
        // Read selected physical windows on the EE thread at the call boundary,
        // so completion callbacks can expose the actual destination payload.
        for (const auto &window : traceMemory)
        {
            if (!rdram || window.base < 0x1000u || window.base > PS2_RAM_SIZE - 4u) continue;
            const uint32_t pointer = window.indirect ? Ps2FastRead32(rdram, window.base) : window.base;
            // Widen before adding so a malformed guest pointer cannot wrap
            // into an apparently valid physical RAM window.
            const uint64_t address = static_cast<uint64_t>(pointer) + window.offset;
            if (address < 0x1000u || address > PS2_RAM_SIZE - 64u) continue;
            out << " mem_" << window.base;
            if (window.indirect) out << "_at_" << window.offset << "_resolved_" << address;
            out << '=';
            for (size_t j = 0; j < 64u; ++j)
                out << std::setw(2) << std::setfill('0') << static_cast<unsigned>(rdram[address + j]);
        }
        std::cerr << out.str() << '\n';
    };
    emitCallTrace("enter");

    return dispatchTransfer(emitCallTrace);
}

void PS2Runtime::SignalException(R5900Context *ctx, PS2Exception exception)
{
    if (exception == EXCEPTION_INTEGER_OVERFLOW)
    {
        HandleIntegerOverflow(ctx);
        return;
    }

    raiseCop0Exception(ctx, static_cast<uint32_t>(exception),
                       exception == EXCEPTION_TLB_REFILL);
}

void PS2Runtime::executeVU0Microprogram(uint8_t *rdram, R5900Context *ctx, uint32_t address)
{
    (void)rdram;

    uint8_t *const vu0Code = m_memory.getVU0Code();
    uint8_t *const vu0Data = m_memory.getVU0Data();
    const uint32_t startPC = address & ~0x7u;

    // Only these two controls are shared here. VF/VI and other COP2 fields
    // retain their current representation and require a separate ownership audit.
    ctx->vu0_fbrst = m_cpuContext.vu0_fbrst;
    ctx->vu0_vpu_stat = m_cpuContext.vu0_vpu_stat;

    if (!vu0Code || !vu0Data || startPC + 8u > PS2_VU0_CODE_SIZE)
    {
        seedVu0IdleSuccess(ctx);
        m_cpuContext.vu0_vpu_stat = ctx->vu0_vpu_stat;
        return;
    }

    m_vu0.reset();
    copyVu0ContextToState(ctx, m_vu0.state());
    m_vu0.execute(vu0Code, PS2_VU0_CODE_SIZE,
                  vu0Data, PS2_VU0_DATA_SIZE,
                  m_gs, &m_memory,
                  startPC, 0u, ctx->vu0_itop, 4096);
    copyVu0StateToContext(m_vu0.state(), ctx);
    m_cpuContext.vu0_vpu_stat = ctx->vu0_vpu_stat;
}

void PS2Runtime::vu0StartMicroProgram(uint8_t *rdram, R5900Context *ctx, uint32_t address)
{
    // VCALLMS uses executeVU0Microprogram directly. VCALLMSR uses CMSAR0;
    // ignore the legacy argument so older generated callers also execute the correct program.
    (void)address;
    const uint32_t startPC = (ctx->vu0_cmsar0 & 0x1FFu) << 3;
    ctx->vu0_pc = startPC;
    executeVU0Microprogram(rdram, ctx, startPC);
}

void PS2Runtime::handleSyscall(uint8_t *rdram, R5900Context *ctx)
{
    handleSyscall(rdram, ctx, 0);
}

void PS2Runtime::handleSyscall(uint8_t *rdram, R5900Context *ctx, uint32_t encodedSyscallId)
{
    if (ctx->in_delay_slot)
    {
        throw std::runtime_error("Attempted to execute a syscall inside a branch delay slot! "
                                 "This breaks the atomic basic block model and is structurally unsupported by the emulator.");
    }

    const uint32_t syscallId = (encodedSyscallId != 0u)
                                   ? encodedSyscallId
                                   : getRegU32(ctx, 3); // $v1 / $3 is the EE kernel syscall number

    // LODESTONE: unconditional syscall trace, keyed on the ID rather than a call
    // counter, so a hot syscall shows up once instead of drowning the log.
    //
    // Added because RE4 calls 0x83 (FindAddress) in a tight loop — 2,000 entries
    // of FUN_002A1CC8 in 25 s — yet FindAddress's own trace, and the
    // AGRESSIVE_LOGS-gated diagnostics, produce ZERO lines. Something is
    // consuming the syscall before it reaches the switch. Without seeing the
    // ID and the dispatch outcome, that is a guess, so measure it.
    {
        static std::atomic<uint32_t> s_syscallTraceCount{0u};
        const uint32_t n = s_syscallTraceCount.fetch_add(1u, std::memory_order_relaxed);
        if (n < 64u)
        {
            std::cerr << "[syscall] id=0x" << std::hex << syscallId
                      << " encoded=0x" << encodedSyscallId
                      << " pc=0x" << ctx->pc
                      << " a0=0x" << getRegU32(ctx, 4)
                      << " a1=0x" << getRegU32(ctx, 5)
                      << " a2=0x" << getRegU32(ctx, 6);
        uint32_t overrideHandler = 0u;
        if (findEeSyscallOverride(syscallId, overrideHandler))
        {
            std::cerr << " override=0x" << std::hex << overrideHandler;
        }
        else
        {
            std::cerr << " override=none";
        }
        std::cerr << std::dec << std::endl;
        }
    }

    if (ps2_syscalls::dispatchNumericSyscall(syscallId, rdram, ctx, this))
    {
        return;
    }

    // God help you
    ps2_syscalls::TODO(rdram, ctx, this, encodedSyscallId);
}

void PS2Runtime::handleBreak(uint8_t *rdram, R5900Context *ctx)
{
    raiseCop0Exception(ctx, EXCEPTION_BREAKPOINT);
}

void PS2Runtime::drainCompletedDmacHandlers(uint8_t *rdram)
{
    if (!m_memory.hasPendingInterruptWork())
    {
        return;
    }
    for (uint32_t cause : m_memory.consumeCompletedDmacCauses())
    {
        ps2_syscalls::dispatchDmacHandlersForCause(rdram, this, cause);
    }
    if (m_memory.consumeIpuInterrupt())
    {
        constexpr uint32_t kIntcIpuCause = 8u;
        eeScheduler().dispatchIrq(false, kIntcIpuCause);
    }
}

void PS2Runtime::handleTrap(uint8_t *rdram, R5900Context *ctx)
{
    raiseCop0Exception(ctx, EXCEPTION_TRAP);
}

void PS2Runtime::handleTLBR(uint8_t *rdram, R5900Context *ctx)
{
    uint32_t vpn = 0;
    uint32_t pfn = 0;
    uint32_t mask = 0;
    bool valid = false;

    const uint32_t index = ctx->cop0_index & 0x3Fu;
    if (!m_memory.tlbRead(index, vpn, pfn, mask, valid))
    {
        raiseCop0Exception(ctx, EXCEPTION_RESERVED_INSTRUCTION);
        return;
    }

    // Preserve low ASID bits in EntryHi.
    ctx->cop0_entryhi = (ctx->cop0_entryhi & 0x00000FFFu) | (vpn & 0xFFFFF000u);
    ctx->cop0_entrylo0 = (ctx->cop0_entrylo0 & ~0x03FFFFC2u) |
                         ((pfn & 0x000FFFFFu) << 6) |
                         (valid ? 0x2u : 0u);
    ctx->cop0_pagemask = mask & 0x01FFE000u;
}

void PS2Runtime::handleTLBWI(uint8_t *rdram, R5900Context *ctx)
{
    const uint32_t index = ctx->cop0_index & 0x3Fu;
    const uint32_t vpn = ctx->cop0_entryhi & 0xFFFFF000u;
    const uint32_t pfn = (ctx->cop0_entrylo0 >> 6) & 0x000FFFFFu;
    const uint32_t mask = ctx->cop0_pagemask & 0x01FFE000u;
    const bool valid = (ctx->cop0_entrylo0 & 0x2u) != 0u;

    if (!m_memory.tlbWrite(index, vpn, pfn, mask, valid))
    {
        raiseCop0Exception(ctx, EXCEPTION_RESERVED_INSTRUCTION);
    }
}

void PS2Runtime::handleTLBWR(uint8_t *rdram, R5900Context *ctx)
{
    const uint32_t entryCount = static_cast<uint32_t>(m_memory.tlbEntryCount());
    if (entryCount == 0)
    {
        raiseCop0Exception(ctx, EXCEPTION_RESERVED_INSTRUCTION);
        return;
    }

    const uint32_t wired = std::min(ctx->cop0_wired, entryCount - 1);
    uint32_t random = ctx->cop0_random % entryCount;
    if (random < wired)
    {
        random = wired;
    }

    const uint32_t vpn = ctx->cop0_entryhi & 0xFFFFF000u;
    const uint32_t pfn = (ctx->cop0_entrylo0 >> 6) & 0x000FFFFFu;
    const uint32_t mask = ctx->cop0_pagemask & 0x01FFE000u;
    const bool valid = (ctx->cop0_entrylo0 & 0x2u) != 0u;

    if (!m_memory.tlbWrite(random, vpn, pfn, mask, valid))
    {
        raiseCop0Exception(ctx, EXCEPTION_RESERVED_INSTRUCTION);
        return;
    }

    // Keep COP0 bookkeeping in sync with the selected slot.
    ctx->cop0_index = (ctx->cop0_index & ~0x3Fu) | (random & 0x3Fu);
    ctx->cop0_random = (random <= wired) ? (entryCount - 1) : (random - 1);
}

void PS2Runtime::handleTLBP(uint8_t *rdram, R5900Context *ctx)
{
    const int32_t index = m_memory.tlbProbe(ctx->cop0_entryhi & 0xFFFFF000u);
    if (index >= 0)
    {
        ctx->cop0_index = (ctx->cop0_index & ~0x8000003Fu) |
                          (static_cast<uint32_t>(index) & 0x3Fu);
    }
    else
    {
        // MIPS sets probe failure bit (P) in Index[31].
        ctx->cop0_index |= 0x80000000u;
    }
}

void PS2Runtime::clearLLBit(R5900Context *ctx)
{
    // LL/SC reservation is tracked separately from COP0 Status.
    ctx->llbit = 0;
    ctx->lladdr = 0;
}

uint32_t PS2Runtime::alignGuestHeapValue(uint32_t value, uint32_t alignment)
{
    if (alignment == 0)
    {
        return value;
    }

    const uint32_t mask = alignment - 1u;
    if (value > (std::numeric_limits<uint32_t>::max() - mask))
    {
        return std::numeric_limits<uint32_t>::max();
    }
    return (value + mask) & ~mask;
}

bool PS2Runtime::isGuestHeapAlignmentValid(uint32_t alignment)
{
    return alignment != 0u && (alignment & (alignment - 1u)) == 0u;
}

uint32_t PS2Runtime::normalizeGuestHeapAlignment(uint32_t alignment)
{
    if (!isGuestHeapAlignmentValid(alignment))
    {
        return kGuestHeapDefaultAlignment;
    }
    return std::max(alignment, kGuestHeapDefaultAlignment);
}

uint32_t PS2Runtime::clampGuestHeapBase(uint32_t guestBase) const
{
    uint32_t normalized = guestBase;
    if (normalized >= PS2_RAM_SIZE)
    {
        normalized &= PS2_RAM_MASK;
    }
    const uint32_t hardLimit = std::min(kGuestHeapHardLimit, PS2_RAM_SIZE);
    return std::min(normalized, hardLimit);
}

uint32_t PS2Runtime::clampGuestHeapLimit(uint32_t guestLimit) const
{
    const uint32_t hardLimit = std::min(kGuestHeapHardLimit, PS2_RAM_SIZE);
    if (guestLimit == 0u || guestLimit > hardLimit)
    {
        return hardLimit;
    }
    return guestLimit;
}

void PS2Runtime::resetGuestHeapLocked(uint32_t guestBase, uint32_t guestLimit)
{
    uint32_t base = alignGuestHeapValue(clampGuestHeapBase(guestBase), kGuestHeapDefaultAlignment);
    uint32_t limit = clampGuestHeapLimit(guestLimit);
    if (base == 0u)
    {
        const uint32_t fallbackBase = (m_guestHeapSuggestedBase != 0u) ? m_guestHeapSuggestedBase : kGuestHeapDefaultBase;
        base = alignGuestHeapValue(clampGuestHeapBase(fallbackBase), kGuestHeapDefaultAlignment);
    }

    if (limit <= base)
    {
        base = alignGuestHeapValue(clampGuestHeapBase(m_guestHeapSuggestedBase), kGuestHeapDefaultAlignment);
        limit = clampGuestHeapLimit(0u);
    }

    if (limit <= base)
    {
        base = 0u;
        limit = 0u;
    }

    m_guestHeapBlocks.clear();
    if (limit > base)
    {
        // Native callbacks/RPC must stay isolated even with a low heap base.
        const uint32_t beforeEnd = std::min(limit, kRuntimeArenaBase);
        if (base < beforeEnd) m_guestHeapBlocks.push_back({base, beforeEnd - base, true});
        const uint32_t afterBase = std::max(base, kRuntimeArenaEnd);
        if (afterBase < limit) m_guestHeapBlocks.push_back({afterBase, limit - afterBase, true});
    }

    m_guestHeapBase = base;
    m_guestHeapEnd = base;
    m_guestHeapLimit = limit;
    m_guestHeapConfigured = true;
}

void PS2Runtime::ensureGuestHeapInitializedLocked()
{
    if (m_guestHeapConfigured)
    {
        return;
    }

    const uint32_t suggested = (m_guestHeapSuggestedBase == 0u) ? kGuestHeapDefaultBase : m_guestHeapSuggestedBase;
    resetGuestHeapLocked(suggested, clampGuestHeapLimit(0u));
}

int32_t PS2Runtime::findGuestHeapBlockIndexLocked(uint32_t guestAddr) const
{
    const uint32_t normalizedAddr = guestAddr & PS2_RAM_MASK;
    for (size_t i = 0; i < m_guestHeapBlocks.size(); ++i)
    {
        const GuestHeapBlock &block = m_guestHeapBlocks[i];
        if (!block.free && block.addr == normalizedAddr)
        {
            return static_cast<int32_t>(i);
        }
    }
    return -1;
}

uint32_t PS2Runtime::allocateGuestBlockLocked(uint32_t size, uint32_t alignment)
{
    if (size == 0u)
    {
        return 0u;
    }

    const uint32_t normalizedAlignment = normalizeGuestHeapAlignment(alignment);
    if (size > (std::numeric_limits<uint32_t>::max() - (kGuestHeapDefaultAlignment - 1u)))
    {
        return 0u;
    }

    const uint32_t allocSize = alignGuestHeapValue(size, kGuestHeapDefaultAlignment);
    if (allocSize == 0u)
    {
        return 0u;
    }

    for (size_t i = 0; i < m_guestHeapBlocks.size(); ++i)
    {
        const GuestHeapBlock block = m_guestHeapBlocks[i];
        if (!block.free)
        {
            continue;
        }

        const uint64_t blockStart = block.addr;
        const uint64_t blockEnd = blockStart + static_cast<uint64_t>(block.size);
        const uint32_t alignedAddr = alignGuestHeapValue(block.addr, normalizedAlignment);
        if (alignedAddr < block.addr)
        {
            continue;
        }

        const uint64_t alignedStart = alignedAddr;
        if (alignedStart > blockEnd)
        {
            continue;
        }

        const uint64_t allocEnd = alignedStart + static_cast<uint64_t>(allocSize);
        if (allocEnd > blockEnd)
        {
            continue;
        }

        const uint32_t prefixSize = static_cast<uint32_t>(alignedStart - blockStart);
        const uint32_t suffixSize = static_cast<uint32_t>(blockEnd - allocEnd);

        std::vector<GuestHeapBlock> replacement;
        replacement.reserve(3);
        if (prefixSize > 0u)
        {
            replacement.push_back({block.addr, prefixSize, true});
        }
        replacement.push_back({alignedAddr, allocSize, false});
        if (suffixSize > 0u)
        {
            replacement.push_back({static_cast<uint32_t>(allocEnd), suffixSize, true});
        }

        m_guestHeapBlocks.erase(m_guestHeapBlocks.begin() + static_cast<std::ptrdiff_t>(i));
        m_guestHeapBlocks.insert(m_guestHeapBlocks.begin() + static_cast<std::ptrdiff_t>(i),
                                 replacement.begin(),
                                 replacement.end());

        m_guestHeapEnd = std::max(m_guestHeapEnd, static_cast<uint32_t>(allocEnd));
        return alignedAddr;
    }

    return 0u;
}

void PS2Runtime::coalesceGuestHeapLocked()
{
    if (m_guestHeapBlocks.empty())
    {
        return;
    }

    size_t i = 1;
    while (i < m_guestHeapBlocks.size())
    {
        GuestHeapBlock &prev = m_guestHeapBlocks[i - 1];
        GuestHeapBlock &curr = m_guestHeapBlocks[i];
        const uint64_t prevEnd = static_cast<uint64_t>(prev.addr) + static_cast<uint64_t>(prev.size);
        if (prev.free && curr.free && prevEnd == curr.addr)
        {
            prev.size += curr.size;
            m_guestHeapBlocks.erase(m_guestHeapBlocks.begin() + static_cast<std::ptrdiff_t>(i));
            continue;
        }
        ++i;
    }
}

void PS2Runtime::freeGuestBlockLocked(uint32_t guestAddr)
{
    const int32_t index = findGuestHeapBlockIndexLocked(guestAddr);
    if (index < 0)
    {
        return;
    }

    m_guestHeapBlocks[static_cast<size_t>(index)].free = true;
    coalesceGuestHeapLocked();
}

void PS2Runtime::configureGuestHeap(uint32_t guestBase, uint32_t guestLimit)
{
    std::lock_guard<std::mutex> lock(m_guestHeapMutex);
    uint32_t normalizedBase = alignGuestHeapValue(clampGuestHeapBase(guestBase), kGuestHeapDefaultAlignment);
    if (normalizedBase == 0u)
    {
        normalizedBase = (m_guestHeapSuggestedBase != 0u) ? m_guestHeapSuggestedBase : kGuestHeapDefaultBase;
    }
    m_guestHeapSuggestedBase = normalizedBase;
    resetGuestHeapLocked(normalizedBase, guestLimit);
}

uint32_t PS2Runtime::guestMalloc(uint32_t size, uint32_t alignment)
{
    std::lock_guard<std::mutex> lock(m_guestHeapMutex);
    ensureGuestHeapInitializedLocked();
    return allocateGuestBlockLocked(size, alignment);
}

uint32_t PS2Runtime::guestCalloc(uint32_t count, uint32_t size, uint32_t alignment)
{
    if (count == 0u || size == 0u)
    {
        return 0u;
    }
    if (count > (std::numeric_limits<uint32_t>::max() / size))
    {
        return 0u;
    }

    const uint32_t totalSize = count * size;
    const uint32_t guestAddr = guestMalloc(totalSize, alignment);
    if (guestAddr != 0u)
    {
        uint8_t *rdram = m_memory.getRDRAM();
        if (rdram)
        {
            uint32_t physAddr = guestAddr & PS2_RAM_MASK;
            if (physAddr + totalSize <= PS2_RAM_SIZE)
                std::memset(rdram + physAddr, 0, totalSize);
        }
    }

    return guestAddr;
}

uint32_t PS2Runtime::guestRealloc(uint32_t guestAddr, uint32_t newSize, uint32_t alignment)
{
    if (guestAddr == 0u)
    {
        return guestMalloc(newSize, alignment);
    }
    if (newSize == 0u)
    {
        guestFree(guestAddr);
        return 0u;
    }

    if (newSize > (std::numeric_limits<uint32_t>::max() - (kGuestHeapDefaultAlignment - 1u)))
    {
        return 0u;
    }

    const uint32_t normalizedAlignment = normalizeGuestHeapAlignment(alignment);
    const uint32_t requestedSize = alignGuestHeapValue(newSize, kGuestHeapDefaultAlignment);

    std::lock_guard<std::mutex> lock(m_guestHeapMutex);
    ensureGuestHeapInitializedLocked();

    const int32_t index = findGuestHeapBlockIndexLocked(guestAddr);
    if (index < 0)
    {
        return 0u;
    }

    const size_t blockIndex = static_cast<size_t>(index);
    const uint32_t oldAddr = m_guestHeapBlocks[blockIndex].addr;
    const uint32_t oldSize = m_guestHeapBlocks[blockIndex].size;

    if (requestedSize <= oldSize)
    {
        if (requestedSize < oldSize)
        {
            const uint32_t tailAddr = oldAddr + requestedSize;
            const uint32_t tailSize = oldSize - requestedSize;
            m_guestHeapBlocks[blockIndex].size = requestedSize;
            m_guestHeapBlocks.insert(m_guestHeapBlocks.begin() + static_cast<std::ptrdiff_t>(blockIndex + 1u),
                                     GuestHeapBlock{tailAddr, tailSize, true});
            coalesceGuestHeapLocked();
        }
        return oldAddr;
    }

    if (blockIndex + 1u < m_guestHeapBlocks.size())
    {
        GuestHeapBlock &next = m_guestHeapBlocks[blockIndex + 1u];
        const uint64_t blockEnd = static_cast<uint64_t>(m_guestHeapBlocks[blockIndex].addr) +
                                  static_cast<uint64_t>(m_guestHeapBlocks[blockIndex].size);
        if (next.free && blockEnd == next.addr)
        {
            const uint64_t combined = static_cast<uint64_t>(m_guestHeapBlocks[blockIndex].size) +
                                      static_cast<uint64_t>(next.size);
            if (combined >= requestedSize)
            {
                const uint32_t extraNeeded = requestedSize - m_guestHeapBlocks[blockIndex].size;
                m_guestHeapBlocks[blockIndex].size = requestedSize;
                if (next.size == extraNeeded)
                {
                    m_guestHeapBlocks.erase(m_guestHeapBlocks.begin() + static_cast<std::ptrdiff_t>(blockIndex + 1u));
                }
                else
                {
                    next.addr += extraNeeded;
                    next.size -= extraNeeded;
                }
                m_guestHeapEnd = std::max(m_guestHeapEnd, oldAddr + requestedSize);
                return oldAddr;
            }
        }
    }

    const uint32_t newAddr = allocateGuestBlockLocked(newSize, normalizedAlignment);
    if (newAddr == 0u)
    {
        return 0u;
    }

    uint8_t *rdram = m_memory.getRDRAM();
    if (rdram)
    {
        const uint32_t copyBytes = std::min(oldSize, newSize);
        uint32_t dstPhys = newAddr & PS2_RAM_MASK;
        uint32_t srcPhys = oldAddr & PS2_RAM_MASK;
        if (dstPhys + copyBytes <= PS2_RAM_SIZE && srcPhys + copyBytes <= PS2_RAM_SIZE)
            std::memmove(rdram + dstPhys, rdram + srcPhys, copyBytes);
    }

    freeGuestBlockLocked(oldAddr);
    return newAddr;
}

void PS2Runtime::guestFree(uint32_t guestAddr)
{
    if (guestAddr == 0u)
    {
        return;
    }

    std::lock_guard<std::mutex> lock(m_guestHeapMutex);
    ensureGuestHeapInitializedLocked();
    freeGuestBlockLocked(guestAddr);
}

uint32_t PS2Runtime::guestHeapBase() const
{
    std::lock_guard<std::mutex> lock(m_guestHeapMutex);
    return m_guestHeapConfigured ? m_guestHeapBase : m_guestHeapSuggestedBase;
}

uint32_t PS2Runtime::guestHeapEnd() const
{
    std::lock_guard<std::mutex> lock(m_guestHeapMutex);
    return m_guestHeapConfigured ? m_guestHeapEnd : m_guestHeapSuggestedBase;
}

uint32_t PS2Runtime::guestHeapLimit() const
{
    std::lock_guard<std::mutex> lock(m_guestHeapMutex);
    return m_guestHeapConfigured ? m_guestHeapLimit : m_guestHeapSuggestedBase;
}

uint32_t PS2Runtime::reserveAsyncCallbackStack(uint32_t size, uint32_t alignment)
{
    if (size == 0u)
    {
        return 0u;
    }

    const uint32_t normalizedAlignment = normalizeGuestHeapAlignment(alignment);
    const uint32_t allocSize = alignGuestHeapValue(size, kGuestHeapDefaultAlignment);
    if (allocSize == 0u)
    {
        return 0u;
    }

    std::lock_guard<std::mutex> lock(m_asyncCallbackStackMutex);
    uint32_t top = m_asyncCallbackStackTop;
    if (top > PS2_RAM_SIZE)
    {
        top = PS2_RAM_SIZE;
    }
    top &= ~(kGuestHeapDefaultAlignment - 1u);

    if (top <= allocSize)
    {
        return 0u;
    }

    uint32_t base = top - allocSize;
    base &= ~(normalizedAlignment - 1u);
    if (base < m_asyncCallbackStackFloor || base >= top)
    {
        return 0u;
    }

    m_asyncCallbackStackTop = base;
    return top - 0x10u;
}

uint32_t PS2Runtime::nativeRpcScratch()
{
    // Native RPC is synchronous on the EE executor. Reserve once, then reuse;
    // guestMalloc can overlap allocations made by the game's own allocator.
    constexpr uint32_t size = 32768u;
    if (m_nativeRpcScratch == 0u)
    {
        const uint32_t top = reserveAsyncCallbackStack(size + 64u, 64u);
        if (top != 0u) m_nativeRpcScratch = (top - size) & ~63u;
    }
    return m_nativeRpcScratch;
}

uint8_t PS2Runtime::Load8(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr)
{
    try
    {
        return m_memory.read8(vaddr);
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_LOAD);
        return 0;
    }
}

uint16_t PS2Runtime::Load16(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr)
{
    try
    {
        return m_memory.read16(vaddr);
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_LOAD);
        return 0;
    }
}

uint32_t PS2Runtime::Load32(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr)
{
    try
    {
        const uint32_t value = m_memory.read32(vaddr);
        // IPU register reads advance the IPU model, which can complete ch3/ch4.
        if (PS2Memory::isIpuRegisterAddress(vaddr & 0x1FFFFFFFu))
        {
            drainCompletedDmacHandlers(rdram);
        }
        return value;
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_LOAD);
        return 0;
    }
}

uint64_t PS2Runtime::Load64(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr)
{
    try
    {
        const uint64_t value = m_memory.read64(vaddr);
        if (PS2Memory::isIpuRegisterAddress(vaddr & 0x1FFFFFFFu))
        {
            drainCompletedDmacHandlers(rdram);
        }
        return value;
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_LOAD);
        return 0;
    }
}

__m128i PS2Runtime::Load128(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr)
{
    try
    {
        return m_memory.read128(vaddr);
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_LOAD);
        return _mm_setzero_si128();
    }
}

void PS2Runtime::Store8(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr, uint8_t value)
{
    ps2TraceGuestWrite(rdram, vaddr, 1u, value, 0u, "WRITE8", ctx);
    try
    {
        m_memory.write8(vaddr, value);
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_STORE);
    }
}

void PS2Runtime::Store16(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr, uint16_t value)
{
    ps2TraceGuestWrite(rdram, vaddr, 2u, value, 0u, "WRITE16", ctx);
    try
    {
        m_memory.write16(vaddr, value);
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_STORE);
    }
}

namespace
{
    void traceCsrStore(PS2Memory &memory, const R5900Context *ctx, uint32_t address,
                       uint64_t value, uint64_t tick, const char *phase)
    {
        if ((address & 0x1FFFFFFFu) != 0x12001000u)
            return;
        static const bool enabled = [] {
            const char *v = std::getenv("PS2X_GS_FINISH_TRACE");
            return v && *v && *v != '0';
        }();
        static const uint64_t from = [] {
            const char *v = std::getenv("PS2X_GS_FINISH_TRACE_FROM");
            return v ? std::strtoull(v, nullptr, 0) : 0u;
        }();
        static unsigned observations = 0;
        if (!enabled || tick < from || observations >= 256u)
            return;
        ++observations;
        std::cerr << "[GS CSR store] phase=" << phase << " vsync=" << tick
                  << " pc=" << (ctx ? ctx->pc : 0u) << " value=" << value
                  << " csr=" << memory.gs().csr.load() << '\n';
    }
}

void PS2Runtime::Store32(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr, uint32_t value)
{
    ps2TraceGuestWrite(rdram, vaddr, 4u, value, 0u, "WRITE32", ctx);
    try
    {
        // Bounded, opt-in observation of normal GIF fence packets. Observe
        // both sides of the actual DMA start without raising FINISH or
        // changing masks, clocks, packet ordering, or guest registers.
        static const bool traceFinish = [] {
            const char *v = std::getenv("PS2X_GS_FINISH_TRACE");
            return v && *v && *v != '0';
        }();
        static const uint64_t traceFinishFrom = [] {
            const char *v = std::getenv("PS2X_GS_FINISH_TRACE_FROM");
            return v ? std::strtoull(v, nullptr, 0) : 0u;
        }();
        static unsigned finishObservations = 0;
        const bool observe = traceFinish && (vaddr & 0x1FFFFFFFu) == 0x1000A000u &&
            (value & 0x10Cu) == 0x100u && finishObservations < 64u &&
            m_memory.read32(0x1000A020u) == 3u &&
            m_eeScheduler->currentVSyncTick() >= traceFinishFrom;
        const uint32_t pc = observe && ctx ? ctx->pc : 0u;
        const uint64_t tick = observe ? m_eeScheduler->currentVSyncTick() : 0u;
        const unsigned observation = observe ? ++finishObservations : 0u;
        if (observe)
        {
            const uint32_t madr = m_memory.read32(0x1000A010u);
            const uint32_t qwc = m_memory.read32(0x1000A020u);
            std::ostringstream message;
            message << "[GIF fence before] index=" << observation << " vsync=" << tick
                    << " pc=" << pc << " chcr=" << value << " madr=" << madr << " qwc=" << qwc
                    << " masked=" << m_memory.isPath3Masked() << " csr=" << m_memory.gs().csr.load()
                    << " dctrl=" << m_memory.read32(0x1000E000u) << " prefix=";
            const uint32_t phys = madr & 0x1FFFFFFFu;
            const uint32_t bytes = static_cast<uint32_t>(std::min<uint64_t>(64u, uint64_t(qwc) * 16u));
            if (rdram && phys < PS2_RAM_SIZE && bytes <= PS2_RAM_SIZE - phys)
                for (uint32_t i = 0; i < bytes; ++i)
                {
                    constexpr char hex[] = "0123456789abcdef";
                    const uint8_t byte = rdram[phys + i];
                    message << hex[byte >> 4u] << hex[byte & 15u];
                }
            std::cerr << message.str() << '\n';
        }
        if ((vaddr & 0x1FFFFFFFu) == 0x12001000u)
            traceCsrStore(m_memory, ctx, vaddr, value, m_eeScheduler->currentVSyncTick(), "before32");
        m_memory.write32(vaddr, value);
        if ((vaddr & 0x1FFFFFFFu) == 0x12001000u)
            traceCsrStore(m_memory, ctx, vaddr, value, m_eeScheduler->currentVSyncTick(), "after32");
        if (observe)
        {
            std::cerr << "[GIF fence submitted] index=" << observation << " vsync=" << tick
                      << " csr=" << m_memory.gs().csr.load() << '\n';
        }
        drainCompletedDmacHandlers(rdram);
        if (observe)
        {
            std::ostringstream message;
            message << "[GIF fence after] index=" << observation << " vsync=" << tick
                    << " pc=" << pc
                    << " qwc=" << m_memory.read32(0x1000A020u)
                    << " masked=" << m_memory.isPath3Masked() << " csr=" << m_memory.gs().csr.load();
            std::cerr << message.str() << '\n';
        }
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_STORE);
    }
}

void PS2Runtime::Store64(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr, uint64_t value)
{
    ps2TraceGuestWrite(rdram, vaddr, 8u, value, 0u, "WRITE64", ctx);
    try
    {
        if ((vaddr & 0x1FFFFFFFu) == 0x12001000u)
            traceCsrStore(m_memory, ctx, vaddr, value, m_eeScheduler->currentVSyncTick(), "before64");
        m_memory.write64(vaddr, value);
        if ((vaddr & 0x1FFFFFFFu) == 0x12001000u)
            traceCsrStore(m_memory, ctx, vaddr, value, m_eeScheduler->currentVSyncTick(), "after64");
        drainCompletedDmacHandlers(rdram);
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_STORE);
    }
}

void PS2Runtime::Store128(uint8_t *rdram, R5900Context *ctx, uint32_t vaddr, __m128i value)
{
    alignas(16) uint64_t _parts[2];
    _mm_storeu_si128(reinterpret_cast<__m128i *>(_parts), value);
    ps2TraceGuestWrite(rdram, vaddr, 16u, _parts[0], _parts[1], "WRITE128", ctx);
    try
    {
        m_memory.write128(vaddr, value);
        drainCompletedDmacHandlers(rdram);
    }
    catch (const std::exception &)
    {
        SignalException(ctx, EXCEPTION_ADDRESS_ERROR_STORE);
    }
}

void PS2Runtime::kickGifDmaChainFromMMIO(uint8_t *rdram,
                                         R5900Context *ctx,
                                         uint32_t dPcrValue,
                                         uint32_t dStatValue,
                                         uint32_t tadr,
                                         uint32_t chcr)
{
    constexpr uint32_t D_PCR = 0x1000E020u;
    constexpr uint32_t D_STAT = 0x1000E010u;
    constexpr uint32_t GIF_TADR = 0x1000A030u;
    constexpr uint32_t GIF_CHCR = 0x1000A000u;

    ps2TraceGuestWrite(rdram, D_PCR, 4u, dPcrValue, 0u, "WRITE32", ctx);
    m_memory.writeIORegister(D_PCR, dPcrValue);
    ps2TraceGuestWrite(rdram, D_STAT, 4u, dStatValue, 0u, "WRITE32", ctx);
    m_memory.writeIORegister(D_STAT, dStatValue);
    ps2TraceGuestWrite(rdram, GIF_TADR, 4u, tadr, 0u, "WRITE32", ctx);
    m_memory.writeIORegister(GIF_TADR, tadr);
    ps2TraceGuestWrite(rdram, GIF_CHCR, 4u, chcr, 0u, "WRITE32", ctx);
    if (m_memory.tryProcessNativeGifImageUploadChain(m_gs, tadr, chcr))
    {
        drainCompletedDmacHandlers(rdram);
        return;
    }
    if (m_memory.tryProcessNativeGifPackedChain(m_gs, tadr, chcr))
    {
        drainCompletedDmacHandlers(rdram);
        return;
    }
    m_memory.writeIORegister(GIF_CHCR, chcr);
    m_memory.processPendingTransfers();
    drainCompletedDmacHandlers(rdram);
}

void PS2Runtime::requestStop()
{
    m_stopRequested.store(true, std::memory_order_relaxed);
    if (m_eeScheduler)
    {
        m_eeScheduler->requestStop();
    }
}

bool PS2Runtime::isStopRequested() const
{
    return m_stopRequested.load(std::memory_order_relaxed);
}

EeScheduler &PS2Runtime::eeScheduler()
{
    return *m_eeScheduler;
}

const EeScheduler &PS2Runtime::eeScheduler() const
{
    return *m_eeScheduler;
}

void PS2Runtime::postEeEvent(EeEvent event)
{
    m_eeScheduler->postEvent(event);
}

bool PS2Runtime::eeCheckpointDue(uint32_t cycles) noexcept
{
    // LODESTONE PATCH 12 — this is the ONLY out-of-line call in the body of a
    // typical guest loop. The recompiler emits it on every backward edge
    // (FUN_002A1C88_0x2a1c88.cpp:98), so it is attributed to the scheduler's
    // Checkpoint phase here, deliberately: the scheduler's own phase timer puts
    // 99.5% of host CPU inside the recompiled function, and a call that
    // physically happens inside that function must be measured inside it or it
    // will be attributed to the wrong owner. It was not the phase timer that
    // found this - it was noticing that the guest's checkpoint is invisible to
    // a phase boundary drawn around the function call.
#if defined(PS2X_GUEST_PC_PROFILE)
    lodestone::GuestPcProfile::instance().phaseBegin(lodestone::GuestPcProfile::Phase::Checkpoint);
#endif
    const bool due = m_eeScheduler->checkpointDue(cycles);
#if defined(PS2X_GUEST_PC_PROFILE)
    lodestone::GuestPcProfile::instance().phaseAdd(lodestone::GuestPcProfile::Phase::Checkpoint);
#endif
    return due;
}

[[noreturn]] void PS2Runtime::eeWaitVSyncTicks(uint32_t ticks, uint32_t resumePc)
{
    const uint64_t currentTick = m_eeScheduler->currentVSyncTick();
    const uint64_t waitTicks = std::max<uint64_t>(1u, ticks);
    m_eeScheduler->waitVSync(currentTick + waitTicks - 1u,
                             0,
                             [resumePc](R5900Context &context)
                             {
                                 context.pc = resumePc;
                             });
}

void PS2Runtime::addEeExitHandler(int threadId, uint32_t function, uint32_t argument)
{
    std::lock_guard lock(m_eeKernelStateMutex);
    m_eeExitHandlers[threadId].push_back({function, argument});
}

std::vector<PS2Runtime::EeExitHandlerRegistration> PS2Runtime::takeEeExitHandlers(int threadId)
{
    std::lock_guard lock(m_eeKernelStateMutex);
    auto it = m_eeExitHandlers.find(threadId);
    if (it == m_eeExitHandlers.end())
    {
        return {};
    }
    auto handlers = std::move(it->second);
    m_eeExitHandlers.erase(it);
    return handlers;
}

void PS2Runtime::removeEeExitHandlers(int threadId)
{
    std::lock_guard lock(m_eeKernelStateMutex);
    m_eeExitHandlers.erase(threadId);
}

bool PS2Runtime::findEeSyscallOverride(uint32_t syscallNumber, uint32_t &handler) const
{
    std::lock_guard lock(m_eeKernelStateMutex);
    const auto it = m_eeSyscallOverrides.find(syscallNumber);
    if (it == m_eeSyscallOverrides.end())
    {
        return false;
    }
    handler = it->second;
    return true;
}

void PS2Runtime::setEeSyscallOverride(uint8_t *rdram, uint32_t syscallNumber, uint32_t handler)
{
    constexpr uint32_t kTableBase = 0x80011F80u & 0x1FFFFFFFu;
    constexpr uint32_t kMirrorLimit = 0x00080000u;
    const int64_t offset = static_cast<int64_t>(static_cast<int32_t>(syscallNumber)) * 4;
    const int64_t address = static_cast<int64_t>(kTableBase) + offset;

    std::lock_guard lock(m_eeKernelStateMutex);
    if (handler == 0u)
    {
        m_eeSyscallOverrides.erase(syscallNumber);
    }
    else
    {
        m_eeSyscallOverrides[syscallNumber] = handler;
    }
    if (!rdram || address < 0 || address + 4 > kMirrorLimit)
    {
        return;
    }
    const uint32_t guestAddress = static_cast<uint32_t>(address);
    std::memcpy(rdram + guestAddress, &handler, sizeof(handler));
    if (handler == 0u)
    {
        m_eeSyscallMirrorAddresses.erase(guestAddress);
    }
    else
    {
        m_eeSyscallMirrorAddresses.insert(guestAddress);
    }
}

void PS2Runtime::initializeEeKernelState(uint8_t *rdram)
{
    if (!rdram)
    {
        return;
    }
    constexpr uint32_t kTableGuestBase = 0x80011F80u;
    constexpr uint32_t kTableBase = kTableGuestBase & 0x1FFFFFFFu;
    constexpr uint32_t kMirrorLimit = 0x00080000u;
    constexpr uint32_t kProbeBase = 0x000002F0u;

    std::lock_guard lock(m_eeKernelStateMutex);
    for (const uint32_t address : m_eeSyscallMirrorAddresses)
    {
        const uint32_t zero = 0u;
        std::memcpy(rdram + address, &zero, sizeof(zero));
    }
    m_eeSyscallMirrorAddresses.clear();
    const uint32_t high = kTableGuestBase >> 16;
    const uint32_t low = kTableGuestBase & 0xFFFFu;
    std::memcpy(rdram + kProbeBase, &high, sizeof(high));
    std::memcpy(rdram + kProbeBase + 8u, &low, sizeof(low));
    m_eeSyscallMirrorAddresses.insert(kProbeBase);
    m_eeSyscallMirrorAddresses.insert(kProbeBase + 8u);

    for (const auto &[syscallNumber, handler] : m_eeSyscallOverrides)
    {
        const int64_t offset = static_cast<int64_t>(static_cast<int32_t>(syscallNumber)) * 4;
        const int64_t address = static_cast<int64_t>(kTableBase) + offset;
        if (address < 0 || address + 4 > kMirrorLimit)
        {
            continue;
        }
        const uint32_t guestAddress = static_cast<uint32_t>(address);
        std::memcpy(rdram + guestAddress, &handler, sizeof(handler));
        m_eeSyscallMirrorAddresses.insert(guestAddress);
    }
}

void PS2Runtime::HandleIntegerOverflow(R5900Context *ctx)
{
    raiseCop0Exception(ctx, EXCEPTION_INTEGER_OVERFLOW);
}

namespace {
// LODESTONE PATCH 15 - see the comment block that was moved here from loadELF.
// LODESTONE PATCH 15 — answer one question about the low RAM window.
//
// RE4's FUN_002A1CE0 passes a0=0x80000000 a1=0x80080000 to its private
// handler FUN_002A1C88, which under the EE's direct-mapped KSEG0 rule
// (`addr & 0x01FFFFFF`) resolves to physical 0x00000000..0x00080000 — the
// first 512 KB. The two keys it searches for are its own syscall handler
// addresses, 0x2A1C88 and 0x2A1C50.
//
// The runtime already mirrors the syscall table into that window:
// initializeEeKernelState puts the table at 0x80011F80 -> physical
// 0x00011F80, so an override of syscall 0x83 lands at 0x11F80 + 0x83*4 =
// 0x0001218C and an override of 0x5A lands at 0x11F80 + 0x5A*4 = 0x000120E8.
// Their difference is 0xA4 — which is exactly the value FUN_002A1CE0's
// loop requires before it will exit.
//
// So the table is present and the geometry fits. The open question is
// whether the handler can SEE it, and the way to settle that without more
// static reading is to search the window for the two keys directly. If
// they are there and the loop still does not finish, the defect is in what
// FUN_002A1C88 returns to its caller, not in what is in memory.
//
// One scan, gated on an environment variable, taken after the syscall mirror
// has been installed and before the guest executes an instruction — so it
// reports the region the search will actually see.
//
// Placed in loadELF this probe would have reported an all-zero region for the
// uninteresting reason that the mirror is written in run(), not during load.
// That was the first version, and it produced a confident "high-water 0x0"
// that measured the wrong instant. A number taken at the wrong moment is
// worse than no number, because it looks like a finding.
void lodestoneDumpLowRam(const uint8_t *rdram)
{
    if (!std::getenv("PS2X_DUMP_LOW_RAM") || !rdram)
    {
        return;
    }
    constexpr uint32_t kLowEnd = 0x00080000u;
    constexpr uint32_t kKeys[2] = {0x0002A1C88u, 0x0002A1C50u};
    constexpr const char *kKeyNames[2] = {"0x2A1C88 (syscall 0x83)", "0x2A1C50 (syscall 0x5A)"};

    for (int k = 0; k < 2; ++k)
    {
        int32_t hits = 0;
        int32_t firstAt = -1;
        for (uint32_t off = 0u; off + 4u <= kLowEnd; off += 4u)
        {
            if (Ps2FastRead32(rdram, off) == kKeys[k])
            {
                if (firstAt < 0)
                {
                    firstAt = static_cast<int32_t>(off);
                }
                ++hits;
            }
        }
        std::cerr << "[low-ram] key " << kKeyNames[k] << ": " << hits
                  << " occurrence(s) in [0x0, 0x80000)";
        if (firstAt >= 0)
        {
            std::cerr << ", first at physical 0x" << std::hex << firstAt << std::dec;
        }
        else
        {
            std::cerr << "  <-- NOT PRESENT";
        }
        std::cerr << "\n";
    }

    // Where the runtime itself put them, so the two can be compared
    // rather than assumed equal.
    constexpr uint32_t kTableBase = 0x80011F80u & 0x1FFFFFFFu;
    std::cerr << "[low-ram] table base physical 0x" << std::hex << kTableBase
              << "; 0x83 slot 0x" << (kTableBase + 0x83u * 4u)
              << "; 0x5A slot 0x" << (kTableBase + 0x5Au * 4u)
              << "; slot delta 0x" << ((0x83u - 0x5Au) * 4u) << std::dec << "\n";

    uint32_t highWater = 0u;
    for (uint32_t off = 0u; off < kLowEnd; off += 4u)
    {
        if (Ps2FastRead32(rdram, off) != 0u)
        {
            highWater = off + 4u;
        }
    }
    std::cerr << "[low-ram] high-water mark 0x" << std::hex << highWater << std::dec << "\n";
    std::cerr.flush();
}

}

void PS2Runtime::run()
{
    m_stopRequested.store(false, std::memory_order_relaxed);
    ps2_stubs::resetSifState();
    resetIop();
    ps2_stubs::resetAudioStubState();
    ps2_stubs::resetMpegStubState();
    initializeEeKernelState(m_memory.getRDRAM());
    lodestoneDumpLowRam(m_memory.getRDRAM());
    m_cpuContext.r[4] = _mm_setzero_si128();
    m_cpuContext.r[5] = _mm_setzero_si128();
    m_cpuContext.r[29] = _mm_set_epi64x(0, static_cast<int64_t>(PS2_RAM_SIZE - 0x10u));
    m_debugPc.store(m_cpuContext.pc, std::memory_order_relaxed);
    m_debugRa.store(static_cast<uint32_t>(_mm_extract_epi32(m_cpuContext.r[31], 0)), std::memory_order_relaxed);
    m_debugSp.store(static_cast<uint32_t>(_mm_extract_epi32(m_cpuContext.r[29], 0)), std::memory_order_relaxed);
    m_debugGp.store(static_cast<uint32_t>(_mm_extract_epi32(m_cpuContext.r[28], 0)), std::memory_order_relaxed);

    RUNTIME_LOG("Starting execution at address 0x" << std::hex << m_cpuContext.pc << std::dec);

    // A blank image to use as a framebuffer
    Image blank = GenImageColor(FB_WIDTH, FB_HEIGHT, BLANK);
    Texture2D frameTex = LoadTextureFromImage(blank);
    UnloadImage(blank);

    std::atomic<bool> gameThreadFinished{false};

    std::thread gameThread([&]()
                           {
        ThreadNaming::SetCurrentThreadName("GameThread");
        try
        {
            m_eeScheduler->reset(m_memory.getRDRAM(), m_cpuContext);
            m_eeScheduler->run();
            uint32_t pc = m_debugPc.load(std::memory_order_relaxed);
            RUNTIME_LOG("Game thread returned. PC=0x" << std::hex << pc
                      << " RA=0x" << static_cast<uint32_t>(_mm_extract_epi32(m_cpuContext.r[31], 0)) << std::dec << std::endl);
        }
        catch (const std::exception &e)
        {
            std::cerr << "Error during program execution: " << e.what() << std::endl;
        }
        catch (...)
        {
            std::cerr << "Error during program execution: unknown exception" << std::endl;
        }
        gameThreadFinished.store(true, std::memory_order_release); });

    uint64_t tick = 0;
    uint64_t captureTick = 0;
    std::filesystem::path captureDir;
    std::ofstream captureLog;
    std::ofstream captureGsLog;
    uint64_t capturedGsSequence = 0;
    // Bounded dense capture is opt-in; retain the inexpensive default cadence.
    auto captureSetting = [](const char *name, uint64_t fallback) {
        const char *value = std::getenv(name);
        if (!value || !*value) return fallback;
        uint64_t parsed = 0;
        const char *end = value + std::strlen(value);
        const auto result = std::from_chars(value, end, parsed);
        if (result.ec != std::errc{} || result.ptr != end || parsed == 0)
        {
            std::cerr << "[capture:setting] Invalid " << name << "; using default" << std::endl;
            return fallback;
        }
        return parsed;
    };
    const uint64_t captureEvery = captureSetting("PS2X_CAPTURE_EVERY", 120);
    const uint64_t captureFirst = captureSetting("PS2X_CAPTURE_FIRST", 1);
    const uint64_t captureLast = captureSetting("PS2X_CAPTURE_LAST", std::numeric_limits<uint64_t>::max());
    if (const char *directory = std::getenv("PS2X_CAPTURE_DIR"))
    {
        captureDir = directory;
        std::error_code error;
        std::filesystem::create_directories(captureDir, error);
        if (!error)
        {
            captureLog.open(captureDir / "state.jsonl");
            captureGsLog.open(captureDir / "gs-history.jsonl");
            if (captureGsLog)
                m_gs.setDebugHistoryPaused(false);
        }
        if (!captureLog)
            std::cerr << "[capture:error] Could not open diagnostic output directory" << std::endl;
    }
    const auto captureStarted = std::chrono::steady_clock::now();
    while (!isStopRequested() && !gameThreadFinished.load(std::memory_order_acquire))
    {
        m_padBackend.pollHostInput();
        PS2_IF_AGRESSIVE_LOGS({
            tick++;
            if ((tick % 120) == 0)
            {
                uint64_t curDma = m_memory.dmaStartCount();
                uint64_t curGif = m_memory.gifCopyCount();
                uint64_t curGs = m_memory.gsWriteCount();
                uint64_t curVif = m_memory.vifWriteCount();
                const GSRegisters &gs = m_memory.gs();
                const uint32_t dbgPc = m_debugPc.load(std::memory_order_relaxed);
                const uint32_t dbgRa = m_debugRa.load(std::memory_order_relaxed);
                const uint32_t dbgSp = m_debugSp.load(std::memory_order_relaxed);
                const uint32_t dbgGp = m_debugGp.load(std::memory_order_relaxed);
                const auto eeSnapshot = m_eeScheduler->snapshot();

                RUNTIME_LOG("[run:tick] tick=" << tick
                                               << " pc=0x" << std::hex << dbgPc
                                               << " ra=0x" << dbgRa
                                               << " sp=0x" << dbgSp
                                               << " gp=0x" << dbgGp
                                               << " dispfb1=0x" << gs.dispfb1
                                               << " display1=0x" << gs.display1
                                               << std::dec
                                               << " activeThreads=" << eeSnapshot.threads.size()
                                               << " dma=" << curDma
                                               << " gif=" << curGif
                                               << " gsw=" << curGs
                                               << " vif=" << curVif
                                               << std::endl);

            }
        });
        uint32_t presentWidth = FB_WIDTH;
        uint32_t presentHeight = DEFAULT_DISPLAY_HEIGHT;
        UploadFrame(frameTex, this, presentWidth, presentHeight);

        // Opt-in evidence on the presentation thread. EE state comes from its
        // published snapshot; never read the executing guest context here.
        ++captureTick;
        if (captureLog && captureTick >= captureFirst && captureTick <= captureLast &&
            (captureTick == captureFirst || captureTick % captureEvery == 0))
        {
            const auto ee = m_eeScheduler->snapshot();
            const auto gs = m_gs.getDebugSnapshot();
            captureLog << "{\"tick\":" << captureTick
                       << ",\"elapsed_seconds\":" << std::chrono::duration<double>(
                              std::chrono::steady_clock::now() - captureStarted).count()
                       << ",\"host_present_tick\":" << captureTick
                       << ",\"ee_vsync_tick\":" << ee.vsyncTick
                       << ",\"pc\":" << m_debugPc.load(std::memory_order_relaxed)
                       << ",\"ra\":" << m_debugRa.load(std::memory_order_relaxed)
                       << ",\"sequence\":" << ee.sequence
                       << ",\"cycle\":" << ee.eeCycle
                       << ",\"running_thread\":" << ee.runningThreadId
                       << ",\"dma\":" << m_memory.dmaStartCount()
                       << ",\"gif\":" << m_memory.gifCopyCount()
                       << ",\"gs_writes\":" << m_memory.gsWriteCount()
                       << ",\"gs_privileged_writes\":" << m_memory.gsWriteCount()
                       << ",\"vif\":" << m_memory.vifWriteCount()
                       << ",\"ipu_cmds\":" << m_memory.ipu().debugCommands()
                       << ",\"ipu_last_cmd\":" << m_memory.ipu().debugLastCommand()
                       << ",\"ipu_ch3_kicks\":" << m_memory.ipuDmaKickCount(3)
                       << ",\"ipu_ch4_kicks\":" << m_memory.ipuDmaKickCount(4)
                       << ",\"host_frame\":" << (gs.hasHostPresentationFrame ? "true" : "false")
                       << ",\"presentation_vsync_tick\":" << gs.hostPresentationRequest.vsyncTick
                       << ",\"presentation_pmode\":" << gs.hostPresentationRequest.pmode
                       << ",\"presentation_smode2\":" << gs.hostPresentationRequest.smode2
                       << ",\"display_flips\":" << g_ps2DisplayFlips.load(std::memory_order_relaxed)
                       << ",\"presentation_dispfb1\":" << gs.hostPresentationRequest.dispfb1
                       << ",\"presentation_display1\":" << gs.hostPresentationRequest.display1
                       << ",\"presentation_dispfb2\":" << gs.hostPresentationRequest.dispfb2
                       << ",\"presentation_display2\":" << gs.hostPresentationRequest.display2
                       << ",\"presentation_display_fbp\":" << gs.hostPresentationDisplayFbp
                       << ",\"presentation_source_fbp\":" << gs.hostPresentationSourceFbp
                       << ",\"presentation_preferred\":" << (gs.hostPresentationUsedPreferred ? "true" : "false")
                       << ",\"threads\":[";
            for (size_t i = 0; i < ee.threads.size(); ++i)
            {
                const auto &thread = ee.threads[i];
                if (i) captureLog << ',';
                captureLog << "{\"id\":" << thread.id << ",\"pc\":" << thread.pc
                           << ",\"ra\":" << thread.ra << ",\"status\":" << static_cast<int>(thread.status)
                           << ",\"wait_reason\":" << static_cast<int>(thread.waitReason)
                           << ",\"wait_id\":" << thread.waitId << '}';
            }
            captureLog << "],\"semaphores\":[";
            for (size_t i = 0; i < ee.semaphores.size(); ++i)
            {
                const auto &semaphore = ee.semaphores[i];
                if (i) captureLog << ',';
                captureLog << "{\"id\":" << semaphore.id << ",\"count\":" << semaphore.count
                           << ",\"waiters\":" << semaphore.waiters << '}';
            }
            captureLog << "]}" << std::endl;
            // GS MMIO writes do not count drawing-register writes received via
            // GIF. Preserve the frontend's bounded, mutex-protected history so
            // black-frame diagnosis can distinguish tags, registers and draws.
            if (captureGsLog)
            {
                const auto history = m_gs.getDebugHistory();
                if (!history.empty() && history.back().seq < capturedGsSequence)
                {
                    captureGsLog << "{\"kind\":\"reset\",\"previous_seq\":" << capturedGsSequence << "}\n";
                    capturedGsSequence = 0;
                }
                if (!history.empty() && history.front().seq > capturedGsSequence + 1u)
                    captureGsLog << "{\"kind\":\"gap\",\"after_seq\":" << capturedGsSequence
                                 << ",\"first_available_seq\":" << history.front().seq << "}\n";
                for (const auto &event : history)
                {
                    if (event.seq <= capturedGsSequence)
                        continue;
                    captureGsLog << "{\"seq\":" << event.seq
                                 << ",\"tick\":" << event.vsyncTick
                                 << ",\"kind\":" << static_cast<unsigned>(event.kind)
                                 << ",\"reg\":" << static_cast<unsigned>(event.reg)
                                 << ",\"value\":" << event.regValue
                                 << ",\"gif_bytes\":" << event.gifSizeBytes
                                 << ",\"nloop\":" << event.gifNloop
                                 << ",\"flg\":" << static_cast<unsigned>(event.gifFlg)
                                 << ",\"nreg\":" << static_cast<unsigned>(event.gifNreg)
                                 << ",\"vertices\":" << event.vertexCount
                                 << ",\"frame_fbp\":" << event.frame.fbp
                                 << ",\"frame_fbw\":" << event.frame.fbw
                                 << ",\"frame_psm\":" << static_cast<unsigned>(event.frame.psm)
                                 << ",\"frame_mask\":" << event.frame.fbmsk
                                 << ",\"prim\":" << static_cast<unsigned>(event.prim.type)
                                 << ",\"textured\":" << (event.prim.tme ? "true" : "false")
                                 << ",\"alpha_min\":" << static_cast<unsigned>(event.aMin)
                                 << ",\"alpha_max\":" << static_cast<unsigned>(event.aMax)
                                 << ",\"display_fbp\":" << event.displayFbp
                                 << ",\"source_fbp\":" << event.sourceFbp
                                 << ",\"width\":" << event.width
                                 << ",\"height\":" << event.height
                                 << ",\"preferred\":" << (event.usedPreferred ? "true" : "false")
                                 << ",\"xy_bounds\":[";
                    const std::array<float, 4> bounds{event.xMin, event.xMax, event.yMin, event.yMax};
                    for (size_t i = 0; i < bounds.size(); ++i)
                    {
                        if (i) captureGsLog << ',';
                        if (std::isfinite(bounds[i])) captureGsLog << bounds[i];
                        else captureGsLog << "null";
                    }
                    captureGsLog << "]}\n";
                    capturedGsSequence = event.seq;
                }
                captureGsLog.flush();
            }
            std::vector<uint8_t> pixels;
            uint32_t width = 0, height = 0;
            if (m_gs.copyLatchedHostPresentationFrame(pixels, width, height) && !pixels.empty())
            {
                Image frame{pixels.data(), static_cast<int>(width), static_cast<int>(height), 1,
                            PIXELFORMAT_UNCOMPRESSED_R8G8B8A8};
                const auto file = captureDir / ("frame-" + std::to_string(captureTick) + ".png");
                if (!ExportImage(frame, file.string().c_str()))
                    std::cerr << "[capture:error] Could not export game frame" << std::endl;
            }
        }

        BeginDrawing();
        ClearBackground(BLACK);
        const float srcWidth = static_cast<float>(std::max<uint32_t>(1u, presentWidth));
        const float srcHeight = static_cast<float>(std::max<uint32_t>(1u, presentHeight));
        const float screenWidth = static_cast<float>(GetScreenWidth());
        const float screenHeight = static_cast<float>(GetScreenHeight());
        const float scale = std::min(screenWidth / srcWidth, screenHeight / srcHeight);
        const float dstWidth = srcWidth * scale;
        const float dstHeight = srcHeight * scale;
        const Rectangle srcRect{0.0f, 0.0f, srcWidth, srcHeight};
        const Rectangle dstRect{
            (screenWidth - dstWidth) * 0.5f,
            (screenHeight - dstHeight) * 0.5f,
            dstWidth,
            dstHeight};
        DrawTexturePro(frameTex, srcRect, dstRect, Vector2{0.0f, 0.0f}, 0.0f, WHITE);
        if (m_debugUiInitialized && m_debugUiDrawCallback)
        {
            m_debugUiDrawCallback(*this, m_debugUiUserData);
        }
        EndDrawing();

        if (WindowShouldClose())
        {
            RUNTIME_LOG("[run] window close requested, breaking out of loop");
            requestStop();
            break;
        }
    }

    requestStop();
    if (gameThread.joinable())
    {
        gameThread.join();
    }

    if (m_debugUiInitialized && m_debugUiShutdownCallback)
    {
        m_debugUiShutdownCallback(*this, m_debugUiUserData);
        m_debugUiInitialized = false;
    }
    UnloadTexture(frameTex);
    CloseWindow();

    RUNTIME_LOG("[run] exiting loop");
}

// Record the actual Windows playback endpoint with WASAPI loopback.
// miniaudio (MIT/public domain) is already bundled with raylib in this project.
// No microphone is opened. Optional --device selects a playback endpoint.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_GENERATION
#define MA_NO_MP3
#define MA_NO_FLAC
#include "miniaudio.h"

#include <atomic>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cwchar>
#include <cstring>
#include <filesystem>
#include <thread>
#include <vector>

namespace
{
    std::atomic<bool> stopped{false};
    BOOL WINAPI control(DWORD event)
    {
        if (event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT || event == CTRL_CLOSE_EVENT)
        {
            stopped.store(true);
            return TRUE;
        }
        return FALSE;
    }
    struct Capture
    {
        explicit Capture(ma_uint64 capacityFrames = 48000u * 4u)
            : capacity(capacityFrames), ring(static_cast<size_t>(capacityFrames) * 2u) {}
        ma_encoder encoder{};
        const ma_uint64 capacity;
        std::vector<ma_int16> ring;
        std::atomic<ma_uint64> produced{0}, consumed{0}, overflowFrames{0}, nullFrames{0};
        std::atomic<bool> failed{false};
        std::atomic<bool> finished{false};
        bool timing = false;
        std::atomic<long long> firstPacketUnixNs{0}, lastPacketUnixNs{0};
        std::atomic<ma_uint64> lastPacketStart{0}, lastPacketFrames{0};
        ma_uint64 limit = 0;
    };
    static_assert(std::atomic<ma_uint64>::is_always_lock_free);
    void receive(ma_device* device, void*, const void* input, ma_uint32 count)
    {
        auto& capture = *static_cast<Capture*>(device->pUserData);
        const ma_uint64 current = capture.produced.load(std::memory_order_relaxed);
        if (current >= capture.limit || capture.failed.load()) return;
        const ma_uint64 requested = std::min<ma_uint64>(count, capture.limit - current);
        if (capture.timing)
        {
            // Delivery time, not the WASAPI hardware position. Publish only
            // numbers here; log them after the callback has been joined.
            const auto now = std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            if (!current) capture.firstPacketUnixNs.store(now, std::memory_order_relaxed);
            capture.lastPacketUnixNs.store(now, std::memory_order_relaxed);
            capture.lastPacketStart.store(current, std::memory_order_relaxed);
            capture.lastPacketFrames.store(requested, std::memory_order_relaxed);
        }
        const ma_uint64 read = capture.consumed.load(std::memory_order_acquire);
        if (requested > capture.capacity - (current - read))
        {
            capture.overflowFrames.fetch_add(requested);
            capture.failed.store(true);
            return; // Never block the audio thread or silently join dropped packets.
        }
        const ma_uint64 index = current % capture.capacity;
        const ma_uint64 first = std::min(requested, capture.capacity - index);
        ma_int16* target = capture.ring.data() + index * 2u;
        if (input)
        {
            const auto* source = static_cast<const ma_int16*>(input);
            std::memcpy(target, source, static_cast<size_t>(first) * 4u);
            std::memcpy(capture.ring.data(), source + first * 2u, static_cast<size_t>(requested - first) * 4u);
        }
        else
        {
            std::memset(target, 0, static_cast<size_t>(first) * 4u);
            std::memset(capture.ring.data(), 0, static_cast<size_t>(requested - first) * 4u);
            capture.nullFrames.fetch_add(requested);
        }
        capture.produced.store(current + requested, std::memory_order_release);
    }
    void writeQueued(Capture& capture)
    {
        for (;;)
        {
            const ma_uint64 read = capture.consumed.load(std::memory_order_relaxed);
            const ma_uint64 write = capture.produced.load(std::memory_order_acquire);
            if (read == write)
            {
                // The producer may publish its final packet between the two
                // loads. Acquiring finished then re-reading the write position
                // ensures shutdown drains that packet too.
                if (capture.finished.load(std::memory_order_acquire) &&
                    capture.produced.load(std::memory_order_acquire) == read) return;
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }
            const ma_uint64 index = read % capture.capacity;
            const ma_uint64 requested = std::min({write - read, capture.capacity - index, ma_uint64(4096)});
            ma_uint64 written = 0;
            const ma_result result = ma_encoder_write_pcm_frames(&capture.encoder,
                capture.ring.data() + index * 2u, requested, &written);
            capture.consumed.store(read + written, std::memory_order_release);
            if (result != MA_SUCCESS || written != requested)
            {
                capture.failed.store(true);
                return;
            }
        }
    }
    int selfTestRecording(const wchar_t* path, ma_uint64 frames, bool timing)
    {
        Capture capture(1024); // Force wraparound with many unequal packet sizes.
        capture.timing = timing;
        capture.limit = frames;
        const ma_encoder_config config = ma_encoder_config_init(ma_encoding_format_wav, ma_format_s16, 2, 48000);
        if (ma_encoder_init_file_w(path, &config, &capture.encoder) != MA_SUCCESS) return 1;
        std::thread writer([&] { writeQueued(capture); });
        ma_device dummy{};
        dummy.pUserData = &capture;
        ma_int16 data[512]{};
        while (capture.produced.load() < frames && !capture.failed.load())
        {
            const ma_uint64 start = capture.produced.load();
            const ma_uint32 count = static_cast<ma_uint32>(std::min(frames - start, 17u + (start * 19u) % 239u));
            while (capture.capacity - (start - capture.consumed.load(std::memory_order_acquire)) < count && !capture.failed.load())
                std::this_thread::yield();
            for (ma_uint32 i = 0; i < count; ++i)
            {
                data[i * 2u] = static_cast<ma_int16>(int((start + i) * 73u % 60001u) - 30000);
                data[i * 2u + 1u] = static_cast<ma_int16>(int((start + i) * 37u % 50021u) - 25010);
            }
            receive(&dummy, nullptr, data, count);
        }
        capture.finished.store(true, std::memory_order_release);
        writer.join();
        ma_encoder_uninit(&capture.encoder);
        Capture overflow(8);
        overflow.limit = 16;
        dummy.pUserData = &overflow;
        receive(&dummy, nullptr, data, 16);
        const bool guarded = overflow.failed.load() && overflow.overflowFrames.load() == 16 && overflow.produced.load() == 0;
        Capture silence(8);
        silence.limit = 4;
        std::fill(silence.ring.begin(), silence.ring.end(), 123);
        dummy.pUserData = &silence;
        receive(&dummy, nullptr, nullptr, 4);
        const bool nullSafe = silence.produced.load() == 4 && silence.nullFrames.load() == 4 &&
            std::all_of(silence.ring.begin(), silence.ring.begin() + 8, [](ma_int16 v) { return v == 0; });
        std::printf("Queue self-test: %llu frames, overflow guard=%d, silence=%d. No audio device opened.\n",
            static_cast<unsigned long long>(capture.consumed.load()), guarded, nullSafe);
        const bool timed = !timing || (capture.firstPacketUnixNs.load() > 0 &&
            capture.lastPacketUnixNs.load() >= capture.firstPacketUnixNs.load() &&
            capture.lastPacketStart.load() + capture.lastPacketFrames.load() == frames);
        std::printf("Delivery timing self-test=%d\n", timed);
        return !capture.failed.load() && capture.consumed.load() == frames && guarded && nullSafe && timed ? 0 : 1;
    }
}

int wmain(int argc, wchar_t** argv)
{
    const wchar_t* path = nullptr;
    const wchar_t* stopFile = nullptr;
    double seconds = 60;
    int deviceIndex = -1;
    bool list = false;
    bool selfTest = false;
    bool timing = false;
    for (int i = 1; i < argc; ++i)
    {
        if (!std::wcscmp(argv[i], L"--list")) list = true;
        else if (!std::wcscmp(argv[i], L"--self-test")) selfTest = true;
        else if (!std::wcscmp(argv[i], L"--timing")) timing = true;
        else if (!std::wcscmp(argv[i], L"--out") && i + 1 < argc) path = argv[++i];
        else if (!std::wcscmp(argv[i], L"--stop-file") && i + 1 < argc) stopFile = argv[++i];
        else if (!std::wcscmp(argv[i], L"--seconds") && i + 1 < argc)
        {
            wchar_t* end = nullptr;
            seconds = std::wcstod(argv[++i], &end);
            if (end == argv[i] || *end || !std::isfinite(seconds) || seconds * 48000 < 1 || seconds > 3600) return 2;
        }
        else if (!std::wcscmp(argv[i], L"--device") && i + 1 < argc)
        {
            wchar_t* end = nullptr;
            const long parsed = std::wcstol(argv[++i], &end, 10);
            if (end == argv[i] || *end || parsed < 0 || parsed > 10000) return 2;
            deviceIndex = static_cast<int>(parsed);
        }
        else
        {
            std::fprintf(stderr, "usage: capture_speakers --out NEW.wav [--seconds 60] [--device N] [--timing] [--stop-file NEW.flag] | --list\n");
            return 2;
        }
    }
    if (!list && (!path || std::filesystem::exists(path)))
    {
        std::fprintf(stderr, "Choose a new output WAV; existing recordings are never overwritten.\n");
        return 2;
    }
    if (stopFile && std::filesystem::exists(stopFile))
    {
        std::fprintf(stderr, "Stop file must not exist before recording starts.\n");
        return 2;
    }
    if (selfTest) return list ? 2 : selfTestRecording(path, static_cast<ma_uint64>(seconds * 48000), timing);
    ma_context context{};
    const ma_backend backend = ma_backend_wasapi;
    ma_result result = ma_context_init(&backend, 1, nullptr, &context);
    if (result != MA_SUCCESS) { std::fprintf(stderr, "WASAPI context error %d\n", result); return 1; }
    ma_device_info* playback = nullptr;
    ma_uint32 playbackCount = 0;
    result = ma_context_get_devices(&context, &playback, &playbackCount, nullptr, nullptr);
    if (result != MA_SUCCESS) { ma_context_uninit(&context); return 1; }
    if (list)
    {
        for (ma_uint32 i = 0; i < playbackCount; ++i)
            std::printf("%u: %s%s\n", i, playback[i].name, playback[i].isDefault ? " [default]" : "");
        ma_context_uninit(&context);
        return 0;
    }
    if (deviceIndex >= static_cast<int>(playbackCount))
    {
        std::fprintf(stderr, "Playback endpoint does not exist; use --list.\n");
        ma_context_uninit(&context);
        return 2;
    }
    Capture capture;
    capture.timing = timing;
    capture.limit = static_cast<ma_uint64>(seconds * 48000);
    ma_device_config config = ma_device_config_init(ma_device_type_loopback);
    config.capture.pDeviceID = deviceIndex >= 0 ? &playback[deviceIndex].id : nullptr;
    config.capture.format = ma_format_s16;
    config.capture.channels = 2;
    config.sampleRate = 48000;
    config.dataCallback = receive;
    config.pUserData = &capture;
    ma_device device{};
    result = ma_device_init(&context, &config, &device);
    if (result != MA_SUCCESS)
    {
        std::fprintf(stderr, "Speaker loopback init error %d\n", result);
        ma_context_uninit(&context);
        return 1;
    }
    const ma_encoder_config encoder = ma_encoder_config_init(ma_encoding_format_wav, ma_format_s16, 2, 48000);
    result = ma_encoder_init_file_w(path, &encoder, &capture.encoder);
    if (result != MA_SUCCESS)
    {
        std::fprintf(stderr, "Cannot open recording: %d\n", result);
        ma_device_uninit(&device); ma_context_uninit(&context);
        return 1;
    }
    std::printf("Recording speaker endpoint: %s (48000 Hz stereo). No microphone. Ctrl+C stops.\n", device.capture.name);
    SetConsoleCtrlHandler(control, TRUE);
    std::thread writer([&] { writeQueued(capture); });
    result = ma_device_start(&device);
    const auto start = std::chrono::steady_clock::now();
    bool signaled = false;
    while (result == MA_SUCCESS && !stopped.load() && !capture.failed.load() && capture.produced.load() < capture.limit &&
           std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() < seconds + 2.0)
    {
        if (stopFile && std::filesystem::is_regular_file(stopFile))
        {
            signaled = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    ma_device_uninit(&device); // Joins the callback before closing the WAV.
    capture.finished.store(true, std::memory_order_release);
    writer.join();
    ma_encoder_uninit(&capture.encoder);
    ma_context_uninit(&context);
    SetConsoleCtrlHandler(control, FALSE);
    const ma_uint64 frames = capture.consumed.load();
    std::printf("Stop reason: %s.\n", signaled ? "external signal" : stopped.load() ? "console control" :
        frames >= capture.limit ? "frame limit" : "wall deadline or error");
    std::printf("Saved %llu frames (%.3f seconds). Queue overflow=%llu, null input=%llu frames.\n",
        static_cast<unsigned long long>(frames), frames / 48000.0,
        static_cast<unsigned long long>(capture.overflowFrames.load()),
        static_cast<unsigned long long>(capture.nullFrames.load()));
    if (timing)
        std::printf("Delivery timing: first_unix_ns=%lld last_unix_ns=%lld last_start_frame=%llu last_frames=%llu. Callback delivery observations, not hardware sample timestamps.\n",
            capture.firstPacketUnixNs.load(), capture.lastPacketUnixNs.load(),
            static_cast<unsigned long long>(capture.lastPacketStart.load()),
            static_cast<unsigned long long>(capture.lastPacketFrames.load()));
    if (result != MA_SUCCESS || capture.failed.load() || !frames || (!signaled && !stopped.load() && frames < capture.limit))
    {
        std::fprintf(stderr, "Recording incomplete or empty (device start=%d, write error=%d).\n", result, capture.failed.load());
        return 1;
    }
    return 0;
}

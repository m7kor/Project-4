// audio_lab: replay a raw SPU2 capture through the runtime's host audio path.
//
// Input: <prefix>-spu2.wav written by the runner with PS2X_AUDIO_WAV (the SPU2
// mix in emulation time: what the game sounds like at true speed). The tool
// simulates the emulator delivering it at --speed of real time, in bursts of
// one host frame, and an audio device pulling configurable blocks in real time:
//
//   <out>-truespeed.wav   the capture itself (reference: the intended sound)
//   <out>-soundtouch.wav  runtime path: SoundTouch + PCSX2 tempo controller
//   <out>-gaps.wav        no stretching (what a slow emulator sounds like raw)
//
// and prints underruns, tempo, clicks and clipping for each, so changes to the
// audio path can be judged by measurement as well as by ear.
//
//   tools\audio\build_audio_lab.ps1
//   artifacts\tools\audio_lab.exe run3-spu2.wav out\run3 --speed 0.5 [--jitter 0.15] [--seconds 60]

#include "../../core/ps2xRuntime/src/lib/audio/host_audio_stretch.h"

#include <cstdio>
#include <cmath>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

namespace
{
    bool readWav(const char *path, std::vector<int16_t> &out, uint32_t &rate)
    {
        FILE *f = std::fopen(path, "rb");
        if (!f)
            return false;
        char id[4];
        uint32_t size = 0;
        std::fread(id, 1, 4, f);
        std::fread(&size, 4, 1, f);
        std::fread(id, 1, 4, f);
        uint16_t channels = 0, bits = 0;
        bool ok = false;
        while (std::fread(id, 1, 4, f) == 4 && std::fread(&size, 4, 1, f) == 1)
        {
            if (!std::memcmp(id, "fmt ", 4))
            {
                uint16_t format = 0;
                std::fread(&format, 2, 1, f);
                std::fread(&channels, 2, 1, f);
                std::fread(&rate, 4, 1, f);
                std::fseek(f, 6, SEEK_CUR);
                std::fread(&bits, 2, 1, f);
                std::fseek(f, static_cast<long>(size) - 16, SEEK_CUR);
            }
            else if (!std::memcmp(id, "data", 4))
            {
                if (channels != 2 || bits != 16)
                    break;
                // A capture cut short by a killed process may claim zero or a
                // stale size; read what is there.
                std::vector<int16_t> data;
                int16_t block[4096];
                size_t n;
                while ((n = std::fread(block, 2, 4096, f)) > 0)
                    data.insert(data.end(), block, block + n);
                data.resize(data.size() & ~size_t(1));
                out.swap(data);
                ok = true;
                break;
            }
            else
            {
                std::fseek(f, static_cast<long>(size + (size & 1u)), SEEK_CUR);
            }
        }
        std::fclose(f);
        return ok;
    }

    void writeWav(const std::string &path, const std::vector<int16_t> &pcm, uint32_t rate)
    {
        FILE *f = std::fopen(path.c_str(), "wb");
        if (!f)
            return;
        const uint32_t data = static_cast<uint32_t>(pcm.size() * 2u), riff = 36u + data, fmt = 16u, byteRate = rate * 4u;
        const uint16_t pcmFormat = 1u, channels = 2u, align = 4u, bits = 16u;
        std::fwrite("RIFF", 1, 4, f); std::fwrite(&riff, 4, 1, f);
        std::fwrite("WAVEfmt ", 1, 8, f); std::fwrite(&fmt, 4, 1, f);
        std::fwrite(&pcmFormat, 2, 1, f); std::fwrite(&channels, 2, 1, f);
        std::fwrite(&rate, 4, 1, f); std::fwrite(&byteRate, 4, 1, f);
        std::fwrite(&align, 2, 1, f); std::fwrite(&bits, 2, 1, f);
        std::fwrite("data", 1, 4, f); std::fwrite(&data, 4, 1, f);
        std::fwrite(pcm.data(), 2, pcm.size(), f);
        std::fclose(f);
    }

    struct Stats
    {
        uint64_t frames = 0, silentInSound = 0, clicks = 0, clipped = 0;
    };

    // Clicks: a sample-to-sample jump far above the recent slope.
    Stats measure(const std::vector<int16_t> &pcm)
    {
        Stats s;
        s.frames = pcm.size() / 2u;
        double slope = 50.0, level = 0.0;
        for (size_t i = 1; i < s.frames; ++i)
        {
            const int a = pcm[(i - 1) * 2], b = pcm[i * 2];
            const double d = std::abs(b - a);
            if (d > 2000.0 && d > 12.0 * slope)
                ++s.clicks;
            slope = slope * 0.995 + d * 0.005;
            level = level * 0.999 + std::abs(b) * 0.001;
            if (std::abs(b) >= 32700)
                ++s.clipped;
            if (level > 300.0 && std::abs(b) < 4 && std::abs(a) < 4)
                ++s.silentInSound;
        }
        return s;
    }

    void report(const char *name, const std::vector<int16_t> &pcm, uint64_t underrunFrames, double tempo, uint32_t rate)
    {
        const Stats s = measure(pcm);
        std::printf("%-12s %7.1f s  underrun %6.2f%%  silent-in-sound %6.2f%%  clicks/min %6.1f  clipped %llu  tempo %.3f\n",
                    name, s.frames / double(rate), 100.0 * underrunFrames / std::max<uint64_t>(1, s.frames),
                    100.0 * s.silentInSound / std::max<uint64_t>(1, s.frames),
                    s.clicks * 60.0 / std::max(1.0, s.frames / double(rate)),
                    static_cast<unsigned long long>(s.clipped), tempo);
    }

    // Exercise the measured intro/radio/forest rates in one continuous
    // stream. Independent tones catch pitch changes and channel duplication;
    // fixed-rate tests alone cannot check recovery after a scene transition.
    int transitionTest(bool trace = false)
    {
        unsigned failures = 0;
        for (const uint32_t blockFrames : {480u, 1024u})
        for (const bool bursts : {false, true})
        {
            HostAudioSoundTouch stretcher;
            std::mt19937 rng(29171);
            std::uniform_real_distribution<double> jitter(0.8, 1.2);
            std::vector<int16_t> source(2400u * 2u), block(blockFrames * 2u);
            uint64_t phase = 0;
            double owed = 0.0, devicePhase = 0.0;
            for (const double speed : {1.0, 0.97, 0.42, 0.31, 1.0})
            {
                uint64_t demand = 0, missing = 0;
                std::array<uint64_t, 2> crossings{}, audible{};
                std::array<int16_t, 2> previous{};
                double tempo = 0;
                double sourceRate = 0, appliedTempo = 0, fullness = 0;
                uint64_t produced = 0;
                unsigned blocks = 0;
                for (unsigned tick = 0; tick < 900; ++tick)
                {
                    owed += 800.0 * speed * jitter(rng) *
                        (bursts ? (tick % 24 < 12 ? 0.0 : 2.0) : 1.0);
                    const auto count = static_cast<uint32_t>(owed);
                    owed -= count;
                    if (tick >= 480) produced += count;
                    for (uint32_t i = 0; i < count; ++i, ++phase)
                    {
                        source[i * 2u] = static_cast<int16_t>(4000.0 * std::sin(
                            double(phase) * (2.0 * 3.141592653589793 * 380.0 / 48000.0)));
                        source[i * 2u + 1u] = static_cast<int16_t>(2300.0 * std::sin(
                            double(phase) * (2.0 * 3.141592653589793 * 730.0 / 48000.0)));
                    }
                    stretcher.push(source.data(), count);
                    devicePhase += 800;
                    while (devicePhase >= blockFrames)
                    {
                        devicePhase -= blockFrames;
                        const uint32_t got = stretcher.pull(block.data(), blockFrames);
                        // Allow eight seconds for controller and stretch
                        // buffers to settle, then measure seven seconds.
                        if (tick < 480) continue;
                        demand += blockFrames;
                        missing += blockFrames - got;
                        tempo += stretcher.tempo();
                        if (trace) {
                            const auto state = stretcher.diagnostics();
                            sourceRate += state.sourceRate;
                            appliedTempo += state.appliedTempo;
                            fullness += state.queuedFrames / double(state.targetFrames);
                        }
                        ++blocks;
                        for (uint32_t i = 0; i < blockFrames; ++i)
                        for (uint32_t ch = 0; ch < 2; ++ch)
                        {
                            const int16_t sample = block[i * 2u + ch];
                            crossings[ch] += previous[ch] <= 0 && sample > 0;
                            audible[ch] += std::abs(int(sample)) > 100;
                            previous[ch] = sample;
                        }
                    }
                }
                const double seconds = double(demand) / 48000.0;
                const double leftHz = crossings[0] / seconds, rightHz = crossings[1] / seconds;
                const double meanTempo = tempo / blocks;
                const double missingRatio = double(missing) / demand;
                const bool ok = missingRatio < 0.01 && std::abs(meanTempo - speed) < 0.035 &&
                    std::abs(leftHz / 380.0 - 1.0) < 0.02 &&
                    std::abs(rightHz / 730.0 - 1.0) < 0.02 &&
                    double(audible[0]) / demand > 0.85 && double(audible[1]) / demand > 0.85;
                std::printf("%s transition speed=%.2f block=%u bursts=%d tempo=%.4f missing=%.4f%% pitch=%.2f/%.2f Hz\n",
                    ok ? "PASS" : "FAIL", speed, blockFrames, bursts, meanTempo,
                    missingRatio * 100.0, leftHz, rightHz);
                failures += !ok;
                if (trace)
                    std::printf("TRACE speed=%.2f block=%u bursts=%d produced_rate=%.6f filtered_rate=%.6f applied_tempo=%.6f post_pull_fullness=%.6f\n",
                        speed, blockFrames, bursts, double(produced) / demand, sourceRate / blocks, appliedTempo / blocks, fullness / blocks);
            }
        }
        return failures ? 1 : 0;
    }

    // Stop a previously steady producer. A partial device block must retain
    // the pitch of each channel; filling missing time by resampling changes it.
    int starvationPitchTest()
    {
        unsigned checked = 0, failures = 0;
        for (const uint32_t blockFrames : {480u, 1024u, 2048u, 4096u})
        {
            HostAudioSoundTouch stretcher;
            std::vector<int16_t> source(800u * 2u), block(blockFrames * 2u);
            uint64_t phase = 0;
            uint32_t devicePending = 0;
            for (unsigned tick = 0; tick < 600; ++tick)
            {
                for (uint32_t i = 0; i < 800; ++i, ++phase)
                {
                    source[i * 2u] = static_cast<int16_t>(4000 * std::sin(phase * 2 * 3.141592653589793 * 1000 / 48000));
                    source[i * 2u + 1u] = static_cast<int16_t>(2500 * std::sin(phase * 2 * 3.141592653589793 * 2000 / 48000));
                }
                stretcher.push(source.data(), 800);
                devicePending += 800;
                while (devicePending >= blockFrames)
                {
                    devicePending -= blockFrames;
                    stretcher.pull(block.data(), blockFrames);
                }
            }
            // Fill once more, release refill mode with a small read, then
            // request more than the remaining output to force a partial block.
            source.resize(8192u * 2u);
            for (uint32_t i = 0; i < 8192; ++i, ++phase)
            {
                source[i * 2u] = static_cast<int16_t>(4000 * std::sin(phase * 2 * 3.141592653589793 * 1000 / 48000));
                source[i * 2u + 1u] = static_cast<int16_t>(2500 * std::sin(phase * 2 * 3.141592653589793 * 2000 / 48000));
            }
            stretcher.push(source.data(), 8192);
            stretcher.pull(block.data(), 64);
            constexpr uint32_t demandFrames = 16384;
            block.resize(demandFrames * 2u);
            for (unsigned tick = 0; tick < 10; ++tick)
            {
                const uint32_t got = stretcher.pull(block.data(), demandFrames);
                if (got < 512 || got >= demandFrames * 0.95) continue;
                bool ok = true;
                double measured[2]{};
                for (uint32_t ch = 0; ch < 2; ++ch)
                {
                    std::vector<double> crossings, periods;
                    for (uint32_t i = 1; i < got; ++i)
                    {
                        const double a = block[(i - 1u) * 2u + ch], b = block[i * 2u + ch];
                        if (a <= 0 && b > 0) crossings.push_back(i - 1u - a / (b - a));
                    }
                    for (size_t i = 1; i < crossings.size(); ++i)
                        periods.push_back(crossings[i] - crossings[i - 1]);
                    if (periods.size() < 3) { ok = false; continue; }
                    std::sort(periods.begin(), periods.end());
                    measured[ch] = 48000 / periods[periods.size() / 2];
                    ok &= std::abs(measured[ch] / (ch ? 2000 : 1000) - 1) < 0.05;
                }
                std::printf("%s starvation warm-block=%u request=%u got=%u pitch=%.2f/%.2f Hz expected=1000/2000\n",
                    ok ? "PASS" : "FAIL", blockFrames, demandFrames, got, measured[0], measured[1]);
                ++checked;
                failures += !ok;
            }
        }
        std::printf("Starvation pitch: checked=%u failures=%u\n", checked, failures);
        return checked >= 2 && !failures ? 0 : 1;
    }

    int selfTest()
    {
        unsigned failures = 0;
        for (const uint32_t blockFrames : {480u, 1024u})
        for (const double speed : {1.0, 0.5, 0.22})
        for (const bool bursts : {false, true})
        {
            HostAudioSoundTouch stretcher;
            std::mt19937 rng(1234);
            std::uniform_real_distribution<double> jitter(-0.5, 0.5);
            std::vector<int16_t> source(2400u * 2u), block(blockFrames * 2u);
            uint64_t phase = 0, lateMissing = 0, lateDemand = 0;
            double owed = 0.0, devicePhase = 0.0;
            double lateTempo = 0.0;
            uint32_t lateBlocks = 0;
            bool linked = true;
            if (stretcher.pull(block.data(), 0) != 0) ++failures;
            for (unsigned tick = 0; tick < 1200; ++tick)
            {
                owed += 800.0 * speed * (1.0 + jitter(rng)) * (bursts ? (tick % 24 < 12 ? 0.0 : 2.0) : 1.0);
                const uint32_t count = static_cast<uint32_t>(owed);
                owed -= count;
                for (uint32_t i = 0; i < count; ++i, ++phase)
                {
                    const int16_t value = static_cast<int16_t>(4000.0 * std::sin(double(phase) * 0.039269908));
                    source[i * 2u] = value;
                    source[i * 2u + 1u] = -value;
                }
                stretcher.push(source.data(), count);
                devicePhase += 800;
                while (devicePhase >= blockFrames)
                {
                    devicePhase -= blockFrames;
                    const uint32_t got = stretcher.pull(block.data(), blockFrames);
                    if (tick >= 300)
                    {
                        lateDemand += blockFrames; lateMissing += blockFrames - got;
                        lateTempo += stretcher.tempo(); ++lateBlocks;
                    }
                    for (uint32_t i = 0; i < blockFrames; ++i)
                        linked &= int(block[i * 2u]) + int(block[i * 2u + 1u]) == 0;
                }
            }
            const double missing = double(lateMissing) / lateDemand;
            const double meanTempo = lateTempo / lateBlocks;
            const bool ok = linked && missing < 0.01 && std::fabs(meanTempo - speed) < 0.08;
            std::printf("%s speed=%.2f block=%u bursts=%d late-underrun=%.4f%% linked=%d tempo=%.3f\n",
                ok ? "PASS" : "FAIL", speed, blockFrames, bursts, missing * 100.0, linked, meanTempo);
            if (!ok) ++failures;
            // A stopped producer must eventually produce silence, without
            // replaying old samples or changing stereo alignment.
            for (unsigned i = 0; i < 500; ++i) stretcher.pull(block.data(), blockFrames);
            for (int16_t value : block) if (value != 0) { ++failures; break; }
        }
        return failures ? 1 : 0;
    }
}

int main(int argc, char **argv)
{
    if (argc == 2 && std::string(argv[1]) == "--self-test") return selfTest();
    if (argc == 2 && std::string(argv[1]) == "--transition-test") return transitionTest();
    if (argc == 2 && std::string(argv[1]) == "--transition-trace") return transitionTest(true);
    if (argc == 2 && std::string(argv[1]) == "--starvation-pitch-test") return starvationPitchTest();
    if (argc < 3)
    {
        std::fprintf(stderr, "usage: audio_lab <capture-spu2.wav> <out-prefix> [--speed S] [--jitter J] [--seconds N] [--block-frames N]\n");
        return 2;
    }
    double speed = 0.5, jitter = 0.15, seconds = 1e9;
    uint32_t blockFrames = 1024u;
    if ((argc - 3) % 2) return 2;
    for (int i = 3; i + 1 < argc; i += 2)
    {
        const std::string option = argv[i];
        char *end = nullptr;
        const double value = std::strtod(argv[i + 1], &end);
        if (end == argv[i + 1] || *end || !std::isfinite(value)) return 2;
        if (option == "--speed" && value >= 0.05 && value <= 10.0) speed = value;
        else if (option == "--jitter" && value >= 0.0 && value < 1.0) jitter = value;
        else if (option == "--seconds" && value > 0.0 && value <= 3600.0) seconds = value;
        else if (option == "--block-frames" && value >= 1.0 && value <= 8192.0 && std::floor(value) == value)
            blockFrames = static_cast<uint32_t>(value);
        else return 2;
    }
    std::vector<int16_t> raw;
    uint32_t rate = 48000;
    if (!readWav(argv[1], raw, rate))
    {
        std::fprintf(stderr, "cannot read %s (16-bit stereo WAV expected)\n", argv[1]);
        return 1;
    }
    const size_t total = std::min<size_t>(raw.size() / 2u, static_cast<size_t>(seconds * rate));
    const std::string prefix = argv[2];
    writeWav(prefix + "-truespeed.wav", std::vector<int16_t>(raw.begin(), raw.begin() + total * 2u), rate);

    // Simulation: one host frame = 1/60 s of real time; the emulator delivers
    // speed*(1 +/- jitter) of that in SPU2 frames; the device pulls 1024-frame
    // blocks at the real-time rate.
    HostAudioSoundTouch stretcher(rate);
    std::vector<int16_t> outStretch, outGaps, gapsFifo;
    std::mt19937 rng(1234);
    std::uniform_real_distribution<double> wobble(-jitter, jitter);
    size_t produced = 0;
    double owed = 0.0, devicePhase = 0.0, tempoSum = 0.0;
    uint64_t tempoCount = 0, underrunStretch = 0, underrunGaps = 0;
    std::vector<int16_t> block(blockFrames * 2u);
    while (produced < total)
    {
        owed += rate / 60.0 * speed * (1.0 + wobble(rng));
        const size_t n = std::min<size_t>(total - produced, static_cast<size_t>(owed));
        owed -= static_cast<double>(n);
        stretcher.push(raw.data() + produced * 2u, static_cast<uint32_t>(n));
        gapsFifo.insert(gapsFifo.end(), raw.begin() + produced * 2u, raw.begin() + (produced + n) * 2u);
        produced += n;
        devicePhase += rate / 60.0;
        while (devicePhase >= blockFrames)
        {
            devicePhase -= blockFrames;
            const uint32_t got = stretcher.pull(block.data(), blockFrames);
            underrunStretch += blockFrames - got;
            outStretch.insert(outStretch.end(), block.begin(), block.end());
            tempoSum += stretcher.tempo();
            ++tempoCount;
            const size_t g = std::min<size_t>(blockFrames, gapsFifo.size() / 2u);
            outGaps.insert(outGaps.end(), gapsFifo.begin(), gapsFifo.begin() + g * 2u);
            outGaps.insert(outGaps.end(), (blockFrames - g) * 2u, int16_t(0));
            gapsFifo.erase(gapsFifo.begin(), gapsFifo.begin() + g * 2u);
            underrunGaps += blockFrames - g;
        }
    }
    writeWav(prefix + "-soundtouch.wav", outStretch, rate);
    writeWav(prefix + "-gaps.wav", outGaps, rate);
    std::printf("capture %s: %.1f s of SPU2 output, simulated at %.2fx speed (jitter %.0f%%)\n", argv[1],
                total / double(rate), speed, jitter * 100.0);
    report("truespeed", std::vector<int16_t>(raw.begin(), raw.begin() + total * 2u), 0, 1.0, rate);
    report("soundtouch", outStretch, underrunStretch, tempoCount ? tempoSum / tempoCount : 1.0, rate);
    report("gaps", outGaps, underrunGaps, 1.0, rate);
    std::printf("files: %s-truespeed.wav  %s-soundtouch.wav  %s-gaps.wav\n", prefix.c_str(), prefix.c_str(), prefix.c_str());
    return 0;
}

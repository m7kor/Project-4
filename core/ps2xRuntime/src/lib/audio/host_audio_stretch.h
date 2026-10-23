#pragma once

// Host audio time stretch using PCSX2's SoundTouch settings:
// SoundTouch (LGPL-2.1, PCSX2's vendored copy) with PCSX2's default settings
// (sequence 30 ms, seek window 20 ms, overlap 10 ms, full seek, no AA filter)
// The controller measures source production against device demand, with
// buffer feedback and room for one stretch sequence at the current speed
// plus the recent producer gaps. Overrun limits follow that adaptive target.
// Refill after underruns follows PCSX2's approach; fades cover empty blocks.
//
// When the emulator runs slower than real time the sound is slowed down with
// its pitch kept, instead of being cut into gaps. Used by the runtime audio
// callback and by tools/audio/audio_lab.cpp, so the tool measures exactly
// what the player hears. Single-threaded: the audio thread owns it.

#include "SoundTouch.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

class HostAudioSoundTouch
{
public:
    static constexpr uint32_t kChunkFrames = 64; // PCSX2's AudioStream::CHUNK_SIZE

    explicit HostAudioSoundTouch(uint32_t sampleRate = 48000u, uint32_t bufferMs = 50u)
        : m_sampleRate(sampleRate), m_targetFrames(static_cast<float>(sampleRate) * bufferMs / 1000.0f)
    {
        m_soundTouch.setSampleRate(sampleRate);
        m_soundTouch.setChannels(2);
        m_soundTouch.setSetting(SETTING_USE_QUICKSEEK, 0);
        m_soundTouch.setSetting(SETTING_USE_AA_FILTER, 0);
        m_soundTouch.setSetting(SETTING_SEQUENCE_MS, 30);
        m_soundTouch.setSetting(SETTING_SEEKWINDOW_MS, 20);
        m_soundTouch.setSetting(SETTING_OVERLAP_MS, 10);
        m_soundTouch.setTempo(1.0f);
        m_dynamicTarget = m_targetFrames;
    }

    // Raw SPU2 output (interleaved stereo, emulation time).
    void push(const int16_t *stereo, uint32_t frames)
    {
        m_incomingFrames += frames;
        for (uint32_t i = 0; i < frames; ++i)
        {
            m_chunk[m_chunkFill * 2u] = stereo[i * 2u] * (1.0f / 32768.0f);
            m_chunk[m_chunkFill * 2u + 1u] = stereo[i * 2u + 1u] * (1.0f / 32768.0f);
            if (++m_chunkFill == kChunkFrames)
            {
                m_soundTouch.putSamples(m_chunk.data(), kChunkFrames);
                m_chunkFill = 0;

            }
        }
        // Overrun (producer far ahead, e.g. after a host stall): drop the
        // oldest output so latency stays bounded, as PCSX2 discards packets.
        const uint32_t limit = static_cast<uint32_t>(std::max(m_targetFrames * 8.0f, m_dynamicTarget * 2.0f));
        if (m_soundTouch.numSamples() > limit)
        {
            m_discard.resize(static_cast<size_t>(m_soundTouch.numSamples() - limit / 2u) * 2u);
            m_soundTouch.receiveSamples(m_discard.data(), static_cast<uint32_t>(m_discard.size() / 2u));
        }
    }

    // Returns received stretched frames; missing device frames remain counted.
    // Never resample a partial block: that lowers pitch during producer gaps.
    uint32_t pull(int16_t *out, uint32_t frames)
    {
        if (!frames)
            return 0;
        updateTempo(frames);
        m_output.resize(static_cast<size_t>(frames) * 2u);
        const uint32_t recoveryFrames = std::max(1u, static_cast<uint32_t>(m_dynamicTarget / 2.0f));
        const bool waiting = m_filling && m_soundTouch.numSamples() < recoveryFrames;
        const uint32_t got = waiting ? 0u : m_soundTouch.receiveSamples(m_output.data(), frames);
        if (got)
        {
            m_filling = false;
            for (uint32_t i = 0; i < got; ++i)
            {
                const float gain = m_recoveryFade ? std::min(1.0f, float(++m_fadePosition) / fadeFrames()) : 1.0f;
                for (uint32_t channel = 0; channel < 2u; ++channel)
                {
                    const float sample = m_output[i * 2u + channel];
                    out[i * 2u + channel] = softLimit(sample * 32768.0f * gain);
                }
            }
            if (m_fadePosition >= fadeFrames())
                m_recoveryFade = false;
            m_last = {out[(got - 1u) * 2u], out[(got - 1u) * 2u + 1u]};
            m_silencePosition = 0;
            for (uint32_t i = got; i < frames; ++i)
            {
                const float gain = std::max(0.0f, 1.0f - float(++m_silencePosition) / fadeFrames());
                for (uint32_t channel = 0; channel < 2u; ++channel)
                    out[i * 2u + channel] = static_cast<int16_t>(m_last[channel] * gain);
            }
            m_silencePosition = std::min(m_silencePosition, fadeFrames());
            if (got < frames)
            {
                m_recoveryFade = true;
                m_fadePosition = 0;
            }
        }
        else
        {
            // A short ramp avoids a discontinuity when the producer stops.
            // Do not repeat sound or conceal the missing-frame count.
            for (uint32_t i = 0; i < frames; ++i)
            {
                const float gain = std::max(0.0f, 1.0f - float(++m_silencePosition) / fadeFrames());
                for (uint32_t channel = 0; channel < 2u; ++channel)
                    out[i * 2u + channel] = static_cast<int16_t>(m_last[channel] * gain);
            }
            m_silencePosition = std::min(m_silencePosition, fadeFrames());
            m_recoveryFade = true;
            m_fadePosition = 0;
        }
        if (got < frames)
        {
            m_filling = true;
        }
        return got;
    }

    float tempo() const { return m_tempo; }
    bool inactive() const { return m_inactive; }
    struct Diagnostics
    {
        float sourceRate, controllerTempo, appliedTempo, targetFrames;
        uint32_t queuedFrames;
        bool filling;
    };
    // Read on the same owning audio thread. No logging or extra work in the
    // runtime callback; the laboratory can inspect controller bias explicitly.
    Diagnostics diagnostics() const
    {
        return {m_sourceRate, m_tempo, m_inactive ? 1.0f : m_tempo,
                m_dynamicTarget, m_soundTouch.numSamples(), m_filling};
    }

private:
    uint32_t fadeFrames() const { return std::max(1u, m_sampleRate / 200u); }
    static int16_t softLimit(float x)
    {
        // Transparent below the knee; peaks are rounded instead of clipped.
        constexpr float kKnee = 24000.0f, kRange = 32767.0f - kKnee;
        const float magnitude = std::fabs(x);
        if (magnitude > kKnee)
            x = std::copysign(kKnee + kRange * std::tanh((magnitude - kKnee) / kRange), x);
        return static_cast<int16_t>(std::clamp(x, -32767.0f, 32767.0f));
    }

    // Measure source production against actual device demand. The old
    // controller sampled once per producer chunk, so a burst weighted the
    // feedback many times while a stalled producer never updated it.
    void updateTempo(uint32_t frames)
    {
        m_history[m_historyPosition] = {m_incomingFrames, frames};
        m_incomingFrames = 0;
        m_historyPosition = (m_historyPosition + 1u) % m_history.size();
        m_historyCount = std::min(m_historyCount + 1u, static_cast<uint32_t>(m_history.size()));
        uint64_t source = 0, demand = 0;
        // Observe several burst/gap cycles rather than weighting a short
        // window's producer phase as sustained speed. At 480-frame callbacks
        // the history covers 1.28 seconds; at 1024 it covers 2.73 seconds.
        for (uint32_t i = 0; i < m_historyCount && demand < m_sampleRate * 6u / 5u; ++i)
        {
            const auto &entry = m_history[(m_historyPosition + m_history.size() - 1u - i) % m_history.size()];
            source += entry[0];
            demand += entry[1];
        }
        uint64_t gap = 0, longestGap = 0;
        for (uint32_t i = 0; i < m_historyCount; ++i)
        {
            const auto &entry = m_history[(m_historyPosition + m_history.size() - m_historyCount + i) % m_history.size()];
            gap = entry[0] ? 0u : gap + entry[1];
            longestGap = std::max(longestGap, gap);
        }
        if (source)
        {
            const float rate = std::clamp(float(source) / float(demand), 0.05f, 5.0f);
            m_sourceRate += (rate - m_sourceRate) * 0.05f;
        }
        // A slow producer needs room for one SoundTouch sequence measured in
        // host time, in addition to the requested latency.
        m_dynamicTarget = m_targetFrames + float(m_sampleRate) * 0.03f / m_sourceRate +
            float(std::min(longestGap, uint64_t(m_sampleRate / 2u)));
        m_dynamicTarget = std::max(m_dynamicTarget, float(frames) * 2.0f);
        const float fullness = std::max(0.01f, float(m_soundTouch.numSamples()) / m_dynamicTarget);
        // Ready-output occupancy oscillates during SoundTouch sequences and
        // producer gaps. Keep feedback weaker than the measured rate to avoid
        // sustained over-speed when the producer is close to native speed.
        const float correction = std::clamp(std::pow(fullness, 0.1f), 0.8f, 1.2f);
        const float target = std::clamp(m_sourceRate * correction, 0.05f, 5.0f);
        m_tempo += (target - m_tempo) * 0.05f;
        m_inactive = std::fabs(m_tempo - 1.0f) < 0.01f && fullness >= 0.9f && fullness <= 1.1f;
        m_soundTouch.setTempo(m_inactive ? 1.0f : m_tempo);
    }

    soundtouch::SoundTouch m_soundTouch;
    uint32_t m_sampleRate;
    float m_targetFrames;
    float m_dynamicTarget = 0.0f;
    float m_tempo = 1.0f;
    bool m_inactive = false;
    bool m_filling = true;
    bool m_recoveryFade = false;
    uint32_t m_fadePosition = 0, m_silencePosition = 0;
    std::array<int16_t, 2> m_last{};
    uint64_t m_incomingFrames = 0;
    float m_sourceRate = 1.0f;
    std::array<std::array<uint64_t, 2>, 128> m_history{};
    uint32_t m_historyPosition = 0, m_historyCount = 0;
    std::array<float, kChunkFrames * 2> m_chunk{};
    uint32_t m_chunkFill = 0;
    std::vector<float> m_output;
    std::vector<float> m_discard;
};

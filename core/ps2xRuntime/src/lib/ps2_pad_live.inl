// Opt-in diagnostic input, included only by the host adapter and its tests.
#include "ps2x/iop/iop_host.h"
#include <array>
#include <charconv>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <string_view>

namespace ps2x::diagnostic
{
class LivePadReplay
{
public:
    using Input = ps2x::iop::IopHost::PadInput;
    LivePadReplay(std::filesystem::path path, uint64_t activation)
        : m_path(std::move(path)), m_activation(activation) {}

    bool update(const std::string &text, uint64_t tick, uint64_t hostMs)
    {
        m_active = false; // A changed invalid file must not leave a held stick.
        m_reason = "malformed";
        if (text.size() > 1024) return false;
        std::istringstream stream(text);
        std::string header, row, extra;
        if (!std::getline(stream, header) || !std::getline(stream, row)) return false;
        if (!header.empty() && header.back() == '\r') header.pop_back();
        if (!row.empty() && row.back() == '\r') row.pop_back();
        if (header != "sequence,begin,end,buttons,lx,ly,rx,ry" || std::getline(stream, extra)) return false;
        std::array<uint64_t, 8> fields{};
        std::string_view rest(row);
        for (size_t i = 0; i < fields.size(); ++i)
        {
            const auto comma = rest.find(',');
            if ((i < 7 && comma == rest.npos) || (i == 7 && comma != rest.npos)) return false;
            const auto field = rest.substr(0, comma);
            const auto parsed = std::from_chars(field.data(), field.data() + field.size(), fields[i]);
            if (field.empty() || parsed.ec != std::errc{} || parsed.ptr != field.data() + field.size()) return false;
            if (i < 7) rest.remove_prefix(comma + 1);
        }
        m_reason = "sequence";
        if (fields[0] == 0 || fields[0] <= m_sequence) return false;
        m_reason = "interval";
        if (tick < m_activation || fields[1] <= tick || fields[1] - tick < 2 || fields[1] - tick > 120
            || fields[2] <= fields[1] || fields[2] - fields[1] > 180) return false;
        m_reason = "range";
        if (fields[3] > 65535) return false;
        for (size_t i = 4; i < fields.size(); ++i) if (fields[i] > 255) return false;
        m_sequence = fields[0]; m_begin = fields[1]; m_end = fields[2]; m_acceptedHostMs = hostMs;
        m_input = {};
        m_input.buttons = static_cast<uint16_t>(fields[3]);
        m_input.lx = static_cast<uint8_t>(fields[4]); m_input.ly = static_cast<uint8_t>(fields[5]);
        m_input.rx = static_cast<uint8_t>(fields[6]); m_input.ry = static_cast<uint8_t>(fields[7]);
        m_active = true;
        m_reason = "accepted";
        return true;
    }

    Input inputAt(uint64_t tick, uint64_t hostMs) const
    {
        if (!m_active || tick < m_begin || tick >= m_end || hostMs < m_acceptedHostMs
            || hostMs - m_acceptedHostMs >= 30000) return {};
        return m_input;
    }

    bool poll(uint64_t tick, uint64_t hostMs, Input &input)
    {
        if (tick < m_activation) return false; // Startup fixture retains ownership.
        if (m_polled && (tick < m_lastTick || hostMs < m_lastPollHostMs)) m_active = false;
        m_lastTick = tick;
        if (!m_polled || hostMs < m_lastPollHostMs || hostMs - m_lastPollHostMs >= 50)
        {
            m_polled = true;
            m_lastPollHostMs = hostMs;
            std::string text;
            std::error_code ec;
            const auto status = std::filesystem::symlink_status(m_path, ec);
            bool readable = !ec && std::filesystem::is_regular_file(status);
            if (readable)
            {
                std::ifstream file(m_path, std::ios::binary);
                std::array<char, 1025> buffer{};
                if (file)
                {
                    file.read(buffer.data(), buffer.size());
                    readable = !file.bad() && file.gcount() <= 1024;
                    if (readable) text.assign(buffer.data(), static_cast<size_t>(file.gcount()));
                }
                else readable = false;
            }
            if (!readable)
            {
                m_active = false;
                if (!m_sawFileState || m_readable)
                    std::fprintf(stderr, "[pad live] unavailable tick=%llu; released\n", static_cast<unsigned long long>(tick));
            }
            else if (!m_sawFileState || !m_readable || text != m_seenText)
            {
                const bool accepted = update(text, tick, hostMs);
                std::fprintf(stderr, "[pad live] %s reason=%s sequence=%llu tick=%llu begin=%llu end=%llu host_ms=%llu\n",
                    accepted ? "accepted" : "rejected", m_reason,
                    static_cast<unsigned long long>(m_sequence), static_cast<unsigned long long>(tick),
                    static_cast<unsigned long long>(m_begin), static_cast<unsigned long long>(m_end),
                    static_cast<unsigned long long>(hostMs));
            }
            m_sawFileState = true; m_readable = readable; m_seenText = std::move(text);
        }
        input = inputAt(tick, hostMs);
        return true; // After activation this diagnostic owns even neutral input.
    }

    const char *reason() const { return m_reason; }
    uint64_t sequence() const { return m_sequence; }

private:
    std::filesystem::path m_path;
    uint64_t m_activation, m_sequence = 0, m_begin = 0, m_end = 0, m_acceptedHostMs = 0;
    uint64_t m_lastTick = 0, m_lastPollHostMs = 0;
    bool m_active = false, m_polled = false, m_sawFileState = false, m_readable = false;
    std::string m_seenText;
    const char *m_reason = "empty";
    Input m_input{};
};
}

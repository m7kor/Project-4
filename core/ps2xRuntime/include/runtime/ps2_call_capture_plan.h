// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

// At most eight full-RAM snapshots. A field is a lower bound, not a promise
// that the observed function runs at exactly that field. Empty text preserves
// the original one-shot capture. Invalid lists disable capture entirely.
class PS2CallCapturePlan
{
public:
    bool configure(std::string_view text, uint64_t fallback)
    {
        m_fields.clear();
        m_next = 0;
        if (text.empty()) { m_fields.push_back(fallback); return true; }
        while (!text.empty()) {
            const size_t comma = text.find(',');
            const auto word = text.substr(0, comma);
            uint64_t field = 0;
            const auto parsed = std::from_chars(word.data(), word.data() + word.size(), field);
            if (word.empty() || parsed.ec != std::errc{} || parsed.ptr != word.data() + word.size() ||
                m_fields.size() == 8 || (!m_fields.empty() && field <= m_fields.back())) {
                m_fields.clear();
                return false;
            }
            m_fields.push_back(field);
            if (comma == std::string_view::npos) return true;
            text.remove_prefix(comma + 1);
            if (text.empty()) { m_fields.clear(); return false; }
        }
        return false;
    }
    bool due(uint64_t field) const { return m_next < m_fields.size() && field >= m_fields[m_next]; }
    uint64_t consume() { const auto field = m_fields.at(m_next); ++m_next; return field; }
private:
    std::vector<uint64_t> m_fields;
    size_t m_next = 0;
};

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>
#include <limits>

namespace ps2x {
// Brent cycle detection for the deterministic source-chain control state.
// A valid long chain has no arbitrary tag-count cutoff and needs no visited
// allocation. Stack registers are included so repeated CALL subroutines with
// different return addresses remain distinct states.
class DmaChainCycleGuard {
public:
    bool repeated(uint32_t address, uint32_t asp, uint32_t asr0, uint32_t asr1) noexcept {
        const std::array<uint32_t, 4> next{address, asp, asr0, asr1};
        if (!m_started) {
            m_anchor = next;
            m_started = true;
            return false;
        }
        ++m_distance;
        if (next == m_anchor) return true;
        if (m_distance == m_power) {
            m_anchor = next;
            m_distance = 0;
            const auto maximum = std::numeric_limits<uint64_t>::max();
            m_power = m_power <= maximum / 2 ? m_power * 2 : maximum;
        }
        return false;
    }
private:
    std::array<uint32_t, 4> m_anchor{};
    uint64_t m_power = 1, m_distance = 0;
    bool m_started = false;
};
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "iop_memory_card.h"
#include "iop_pad.h"
#include <array>
#include <deque>

namespace ps2x::iop::detail
{
    class IopSio2
    {
    public:
        bool openCard(const std::filesystem::path &path) { return m_card.open(path); }
        void setPadSampler(IopPad::Sampler sampler) { m_padSampler = std::move(sampler); }
        void reset();
        uint32_t read(uint32_t address);
        void write(uint32_t address, uint32_t value);
        void input(uint8_t value, uint32_t blockBytes = 0);
        uint8_t output();
        size_t available() const noexcept { return m_output.size(); }
        bool takeInterrupt() noexcept { const bool pending = m_irq; m_irq = false; return pending; }
    private:
        IopMemoryCard m_card;
        std::array<IopPad, 2> m_pads{};
        IopPad::Sampler m_padSampler;
        std::array<uint32_t, 16> m_commands{};
        std::array<uint32_t, 8> m_portControl{};
        std::vector<uint8_t> m_input;
        std::deque<uint8_t> m_output;
        uint32_t m_position = 0, m_control = 0x3bc, m_status = 0x1d100, m_iStat = 0;
        uint32_t m_txPosition = 0, m_rxPosition = 0;
        bool m_irq = false;
    };
}

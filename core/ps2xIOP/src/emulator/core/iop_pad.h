// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "ps2x/iop/iop_host.h"
#include <functional>
#include <span>
#include <vector>

namespace ps2x::iop::detail
{
    class IopPad
    {
    public:
        using Sampler = std::function<bool(int, int, IopHost::PadInput &)>;
        void reset() noexcept;
        std::vector<uint8_t> exchange(std::span<const uint8_t> packet, const IopHost::PadInput &input);
        uint8_t mode() const noexcept { return m_mode; }
        uint8_t smallMotor() const noexcept { return m_smallMotor; }
        uint8_t largeMotor() const noexcept { return m_largeMotor; }
    private:
        uint8_t m_mode = 0x41;
        bool m_config = false, m_locked = false;
        uint8_t m_smallMap = 0xff, m_largeMap = 0xff;
        uint8_t m_smallMotor = 0, m_largeMotor = 0;
    };
}

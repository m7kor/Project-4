// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <span>
#include <vector>
#include <functional>
#include <array>

namespace ps2x::iop::detail
{
    // PS2SDK's SecrAuthCard orchestration, with guest transport and device
    // endpoints injected. A result is accepted only after all exchanges pass.
    class IopSecrman
    {
    public:
        using Transfer = std::function<bool(int, int, std::span<const uint8_t>, std::vector<uint8_t> &, uint32_t &)>;
        using Mecha = std::function<bool(uint8_t, std::span<const uint8_t>, std::vector<uint8_t> &)>;
        static bool authenticate(int port, int slot, int cnum, const Transfer &transfer, const Mecha &mecha);
        static void reset(int port, int slot, int cnum, const Transfer &transfer, const Mecha &mecha);
    };

    // Virtual MechaCon authentication endpoint. Challenge bytes match the
    // pinned PCSX2 CDVD implementation; no claim of physical MagicGate crypto.
    class IopMechaAuth
    {
    public:
        void reset() noexcept { m_stage = 0; m_cnum = 0; }
        bool exchange(uint8_t command, std::span<const uint8_t> input, std::vector<uint8_t> &output);
    private:
        unsigned m_stage = 0;
        uint8_t m_cnum = 0;
    };
}

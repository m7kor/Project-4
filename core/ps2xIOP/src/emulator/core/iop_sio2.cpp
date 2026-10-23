// SPDX-License-Identifier: GPL-3.0-or-later
// Register/FIFO behavior follows the pinned PCSX2 SIO2 reference. Device
// replies are generated from actual packets, never from MCMAN return values.
#include "iop_sio2.h"
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>

namespace ps2x::iop::detail
{
    void IopSio2::reset()
    {
        m_card.reset(); m_commands.fill(0); m_portControl.fill(0);
        for (auto &pad : m_pads) pad.reset();
        m_input.clear(); m_output.clear(); m_position = 0;
        m_control = 0x3bc; m_status = 0x1d100; m_iStat = 0;
        m_txPosition = m_rxPosition = 0; m_irq = false;
    }
    uint32_t IopSio2::read(uint32_t address)
    {
        if (address >= 0x1f808200 && address < 0x1f808240)
            return m_commands[(address - 0x1f808200) / 4];
        if (address >= 0x1f808240 && address < 0x1f808260)
            return m_portControl[(address - 0x1f808240) / 4];
        switch (address)
        {
        case 0x1f808264: return output();
        case 0x1f808268: return m_control;
        case 0x1f80826c: return m_status;
        case 0x1f808270: return 0xf;
        case 0x1f808278: return m_txPosition;
        case 0x1f80827c: return m_rxPosition;
        case 0x1f808280: return m_iStat;
        default: return 0;
        }
    }
    void IopSio2::write(uint32_t address, uint32_t value)
    {
        if (address >= 0x1f808200 && address < 0x1f808240)
        {
            m_commands[(address - 0x1f808200) / 4] = value;
            if (address == 0x1f808200) { m_position = 0; m_input.clear(); m_status = 0; }
            return;
        }
        if (address >= 0x1f808240 && address < 0x1f808260)
        { m_portControl[(address - 0x1f808240) / 4] = value; return; }
        switch (address)
        {
        case 0x1f808260: input(static_cast<uint8_t>(value)); break;
        case 0x1f808268:
            m_control = value;
            if (value & 1) { if (!m_iStat) m_irq = true; m_iStat |= 1; }
            break;
        case 0x1f808278: m_txPosition = value; break;
        case 0x1f80827c: m_rxPosition = value; break;
        case 0x1f808280: m_iStat &= ~value; break;
        default: break;
        }
    }
    void IopSio2::input(uint8_t value, uint32_t blockBytes)
    {
        if (m_position >= m_commands.size()) return;
        const uint32_t descriptor = m_commands[m_position];
        const uint32_t length = (descriptor >> 8) & 0x3ff;
        if (!length) return;
        const uint32_t expected = blockBytes ? blockBytes : length;
        if (expected > 2 * 1024 * 1024 || expected < length) return;
        m_input.push_back(value);
        if (m_input.size() != expected) return;
        const bool memoryCard = m_input[0] == 0x81;
        const bool padPacket = m_input[0] == 1;
        const int port = descriptor & 1;
        IopHost::PadInput padInput;
        const bool padPresent = padPacket && m_padSampler && m_padSampler(port, 0, padInput);
        const bool connected = memoryCard && !(descriptor & 1) && m_card.present();
        std::vector<uint8_t> reply = connected
            ? m_card.exchange(std::span<const uint8_t>(m_input).first(length))
            : padPresent ? m_pads[port].exchange(std::span<const uint8_t>(m_input).first(length), padInput)
            : std::vector<uint8_t>(length, 0xff);
        if (memoryCard) m_status = connected ? 0x1100 : 0x1d100;
        else
        {
            m_status = (m_status & ~0x300u) | ((m_status & 0x100) ? 0x200 : 0x100);
            m_status |= 0x1000;
            if (!padPresent) m_status |= (descriptor & 1) ? 0x2d000 : 0x1d000;
        }
        // Input bytes and generated response clocks can have different lengths.
        // DMA aligns the complete response; it must never truncate it to TX size.
        if (blockBytes)
        {
            const size_t remainder = reply.size() % blockBytes;
            if (remainder) reply.resize(reply.size() + blockBytes - remainder, 0);
        }
        // PS2X_TRACE_SIO2_CARD: one line per memory card command, with the
        // descriptor's TX/RX byte counts against the reply actually queued.
        static const bool traceCard = std::getenv("PS2X_TRACE_SIO2_CARD") != nullptr;
        if (traceCard && memoryCard)
        {
            std::fprintf(stderr, "[sio2:card] cmd=%02x desc=%08x tx=%u rx=%u block=%u reply=%zu queued=%zu head=",
                         m_input.size() > 1 ? m_input[1] : 0, descriptor, length, (descriptor >> 18) & 0x1ff,
                         blockBytes, reply.size(), m_output.size());
            for (size_t i = 0; i < std::min<size_t>(m_input.size(), 8u); ++i)
                std::fprintf(stderr, "%02x", m_input[i]);
            std::fprintf(stderr, " out=");
            for (size_t i = 0; i < std::min<size_t>(reply.size(), 12u); ++i)
                std::fprintf(stderr, "%02x", reply[i]);
            std::fprintf(stderr, "\n");
        }
        if (m_output.size() + reply.size() > 2 * 1024 * 1024)
            throw std::runtime_error("SIO2 output FIFO exceeded bounded capacity");
        m_output.insert(m_output.end(), reply.begin(), reply.end());
        m_input.clear(); ++m_position;
    }
    uint8_t IopSio2::output()
    {
        if (m_output.empty()) return 0xff;
        const uint8_t value = m_output.front(); m_output.pop_front(); return value;
    }
}

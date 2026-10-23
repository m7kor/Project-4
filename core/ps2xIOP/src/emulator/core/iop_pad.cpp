// SPDX-License-Identifier: GPL-3.0-or-later
// Protocol reference: PCSX2 646df006a4688063e56c0826e7ea4b8bb0c112c4,
// pcsx2/SIO/Pad/PadDualshock2.cpp (PCSX2 Dev Team, GPL-3.0+).
#include "iop_pad.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>

namespace ps2x::iop::detail
{
    void IopPad::reset() noexcept { *this = IopPad{}; }

    std::vector<uint8_t> IopPad::exchange(std::span<const uint8_t> packet, const IopHost::PadInput &input)
    {
        if (packet.size() < 3 || packet.size() > 1023 || packet[0] != 1)
            return std::vector<uint8_t>(packet.size(), 0xff);
        std::vector<uint8_t> reply(packet.size(), 0);
        reply[0] = 0xff; reply[1] = m_config ? 0xf3 : m_mode; reply[2] = 0x5a;
        const auto set = [&](size_t index, uint8_t value) { if (index < reply.size()) reply[index] = value; };
        const auto arg = [&](size_t index) { return index < packet.size() ? packet[index] : uint8_t(0); };
        switch (packet[1])
        {
        case 0x40: set(5,2); set(8,0x5a); break;
        case 0x41:
            if (m_mode == 0x73 || m_mode == 0x79)
            { set(3,0xff); set(4,0xff); set(5,3); set(8,0x5a); }
            break;
        case 0x42:
            set(3,static_cast<uint8_t>(input.buttons)); set(4,static_cast<uint8_t>(input.buttons >> 8));
            set(5,input.rx); set(6,input.ry); set(7,input.lx); set(8,input.ly);
            for (size_t i = 0; i < input.pressure.size(); ++i) set(9 + i,input.pressure[i]);
            if (packet.size() >= 5)
            {
                const auto motorByte = [&](uint8_t map) { return map < 2 ? arg(3 + map) : uint8_t(0); };
                m_smallMotor = motorByte(m_smallMap) & 1; m_largeMotor = motorByte(m_largeMap);
            }
            break;
        case 0x43:
            if (packet.size() > 3) m_config = packet[3] != 0;
            break;
        case 0x44:
            if (packet.size() > 3) m_mode = packet[3] ? 0x73 : 0x41;
            if (packet.size() > 4) m_locked = packet[4] == 3;
            break;
        case 0x45:
            set(3,3); set(4,2); set(5,m_mode == 0x41 ? 0 : 1); set(6,2); set(7,1);
            break;
        case 0x46:
            set(5,1); set(6,arg(3) ? 1 : 2); set(7,arg(3) ? 1 : 0); set(8,arg(3) ? 0x14 : 0x0a);
            break;
        case 0x47: set(5,2); set(7,1); break;
        case 0x4c: set(6,arg(3) ? 7 : 4); break;
        case 0x4d:
            for (size_t i = 3; i < reply.size(); ++i) reply[i] = 0xff;
            set(3,m_smallMap); set(4,m_largeMap);
            if (packet.size() > 3) m_smallMap = packet[3];
            if (packet.size() > 4) m_largeMap = packet[4];
            break;
        case 0x4f:
            if (packet.size() > 5)
            {
                const uint32_t mask = uint32_t(packet[3]) | (uint32_t(packet[4]) << 8) | (uint32_t(packet[5]) << 16);
                m_mode = mask == 0x3ffff ? 0x79 : mask == 0x3f ? 0x73 : 0x41;
            }
            set(8,0x5a); break;
        default:
            // As with the reference DS2, unknown commands have no command
            // payload acknowledgement beyond the device ID/header.
            break;
        }
        // Observe the bytes actually returned, including short polls that
        // cannot contain axes. Diagnostic-only; never modify the reply.
        static const bool trace = [] {
            const char *value = std::getenv("PS2X_TRACE_PAD");
            return value && *value == '1';
        }();
        if (trace && packet[1] == 0x42)
        {
            static thread_local const IopPad *previousDevice = nullptr;
            static thread_local std::vector<uint8_t> previousReply;
            if (previousDevice != this || previousReply != reply)
            {
                previousDevice = this;
                previousReply = reply;
                const auto at = [&](size_t index) { return index < reply.size() ? int(reply[index]) : -1; };
                const auto hostMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now().time_since_epoch()).count();
                const int buttons = reply.size() >= 5 ? (int(reply[3]) | int(reply[4]) << 8) : -1;
                std::fprintf(stderr, "[pad wire] host_ms=%lld command=66 mode=%u bytes=%zu buttons=%d lx=%d ly=%d rx=%d ry=%d\n",
                    static_cast<long long>(hostMs), unsigned(reply[1]), reply.size(), buttons,
                    at(7), at(8), at(5), at(6));
            }
        }
        return reply;
    }
}

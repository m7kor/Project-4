// SPDX-License-Identifier: GPL-3.0-or-later
// References: ps2dev/ps2sdk iop/security/secrman/src/{secrman,CardAuth}.c;
// PCSX2 646df006a4688063e56c0826e7ea4b8bb0c112c4 pcsx2/CDVD/CDVD.cpp.
#include "iop_secrman.h"
#include <algorithm>

namespace ps2x::iop::detail
{
    namespace
    {
        using Block = std::array<uint8_t, 8>;
        bool card(const IopSecrman::Transfer &transfer, int port, int slot,
                  uint8_t command, uint8_t mode, Block *data = nullptr, bool write = false)
        {
            std::vector<uint8_t> input(data ? 14 : 5, 0), output;
            input[0] = 0x81; input[1] = command; input[2] = mode;
            if (data && write)
                for (size_t i = 0; i < 8; ++i) { input[3 + i] = (*data)[7 - i]; input[11] ^= (*data)[i]; }
            uint32_t status = 0;
            if (!transfer(port, slot, input, output, status) || output.size() != input.size() || (status & 0xe000))
                return false;
            const size_t ack = data && write ? 12 : 3;
            if (output[ack] != 0x2b || output.back() == 0x66) return false;
            if (data && !write)
            {
                uint8_t checksum = 0;
                for (size_t i = 0; i < 8; ++i) checksum ^= output[4 + i];
                if (checksum != output[12]) return false;
                for (size_t i = 0; i < 8; ++i) (*data)[7 - i] = output[4 + i];
            }
            return true;
        }
        bool device(const IopSecrman::Mecha &mecha, uint8_t command,
                    std::span<const uint8_t> input, std::vector<uint8_t> &output, size_t expected = 1)
        {
            return mecha(command, input, output) && output.size() == expected && output[0] == 0;
        }
    }

    void IopSecrman::reset(int port, int slot, int cnum, const Transfer &transfer, const Mecha &mecha)
    {
        if (!transfer || !mecha || port < 0 || port > 3 || slot < 0 || slot > 3 || cnum < 0 || cnum > 15) return;
        (void)card(transfer, port, slot, 0xf3, 0);
        const uint8_t number = static_cast<uint8_t>(cnum);
        std::vector<uint8_t> output;
        (void)device(mecha, 0x80, {&number, 1}, output);
    }

    bool IopSecrman::authenticate(int port, int slot, int cnum, const Transfer &transfer, const Mecha &mecha)
    {
        if (!transfer || !mecha || port < 0 || port > 3 || slot < 0 || slot > 3 || cnum < 0 || cnum > 15) return false;
        const uint8_t number = static_cast<uint8_t>(cnum);
        std::vector<uint8_t> output;
        Block iv{}, material{}, nonce{}, challenge1{}, challenge2{}, challenge3{}, response1{}, response2{}, response3{};
        const auto small = [&](uint8_t command, uint8_t mode) { return card(transfer, port, slot, command, mode); };
        const auto read = [&](uint8_t mode, Block &data) { return card(transfer, port, slot, 0xf0, mode, &data); };
        const auto write = [&](uint8_t mode, Block &data) { return card(transfer, port, slot, 0xf0, mode, &data, true); };
        const auto mc = [&](uint8_t command, std::span<const uint8_t> bytes = {}) { return device(mecha, command, bytes, output); };
        const auto twoBlocks = [&](uint8_t command, const Block &first, const Block &second) {
            std::array<uint8_t, 16> bytes{}; std::copy(first.begin(), first.end(), bytes.begin());
            std::copy(second.begin(), second.end(), bytes.begin() + 8); return mc(command, bytes);
        };
        bool success = small(0xf3, 0) && mc(0x80, {&number, 1}) && small(0xf7, 1)
            && small(0xf0, 0) && mc(0x81, {&number, 1}) && read(1, iv) && read(2, material)
            && twoBlocks(0x82, iv, material) && small(0xf0, 3) && read(4, nonce)
            && mc(0x83, nonce) && small(0xf0, 5) && mc(0x8f);
        if (success)
        {
            success = device(mecha, 0x84, {}, output, 13);
            if (success) { std::copy_n(output.begin() + 1, 8, challenge1.begin()); std::copy_n(output.begin() + 9, 4, challenge2.begin()); }
        }
        if (success)
        {
            success = device(mecha, 0x85, {}, output, 13);
            if (success) { std::copy_n(output.begin() + 1, 4, challenge2.begin() + 4); std::copy_n(output.begin() + 5, 8, challenge3.begin()); }
        }
        if (success) success = write(6, challenge3) && write(7, challenge2) && small(0xf0, 8)
            && small(0xf0, 9) && small(0xf0, 0xa) && write(0xb, challenge1) && small(0xf0, 0xc)
            && small(0xf0, 0xd) && small(0xf0, 0xe) && read(0xf, response1) && small(0xf0, 0x10)
            && read(0x11, response2) && twoBlocks(0x86, response1, response2) && small(0xf0, 0x12)
            && read(0x13, response3) && mc(0x87, response3) && mc(0x8f) && small(0xf0, 0x14) && mc(0x88);
        if (!success) reset(port, slot, cnum, transfer, mecha);
        return success;
    }

    bool IopMechaAuth::exchange(uint8_t command, std::span<const uint8_t> input, std::vector<uint8_t> &output)
    {
        output.clear();
        const auto accepted = [&](unsigned next) { m_stage = next; output = {0}; return true; };
        switch (command)
        {
        case 0x80:
            if (input.size() != 1 || input[0] > 15) return false;
            m_cnum = input[0]; return accepted(1);
        case 0x81:
            if (m_stage != 1 || input.size() != 1 || input[0] != m_cnum) return false;
            return accepted(2);
        case 0x82:
            if (m_stage != 2 || input.size() != 16) return false;
            return accepted(3);
        case 0x83:
            if (m_stage != 3 || input.size() != 8) return false;
            return accepted(4);
        case 0x8f:
            if (!input.empty() || (m_stage != 4 && m_stage != 8)) return false;
            return accepted(m_stage == 4 ? 5 : 9);
        case 0x84:
            if (m_stage != 5 || !input.empty()) return false;
            m_stage = 6; output = {0,0x21,0xdc,0x31,0x96,0xce,0x72,0xe0,0xc8,0x69,0xda,0x34,0x9b}; return true;
        case 0x85:
            if (m_stage != 6 || !input.empty()) return false;
            m_stage = 7; output = {0,0xeb,0x01,0xc7,0xa9,0x3f,0x9c,0x5b,0x19,0x31,0xa0,0xb3,0xa3}; return true;
        case 0x86:
            if (m_stage != 7 || input.size() != 16) return false;
            return accepted(10);
        case 0x87:
            if (m_stage != 10 || input.size() != 8) return false;
            return accepted(8);
        case 0x88:
            if (m_stage != 9 || !input.empty()) return false;
            return accepted(0);
        default: return false;
        }
    }
}

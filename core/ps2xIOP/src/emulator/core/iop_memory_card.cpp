// SPDX-License-Identifier: GPL-3.0-or-later
// Protocol reference: pinned PCSX2 646df006a4688063e56c0826e7ea4b8bb0c112c4,
// pcsx2/SIO/Memcard/MemoryCardProtocol.cpp (PCSX2 Dev Team, GPL-3.0+).
#include "iop_memory_card.h"
#include <algorithm>
#include <fstream>

namespace ps2x::iop::detail
{
    bool IopMemoryCard::open(const std::filesystem::path &path)
    {
        m_image.clear(); m_path.clear(); reset();
        std::error_code ec;
        const bool exists = std::filesystem::exists(path, ec);
        if (ec) return false;
        std::vector<uint8_t> image(ImageBytes, 0xff);
        if (exists)
        {
            if (std::filesystem::file_size(path, ec) != ImageBytes || ec) return false;
            std::ifstream file(path, std::ios::binary);
            if (!file.read(reinterpret_cast<char *>(image.data()), image.size())) return false;
        }
        else
        {
            // Caller chooses the storage directory. Never resize an existing card.
            std::ofstream file(path, std::ios::binary | std::ios::out);
            if (!file.write(reinterpret_cast<const char *>(image.data()), image.size())) return false;
            file.flush();
            if (!file) return false;
        }
        m_path = path; m_image = std::move(image);
        return true;
    }

    void IopMemoryCard::reset() noexcept
    {
        m_sector = m_address = 0; m_goodSector = false; m_terminator = 0x55;
    }

    bool IopMemoryCard::persist(uint32_t address, std::span<const uint8_t> bytes)
    {
        if (!present() || address > ImageBytes || bytes.size() > ImageBytes - address) return false;
        std::fstream file(m_path, std::ios::binary | std::ios::in | std::ios::out);
        file.seekp(address);
        file.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
        file.flush();
        if (!file) { m_image.clear(); return false; }
        std::copy(bytes.begin(), bytes.end(), m_image.begin() + address);
        return true;
    }

    std::vector<uint8_t> IopMemoryCard::exchange(std::span<const uint8_t> packet)
    {
        // A malformed or unsupported transaction has no acknowledgement.
        const auto failure = [&] { return std::vector<uint8_t>(packet.size(), 0xff); };
        if (!present() || packet.size() < 2 || packet.size() > 1023 || packet[0] != 0x81)
            return failure();
        const auto tail = [&](size_t length) -> std::vector<uint8_t> {
            std::vector<uint8_t> reply(std::max(packet.size(), length), 0);
            reply[length - 2] = 0x2b; reply[length - 1] = m_terminator;
            return reply;
        };
        switch (packet[1])
        {
        case 0x11: case 0x12: case 0x81: return tail(4);
        case 0xbf: case 0xf7: return tail(5);
        case 0xf3:
            m_terminator = 0x55; return tail(5);
        case 0x21: case 0x22: case 0x23:
        {
            if (packet.size() < 7) return failure();
            const uint32_t sector = uint32_t(packet[2]) | (uint32_t(packet[3]) << 8)
                | (uint32_t(packet[4]) << 16) | (uint32_t(packet[5]) << 24);
            m_goodSector = (packet[2] ^ packet[3] ^ packet[4] ^ packet[5]) == packet[6]
                && sector < Pages;
            m_sector = sector;
            m_address = m_goodSector ? sector * PageBytes : ImageBytes;
            return tail(9);
        }
        case 0x26:
        {
            auto reply = tail(13);
            const uint8_t geometry[] = {0x2b, 0x00, 0x02, 0x10, 0x00, 0x00, 0x40, 0x00, 0x00, 0x52};
            std::copy(std::begin(geometry), std::end(geometry), reply.begin() + 2);
            return reply;
        }
        case 0x27:
            if (packet.size() < 3) return failure();
            m_terminator = packet[2]; return tail(5);
        case 0x28:
        {
            auto reply = tail(5); reply[2] = 0x2b; reply[3] = m_terminator; return reply;
        }
        case 0x42: case 0x43:
        {
            if (packet.size() < 3) return failure();
            const size_t count = packet[2];
            if (!m_goodSector || count > ImageBytes - m_address ||
                (packet[1] == 0x42 && packet.size() < count + 4))
                return failure();
            std::vector<uint8_t> reply(std::max(packet.size(), count + 6), 0);
            reply[3] = 0x2b;
            uint8_t checksum = 0;
            if (packet[1] == 0x42)
            {
                auto data = packet.subspan(3, count);
                for (auto byte : data) checksum ^= byte;
                // PS2 card NAND programming only clears bits. Erase (0x82)
                // restores them; match PCSX2 FileMemoryCard::Save semantics.
                std::vector<uint8_t> programmed(count);
                for (size_t i = 0; i < count; ++i)
                    programmed[i] = m_image[m_address + i] & data[i];
                if (!persist(m_address, programmed)) return failure();
            }
            else
            {
                for (size_t i = 0; i < count; ++i)
                {
                    reply[4 + i] = m_image[m_address + i]; checksum ^= reply[4 + i];
                }
            }
            reply[count + 4] = checksum; reply[count + 5] = m_terminator;
            m_address += static_cast<uint32_t>(count);
            return reply;
        }
        case 0x82:
        {
            if (!m_goodSector) return failure();
            const uint32_t base = (m_sector / ErasePages) * ErasePages * PageBytes;
            const std::vector<uint8_t> erased(ErasePages * PageBytes, 0xff);
            if (!persist(base, erased)) return failure();
            return tail(4);
        }
        case 0xf0:
        {
            if (packet.size() < 5) return failure();
            switch (packet[2])
            {
            case 1: case 2: case 4: case 0xf: case 0x11: case 0x13:
            {
                if (packet.size() < 14) return failure();
                std::vector<uint8_t> reply(packet.size(), 0); reply[3] = 0x2b;
                for (size_t i = 3; i < 11; ++i) reply[12] ^= packet[i];
                reply[13] = m_terminator; return reply;
            }
            case 6: case 7: case 0xb: return tail(14);
            case 0: case 3: case 5: case 8: case 9: case 0xa: case 0xc: case 0xd:
            case 0xe: case 0x10: case 0x12: case 0x14: return tail(5);
            default: return failure();
            }
        }
        default: return failure();
        }
    }
}

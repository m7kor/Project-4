// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <filesystem>
#include <span>
#include <vector>

namespace ps2x::iop::detail
{
    // Raw PS2 card sectors include the 16-byte spare/ECC area. No filesystem
    // is synthesized: the original MCMAN owns formatting and directory layout.
    class IopMemoryCard
    {
    public:
        static constexpr uint32_t PageBytes = 528, Pages = 16384, ErasePages = 16;
        static constexpr uint32_t ImageBytes = PageBytes * Pages;
        bool open(const std::filesystem::path &path);
        bool present() const noexcept { return !m_image.empty(); }
        void reset() noexcept;
        std::vector<uint8_t> exchange(std::span<const uint8_t> packet);
    private:
        bool persist(uint32_t address, std::span<const uint8_t> bytes);
        std::filesystem::path m_path;
        std::vector<uint8_t> m_image;
        uint32_t m_sector = 0, m_address = 0;
        uint8_t m_terminator = 0x55;
        bool m_goodSector = false;
    };
}

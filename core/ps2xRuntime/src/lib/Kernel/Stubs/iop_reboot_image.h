#pragma once

#include <cstdint>
#include <cstring>
#include <span>
#include <string>
#include <unordered_set>
#include <vector>

namespace ps2_stubs::detail
{
    struct RebootImageFile
    {
        std::string name;
        uint32_t offset = 0u;
        uint32_t size = 0u;
    };

    // ROMDIR entry layout: name[10], extinfo size[2], file size[4].
    // This parser accepts the zero-sized RESET layout of IOPRP images;
    // a BIOS image with executable RESET code needs a separate boot path.
    inline bool parseRebootImage(std::span<const uint8_t> bytes,
                                 std::vector<RebootImageFile> &files)
    {
        files.clear();
        if (bytes.size() < 48u || std::memcmp(bytes.data(), "RESET\0", 6u) != 0 ||
            std::memcmp(bytes.data() + 16u, "ROMDIR\0", 7u) != 0)
            return false;
        const auto word = [&](size_t offset)
        {
            return uint32_t(bytes[offset]) | (uint32_t(bytes[offset + 1u]) << 8u) |
                   (uint32_t(bytes[offset + 2u]) << 16u) | (uint32_t(bytes[offset + 3u]) << 24u);
        };
        const uint32_t tableSize = word(28u);
        if (word(12u) != 0u || tableSize < 48u || tableSize > 4096u ||
            tableSize % 16u != 0u || tableSize > bytes.size())
            return false;
        std::vector<RebootImageFile> pending;
        std::unordered_set<std::string> names;
        uint64_t cursor = 0u;
        for (uint32_t entry = 0u; entry < tableSize; entry += 16u)
        {
            if (bytes[entry] == 0u)
            {
                if (pending.size() < 3u || pending[2].name != "EXTINFO")
                    return false;
                files = std::move(pending);
                return true;
            }
            size_t length = 0u;
            while (length < 10u && bytes[entry + length] != 0u)
            {
                if (bytes[entry + length] < 0x21u || bytes[entry + length] > 0x7eu)
                    return false;
                ++length;
            }
            const std::string name(reinterpret_cast<const char *>(bytes.data() + entry), length);
            const uint32_t size = word(entry + 12u);
            if (!names.emplace(name).second || cursor > bytes.size() || size > bytes.size() - cursor)
                return false;
            pending.push_back({name, static_cast<uint32_t>(cursor), size});
            cursor += (uint64_t(size) + 15u) & ~uint64_t(15u);
        }
        return false;
    }
}

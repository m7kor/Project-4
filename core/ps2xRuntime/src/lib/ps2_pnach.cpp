#include "runtime/ps2_pnach.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>

namespace
{
    constexpr uint32_t kRamSize = 32u * 1024u * 1024u;

    std::string trim(std::string s)
    {
        const auto notSpace = [](unsigned char c) { return !std::isspace(c); };
        s.erase(s.begin(), std::find_if(s.begin(), s.end(), notSpace));
        s.erase(std::find_if(s.rbegin(), s.rend(), notSpace).base(), s.end());
        return s;
    }

    std::string lower(std::string s)
    {
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return s;
    }
}

size_t PnachPatchSet::load(const std::string &paths, std::function<bool(uint32_t)> isCode)
{
    m_isCode = std::move(isCode);
    std::stringstream list(paths);
    std::string path;
    while (std::getline(list, path, ';'))
    {
        path = trim(path);
        if (path.empty())
            continue;
        std::ifstream file(path);
        if (!file)
        {
            std::cerr << "[pnach] cannot open " << path << std::endl;
            continue;
        }
        std::string line;
        int number = 0;
        size_t before = m_patches.size();
        while (std::getline(file, line))
        {
            ++number;
            parseLine(line, path, number);
        }
        std::cerr << "[pnach] " << path << ": " << (m_patches.size() - before) << " data patch(es)" << std::endl;
    }
    return m_patches.size();
}

bool PnachPatchSet::parseLine(const std::string &raw, const std::string &file, int number)
{
    std::string line = raw;
    if (const auto comment = line.find("//"); comment != std::string::npos)
        line.resize(comment);
    line = trim(line);
    if (lower(line.substr(0, 6)) != "patch=")
        return false; // gametitle, [sections], author, description, gsaspectratio...
    std::vector<std::string> fields;
    std::stringstream parts(line.substr(6));
    std::string field;
    while (std::getline(parts, field, ','))
        fields.push_back(trim(field));
    if (fields.size() != 5 || lower(fields[1]) != "ee")
    {
        std::cerr << "[pnach] " << file << ":" << number << " unsupported: " << raw << std::endl;
        return false;
    }
    Patch patch;
    patch.place = static_cast<uint8_t>(std::strtoul(fields[0].c_str(), nullptr, 10));
    const uint32_t address = static_cast<uint32_t>(std::strtoul(fields[2].c_str(), nullptr, 16));
    const std::string type = lower(fields[3]);
    const uint32_t value = static_cast<uint32_t>(std::strtoul(fields[4].c_str(), nullptr, 16));
    if (type == "byte" || type == "short" || type == "word")
    {
        patch.width = type == "byte" ? 1 : type == "short" ? 2 : 4;
        patch.address = address & 0x01FFFFFFu;
        patch.value = value;
    }
    else if (type == "extended")
    {
        const uint32_t code = address >> 28;
        if (code <= 2u)
        {
            patch.width = code == 0u ? 1 : code == 1u ? 2 : 4;
            patch.address = address & 0x01FFFFFFu;
            patch.value = value;
        }
        else if (code == 0xEu)
        {
            patch.width = 0;
            patch.skip = static_cast<uint8_t>((address >> 16) & 0xFFu);
            patch.value = address & 0xFFFFu;
            patch.compare = static_cast<uint8_t>(value >> 28);
            patch.compareAddress = value & 0x01FFFFFFu;
        }
        else
        {
            std::cerr << "[pnach] " << file << ":" << number << " unsupported extended code: " << raw << std::endl;
            return false;
        }
    }
    else
    {
        std::cerr << "[pnach] " << file << ":" << number << " unsupported type: " << raw << std::endl;
        return false;
    }
    if (patch.width != 0 && m_isCode && m_isCode(patch.address & ~3u))
    {
        std::cerr << "[pnach] " << file << ":" << number << " rewrites recompiled code at 0x" << std::hex
                  << patch.address << std::dec << " - ignored (needs a recompiler patch)" << std::endl;
        // Keep a no-op slot so conditional skip counts stay aligned.
        patch.width = 0xFF;
    }
    m_patches.push_back(patch);
    return true;
}

void PnachPatchSet::apply(uint8_t *rdram, bool firstVsync)
{
    if (!rdram)
        return;
    for (size_t i = 0; i < m_patches.size(); ++i)
    {
        const Patch &patch = m_patches[i];
        if (patch.width == 0)
        {
            uint16_t current = 0;
            if (patch.compareAddress + 2u <= kRamSize)
                std::memcpy(&current, rdram + patch.compareAddress, 2);
            bool pass = false;
            switch (patch.compare)
            {
            case 0: pass = current == patch.value; break;
            case 1: pass = current != patch.value; break;
            case 2: pass = current < patch.value; break;
            case 3: pass = current > patch.value; break;
            default: break;
            }
            if (!pass)
                i += patch.skip;
            continue;
        }
        if (patch.width == 0xFF || (patch.place == 0 && !firstVsync) || patch.address + patch.width > kRamSize)
            continue;
        std::memcpy(rdram + patch.address, &patch.value, patch.width);
    }
}

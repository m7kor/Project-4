#pragma once

// PCSX2 .pnach patches for the recompiled runtime (PS2X_PNACH=<file>[;<file>]).
//
// patch=<place>,EE,<address>,<type>,<value>
//   place 0: applied once, at the first vsync; 1: re-applied every vsync.
//   type byte/short/word, or extended (address top nibble: 0 = 8-bit,
//   1 = 16-bit, 2 = 32-bit, E = conditional "E0nnvvvv taaaaaaa": run the next
//   nn lines only if the 16-bit value at a compares with vvvv (t: 0 ==, 1 !=,
//   2 <, 3 >)).
//
// Only data patches take effect. In a static recompile the guest instructions
// are already C++, so a patch that rewrites code changes nothing at runtime;
// those are reported once and must become recompiler patches instead.

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

class PnachPatchSet
{
public:
    // Loads every file in a ';'-separated list. Returns the number of patches.
    // isCode(address) tells whether the address holds recompiled code.
    size_t load(const std::string &paths, std::function<bool(uint32_t)> isCode);
    // Applies the patches for this vsync to guest RAM (32 MB).
    void apply(uint8_t *rdram, bool firstVsync);
    bool empty() const { return m_patches.empty(); }

private:
    struct Patch
    {
        uint8_t place = 1;
        uint8_t width = 4; // 1, 2, 4 bytes; 0 = conditional
        uint32_t address = 0;
        uint32_t value = 0;
        // conditional
        uint8_t skip = 0;
        uint8_t compare = 0;
        uint32_t compareAddress = 0;
    };
    bool parseLine(const std::string &line, const std::string &file, int number);
    std::vector<Patch> m_patches;
    std::function<bool(uint32_t)> m_isCode;
};

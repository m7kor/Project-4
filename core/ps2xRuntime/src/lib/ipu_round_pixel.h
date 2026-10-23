#pragma once

#include <cstdint>

namespace ps2x::ipu
{
    // IDCT inputs are finite. Saturate first so the integer conversion is
    // bounded, then implement lround's ties-away-from-zero rule exactly.
    // Subtracting the truncated integer retains the fractional half boundary;
    // adding +/- 0.5 before truncation can round a neighboring value wrongly.
    inline int16_t roundPixel(double value, bool intra) noexcept
    {
        const int lower = intra ? 0 : -256;
        if (value <= lower) return static_cast<int16_t>(lower);
        if (value >= 255.0) return 255;
        const int whole = static_cast<int>(value);
        const double fraction = value - whole;
        return static_cast<int16_t>(whole + (fraction >= 0.5) - (fraction <= -0.5));
    }
}

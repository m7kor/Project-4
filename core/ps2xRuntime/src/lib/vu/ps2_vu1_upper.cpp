#include <emmintrin.h>
#include "runtime/ps2_vu1.h"
#include "ps2_vu1_detail.h"

#include <cmath>
#include <cstring>
#include <limits>

namespace
{
    int32_t vuFloatToInt(float value, float scale)
    {
        const double scaled = static_cast<double>(value) * static_cast<double>(scale);
        if (scaled >= static_cast<double>(std::numeric_limits<int32_t>::max()))
            return std::numeric_limits<int32_t>::max();
        if (scaled <= static_cast<double>(std::numeric_limits<int32_t>::min()))
            return std::numeric_limits<int32_t>::min();
        return static_cast<int32_t>(scaled);
    }
}

// ============================================================================
// Upper instructions (FMAC pipeline)
// ============================================================================
// Always inlined into the per-pair step: a compiled microprogram passes a
// constant instruction and the whole decode switch folds away.
PS2X_VU1_STEP_INLINE void VU1Interpreter::execUpper(uint32_t instr)
{
    auto &vu = *this;
    constexpr uint8_t Clean = 0;
#define PS2X_VU1_FMAC_DEST(dst, result, dest) vu.applyFmacDest(dst, result, dest)
#define PS2X_VU1_FMAC_ACC(result, dest) vu.applyFmacDestAcc(result, dest)
#include "ps2_vu1_upper_body.inl"
#undef PS2X_VU1_FMAC_ACC
#undef PS2X_VU1_FMAC_DEST
}

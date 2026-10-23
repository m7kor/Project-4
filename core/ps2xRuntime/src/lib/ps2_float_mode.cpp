#include <cstdint>
#include <cstdlib>
#include <iostream>

// See PS2X_FLOAT_LEGACY in ps2_runtime_macros.h. The default keeps IEEE
// add/sub (no guard-bit truncation) and IEEE compares, the closest match to
// the code the RE4 runs were validated with. A first A/B round suggested the
// two PS2 forms stopped the car cutscene, but repeats showed that stop is a
// timing race independent of the mask (2026-10-11), so this default is a
// conservative choice, not a measured fix. Clamps, PS2 divide/sqrt and
// CVT.W.S truncation stay on.
uint32_t g_ps2FloatLegacy = []
{
    constexpr uint32_t kDefault = 1u | 8u;
    const char *value = std::getenv("PS2X_FLOAT_LEGACY");
    const uint32_t mask = value ? static_cast<uint32_t>(std::strtoul(value, nullptr, 0)) : kDefault;
    std::cerr << "[float] PS2X_FLOAT_LEGACY=0x" << std::hex << mask << std::dec
              << (value ? " from environment" : " default") << " (IEEE behaviour restored for these groups)\n";
    return mask;
}();

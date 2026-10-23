#include "MiniTest.h"
#include "ps2_runtime_macros.h"
#include <array>
#include <cstring>

extern "C" void ps2MmiPermutationProbe(R5900Context *, unsigned, unsigned);

void register_mmi_permutation_tests()
{
    // Independent lane maps from EE semantics, also checked against PCSX2 MMI.cpp.
    static constexpr const char *names[] = {"PEXEH", "PREVH", "PEXEW", "PROT3W", "PEXCH", "PEXCW"};
    static constexpr unsigned laneMap[6][8] = {
        {2,1,0,3,6,5,4,7}, {3,2,1,0,7,6,5,4}, {4,5,2,3,0,1,6,7},
        {2,3,4,5,0,1,6,7}, {0,2,1,3,4,6,5,7}, {0,1,4,5,2,3,6,7}};
    MiniTest::Case("compiled EE MMI permutation semantics", [](TestCase &tc) {
        for (unsigned op = 0; op < 6; ++op)
            tc.Run(names[op], [op](TestCase &t) {
                for (unsigned mode = 0; mode < 4; ++mode) {
                    R5900Context ctx{};
                    const std::array<uint16_t, 8> input = {0x0112,0x2345,0x4567,0x6789,0x89AB,0xABCD,0xCDEF,0xEF01};
                    std::memcpy(&ctx.r[5], input.data(), 16);
                    ctx.r[4] = _mm_set1_epi32(0x12345678);
                    ps2MmiPermutationProbe(&ctx, op, mode);
                    std::array<uint16_t, 8> actual{}, expected{};
                    const unsigned dest = mode == 2 ? 0 : mode == 1 ? 5 : 3;
                    std::memcpy(actual.data(), &ctx.r[dest], 16);
                    if (mode < 2)
                        for (unsigned lane = 0; lane < 8; ++lane) expected[lane] = input[laneMap[op][lane]];
                    t.IsTrue(actual == expected, "exact 128-bit output for distinct/aliased/zero destination/source");
                    if (mode != 1)
                        t.IsTrue(std::memcmp(&ctx.r[5], input.data(), 16) == 0, "non-destination rt stays unchanged");
                    t.Equals(_mm_cvtsi128_si32(ctx.r[4]), 0x12345678, "unused rs must stay untouched");
                }
            });
    });
}

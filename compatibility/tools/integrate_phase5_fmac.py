"""Preserve rejected retirement variants; batch the existing safe-normal predicate."""
from pathlib import Path
import hashlib,json,difflib
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
current=source.read_bytes();assert hashlib.sha256(current).hexdigest()=='6ec6b44fa7ccd39aea49156f6f5b547e7f4626399184f78de8c63fab01dcc09d'
before=(ROOT/'artifacts/phase5/vector-01/before-core.cpp').read_bytes()
(ROOT/'artifacts/phase5/vector-01/rejected-core.cpp').write_bytes(current)
(ROOT/'reports/PHASE5_VECTOR_RETIRE_REJECTED.patch').write_text(''.join(difflib.unified_diff(before.decode().splitlines(True),current.decode().splitlines(True),fromfile='a/ps2_vu1_core.cpp',tofile='b/ps2_vu1_core.cpp')),encoding='utf-8')
out=ROOT/'artifacts/phase5/fmac-01';out.mkdir(exist_ok=False)
table=', '.join(f'0x{sum((2 if signs&(1<<c) else 0)<<(8*c) for c in range(4)):08x}u' for signs in range(16))
helper='''#if defined(_M_X64) || defined(__x86_64__) || defined(__SSE2__)
#include <emmintrin.h>
#define PS2X_FMAC_CLASSIFY_SSE2 1
#endif

// Batch ONLY the existing exponent2..253 shortcut. No arithmetic or rounding.
// Boundary exponents and any exceptional selected lane use the original path.
bool ps2Vu1ClassifyNormalFmac(const float *value, uint8_t dest, uint8_t laneFlags[4])
{
    dest &= 15u;
    if (!dest) { std::memset(laneFlags, 0, 4); return true; }
#if defined(PS2X_FMAC_CLASSIFY_SSE2)
    static constexpr uint8_t reversed[16] = {0,8,4,12,2,10,6,14,1,9,5,13,3,11,7,15};
    static constexpr uint32_t signFlags[16] = {'''+table+'''};
    const uint32_t selected = reversed[dest];
    const __m128 bits = _mm_loadu_ps(value);
    const __m128i magnitude = _mm_and_si128(_mm_castps_si128(bits), _mm_set1_epi32(0x7fffffff));
    const __m128i lower = _mm_cmpgt_epi32(magnitude, _mm_set1_epi32(0x00ffffff));
    const __m128i upper = _mm_cmpgt_epi32(_mm_set1_epi32(0x7f000000), magnitude);
    const uint32_t normal = static_cast<uint32_t>(_mm_movemask_ps(_mm_castsi128_ps(_mm_and_si128(lower, upper))));
    if ((normal & selected) != selected) return false;
    const uint32_t packed = signFlags[static_cast<uint32_t>(_mm_movemask_ps(bits)) & selected];
    std::memcpy(laneFlags, &packed, 4);
    return true;
#else
    uint8_t flags[4]{};
    for (uint32_t component = 0; component < 4; ++component)
    {
        if (!(dest & (8u >> component))) continue;
        uint32_t bits;std::memcpy(&bits, value + component, sizeof(bits));
        const uint32_t exponent=(bits >> 23)&255u;
        if (exponent < 2u || exponent > 253u) return false;
        flags[component]=static_cast<uint8_t>((bits >> 30)&2u);
    }
    std::memcpy(laneFlags,flags,4);return true;
#endif
}
static const bool fmacClassifyEnabled = [] {
    const char *value = std::getenv("PS2X_VU1_FMAC_CLASSIFY");
    return value && *value == '1';
}();

'''
text=before.decode('utf-8').replace('\r\n','\n');needle='// Internal algebra shared';assert text.count(needle)==1;text=text.replace(needle,helper+needle)
needle='''void VU1Interpreter::normalizeFmacResult(float *result, uint8_t dest,
                                         uint8_t laneFlags[4])
{''';assert text.count(needle)==1
text=text.replace(needle,needle+'\n    if (fmacClassifyEnabled && ps2Vu1ClassifyNormalFmac(result, dest, laneFlags))\n        return;')
after=text.replace('\n','\r\n' if b'\r\n' in before else '\n').encode();source.write_bytes(after)
(out/'before-core.cpp').write_bytes(before)
(out/'source.json').write_text(json.dumps({'source_sha256':hashlib.sha256(after).hexdigest(),'baseline_sha256':hashlib.sha256(before).hexdigest(),'mode':'PS2X_VU1_FMAC_CLASSIFY=1','default':False,'scope':'Batch integer classification of the pre-existing exponent2..253 shortcut. Original exceptional/rounding/math and pipeline scheduling unchanged.'},indent=2))
print('FMAC classification prototype installed, default OFF')

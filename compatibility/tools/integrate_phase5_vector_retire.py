"""Reject the slower index; prototype stateless bitwise vector retirement."""
from pathlib import Path
import hashlib,json,difflib
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
rejected=ROOT/'artifacts/phase5/pipeline-02'
current=path.read_bytes();assert hashlib.sha256(current).hexdigest()=='2b16934e3ead8bb60775861a98be35b5b63b9ebe8e0d45433141b74597a1f00d'
before=(rejected/'before-core.cpp').read_bytes();assert hashlib.sha256(before).hexdigest()=='48077ba02c66e8d0dc0efe6182db011ca2d7575db19e6b4f1e03412dfd207f98'
(rejected/'rejected-core.cpp').write_bytes(current)
(ROOT/'reports/PHASE5_PIPELINE_INDEX_REJECTED.patch').write_text(''.join(difflib.unified_diff(before.decode().splitlines(True),current.decode().splitlines(True),fromfile='a/ps2_vu1_core.cpp',tofile='b/ps2_vu1_core.cpp')),encoding='utf-8')
text=before.decode('utf-8').replace('\r\n','\n')
out=ROOT/'artifacts/phase5/vector-01';out.mkdir(exist_ok=False)
table=',\n'.join('        {'+', '.join('0xffffffffu' if mask&(8>>c) else '0u' for c in range(4))+'}' for mask in range(16))
helper='''#if defined(USE_SSE41) || defined(__SSE4_1__)
#include <smmintrin.h>
#define PS2X_VECTOR_RETIRE_SSE41 1
#endif

// Bit selection only: preserve payload bits, including NaNs and signed zero.
// Kept externally callable for an independent procedural equivalence witness.
void ps2Vu1RetireVectorWrite(float *destination, const float *value,
                            const uint64_t *latest, uint64_t sequence, uint8_t lanes)
{
#if defined(PS2X_VECTOR_RETIRE_SSE41)
    alignas(16) static constexpr uint32_t masks[16][4] = {
'''+table+'''};
    const __m128i wanted = _mm_set1_epi64x(static_cast<long long>(sequence));
    const __m128i low = _mm_cmpeq_epi64(_mm_loadu_si128(reinterpret_cast<const __m128i *>(latest)), wanted);
    const __m128i high = _mm_cmpeq_epi64(_mm_loadu_si128(reinterpret_cast<const __m128i *>(latest + 2)), wanted);
    const __m128 equal = _mm_shuffle_ps(_mm_castsi128_ps(low), _mm_castsi128_ps(high), _MM_SHUFFLE(2, 0, 2, 0));
    const __m128 mask = _mm_and_ps(equal, _mm_castsi128_ps(_mm_load_si128(reinterpret_cast<const __m128i *>(masks[lanes & 15u]))));
    const __m128 oldValue = _mm_loadu_ps(destination);
    const __m128 newValue = _mm_loadu_ps(value);
    _mm_storeu_ps(destination, _mm_or_ps(_mm_and_ps(mask, newValue), _mm_andnot_ps(mask, oldValue)));
#else
    for (uint32_t component = 0; component < 4; ++component)
        if ((lanes & (8u >> component)) && latest[component] == sequence)
            std::memcpy(destination + component, value + component, sizeof(float));
#endif
}
static const bool vectorRetirementEnabled = [] {
    const char *value = std::getenv("PS2X_VU1_VECTOR_RETIRE");
    return value && *value == '1';
}();

'''
needle='// Internal algebra shared';assert text.count(needle)==1;text=text.replace(needle,helper+needle)
for kind,array,destination,latest in [('vf','m_vfWritePipeline','m_state.vf[write.reg]','m_vfLatestWrite[write.reg].data()'),('acc','m_accWritePipeline','m_state.acc','m_accLatestWrite.data()')]:
 start=text.index('    for (uint32_t pending = m_'+kind+'Pending;',text.index('void VU1Interpreter::commitReadyPipelines'))
 end=text.index('\n    }',start)+6
 block=text[start:end];needle='''            for (uint32_t component = 0; component < 4u; ++component)''';assert block.count(needle)==1
 block=block.replace(needle,'            if (vectorRetirementEnabled)\n                ps2Vu1RetireVectorWrite('+destination+', write.value.data(), '+latest+', write.sequence, write.laneMask);\n            else\n'+needle)
 text=text[:start]+block+text[end:]
after=text.replace('\n','\r\n' if b'\r\n' in before else '\n').encode();path.write_bytes(after)
(out/'source.json').write_text(json.dumps({'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),'default':False,'mode':'PS2X_VU1_VECTOR_RETIRE=1','scope':'VF/ACC lane-and-sequence bitwise selection only, original event scheduling/order; no floating-point arithmetic changes'},indent=2))
(out/'before-core.cpp').write_bytes(before)
print('Slower run-scoped index archived; stateless SIMD retirement prototype installed, default OFF')

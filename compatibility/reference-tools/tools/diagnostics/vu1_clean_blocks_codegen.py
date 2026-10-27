"""Generate opt-in VU1 blocks with conservative normalized-lane facts.

Uses the existing exported pairs and source bodies shared with the interpreter.
It never changes the default pair tables or PS2 timing. Specialized methods in
the already-friended VU1CompiledPrograms include those same source bodies.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

def arithmetic_body(source):
    if source.count('#include "ps2_vu1_upper_body.inl"') != 1 or 'void VU1Interpreter::execUpper(' not in source:
        raise ValueError('Upper reference must use the shared semantic body')
    return """

    template <bool FlagsLive, bool Accumulator>
    static PS2X_VU1_STEP_INLINE void finishFmac(VU1Interpreter &vu, float *dst, float *result, uint8_t dest)
    {
        if constexpr (FlagsLive)
        {
            if constexpr (Accumulator) vu.applyFmacDestAcc(result, dest);
            else vu.applyFmacDest(dst, result, dest);
        }
        else
        {
            if (g_vu1CleanTrace) ++g_vu1CompiledDeadFmac;
            // Copy only written lanes: future arithmetic instructions need not
            // initialize an unwritten component. No read of indeterminate data.
            alignas(16) float normalized[4]{};
            for (uint32_t component = 0; component < 4; ++component)
                if (dest & laneForComponent(component)) normalized[component] = result[component];
            const __m128i bits = _mm_castps_si128(_mm_load_ps(normalized));
            const __m128i exponentMask = _mm_set1_epi32(0x7F800000);
            const __m128i sign = _mm_and_si128(bits, _mm_set1_epi32(static_cast<int>(0x80000000u)));
            const __m128i exponent = _mm_and_si128(bits, exponentMask);
            const __m128i zero = _mm_cmpeq_epi32(exponent, _mm_setzero_si128());
            const __m128i maximum = _mm_cmpeq_epi32(exponent, exponentMask);
            __m128i value = _mm_andnot_si128(_mm_or_si128(zero, maximum), bits);
            value = _mm_or_si128(value, _mm_and_si128(zero, sign));
            value = _mm_or_si128(value, _mm_and_si128(maximum, _mm_or_si128(sign, _mm_set1_epi32(0x7F7FFFFF))));
            _mm_store_ps(normalized, _mm_castsi128_ps(value));
            if (dest & 8u) dst[0] = normalized[0];
            if (dest & 4u) dst[1] = normalized[1];
            if (dest & 2u) dst[2] = normalized[2];
            if (dest & 1u) dst[3] = normalized[3];
        }
    }

    template <const P &K, uint8_t Clean>
    static PS2X_VU1_STEP_INLINE void upperClean(VU1Interpreter &vu, uint32_t instr)
    {
        if constexpr (Clean != 0) if (g_vu1CleanTrace) ++g_vu1CompiledBlockSteps;
#define PS2X_VU1_FMAC_DEST(dst, result, dest) finishFmac<K.flagsLive, false>(vu, dst, result, dest)
#define PS2X_VU1_FMAC_ACC(result, dest) finishFmac<K.flagsLive, true>(vu, vu.m_state.acc, result, dest)
#include "../ps2_vu1_upper_body.inl"
#undef PS2X_VU1_FMAC_ACC
#undef PS2X_VU1_FMAC_DEST
    }
"""


def scheduling_body(source):
    if source.count('#include "ps2_vu1_step_body.inl"') != 1 or 'int VU1Interpreter::stepPairBody(' not in source:
        raise ValueError('Reference scheduling must use the shared body')
    return """
    template <const P &K, uint8_t Clean>
    static PS2X_VU1_STEP_INLINE int stepClean(VU1Interpreter &vu, uint8_t *vuData, uint32_t dataSize,
            GS &gs, PS2Memory *memory, uint32_t codeSize, uint64_t budgetEnd, bool &programEnded)
    {
        vu.m_pairFlagsDirect = K.flagsDirect;
        vu.m_pairProductSum = K.productSum;
        vu.m_pairStoreDirect = K.storeDirect;
        vu.m_pairFlagsLive = K.flagsLive;
        const P &decoded = K;
#define PS2X_VU1_ISSUE_UPPER(instruction) upperClean<K, Clean>(vu, instruction)
#include "../ps2_vu1_step_body.inl"
#undef PS2X_VU1_ISSUE_UPPER
    }
"""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Unexpected generated source shape: ' + old)
    return source.replace(old, new)


def usage(text):
    writes = re.search(r'\.vfWrite = \{(\d+), (\d+)\}', text)
    reads = re.search(r'\.vfRead = \{\{\{(\d+), (\d+)\}, \{(\d+), (\d+)\}\}\}', text)
    if not writes or not reads:
        raise ValueError('Malformed decoded VF accesses')
    def number(name):
        found = re.search(r'\.' + name + r' = (\d+)', text)
        if not found:
            raise ValueError('Missing decoded ' + name)
        return int(found[1])
    values = list(map(int, reads.groups()))
    return {'write': tuple(map(int, writes.groups())), 'reads': list(zip(values[::2], values[1::2]))[:number('vfReadCount')],
            'acc_read': number('accRead'), 'acc_write': number('accWrite')}


def pair(text):
    parts = re.search(r'\.lowerUsage = (.*?), \.upperUsage = (.*?), \.iBit', text)
    if not parts:
        raise ValueError('Malformed decoded pair')
    words = re.search(r'\.lower = 0x([0-9A-Fa-f]+)u, \.upper = 0x([0-9A-Fa-f]+)u', text)
    if not words:
        raise ValueError('Missing instruction words')
    return {'lower': int(words[1], 16), 'upper': int(words[2], 16), 'lo': usage(parts[1]), 'hi': usage(parts[2]),
            'i_bit': '.iBit = true' in text}


def clean_masks(pairs):
    """No imported facts: even VF0 is unknown until the first exact step resets it."""
    lanes = [0] * 32
    acc = 0
    result = []
    for item in pairs:
        u = item['upper']
        fs, ft, op = (u >> 11) & 31, (u >> 16) & 31, u & 63
        def known(reg):
            required = 0
            for read_reg, read_mask in item['hi']['reads']:
                if read_reg == reg:
                    required |= read_mask
            return bool(required) and lanes[reg] & required == required
        required_acc = item['hi']['acc_read']
        mask = int(known(fs)) | (int(known(ft)) << 1)
        if required_acc and acc & required_acc == required_acc:
            mask |= 4
        result.append(mask)
        lower_reg, lower_mask = item['lo']['write']
        upper_reg, upper_mask = item['hi']['write']
        if lower_reg:
            lanes[lower_reg] &= ~lower_mask
        if upper_reg:
            lanes[upper_reg] &= ~upper_mask
            special = (u & 3) | ((u >> 4) & 0x7c)
            # All ordinary arithmetic normalizes outputs. ITOF's integer range
            # and scales produce normal floats/zero; FTOI produces raw bits.
            normalized = op <= 0x2f or (op >= 0x3c and (0x10 <= special <= 0x13 or special == 0x1d))
            if normalized:
                lanes[upper_reg] |= upper_mask & ~(lower_mask if lower_reg == upper_reg else 0)
        # All upper ACC writes in the semantic source pass applyFmacDestAcc.
        acc |= item['hi']['acc_write']
        lanes[0] = 15
    return result


def generate(base, upper, step, regions, block_size):
    if 'VU1CleanBlockGenerator' in base:
        raise ValueError('Input already contains clean blocks')
    if block_size not in (8, 16, 32, 64):
        raise ValueError('Block size must be 8,16,32,64')
    if not isinstance(regions, dict) or not regions:
        raise ValueError('At least one image region is required')
    constants = dict(re.findall(r'static constexpr P (k\d+) = ([^\n]+);', base))
    tables = {key: re.findall(r'&step<(k\d+)>', values) for key, values in
              re.findall(r'CompiledPairFn t_([0-9a-f]{16})\[2048\] = \{(.*?)\n    \};', base, re.S)}
    if not tables or any(len(t) != 2048 or any(k not in constants for k in t) for t in tables.values()):
        raise ValueError('Incomplete original pair tables')
    chunks = []
    report = []
    for key, spans in regions.items():
        if key not in tables or not spans:
            raise ValueError('Unknown or empty region image')
        occupied = set()
        entries = {}
        for begin, end in spans:
            if not (0 <= begin < end <= 0x4000) or begin % 8 or end % 8:
                raise ValueError('Unaligned or invalid region')
            pcs = set(range(begin, end, 8))
            if occupied & pcs:
                raise ValueError('Overlapping regions')
            occupied |= pcs
            heads = set(range(begin, end, 8 * block_size))
            heads.add(begin)
            for pc in range(begin, end, 8):
                item = pair(constants[tables[key][pc // 8]])
                l, u = item['lower'], item['upper']
                opcode = l >> 25
                if not item['i_bit'] and opcode in (0x20, 0x21, 0x24, 0x25, 0x28, 0x29, 0x2c, 0x2d, 0x2e, 0x2f):
                    if opcode not in (0x24, 0x25):
                        immediate = l & 0x7ff
                        immediate -= 0x800 if immediate & 0x400 else 0
                        target = (pc + 8 + immediate * 8) & 0x3fff
                        if begin <= target < end:
                            heads.add(target)
                    if pc + 16 < end:
                        heads.add(pc + 16)
            heads = sorted(heads)
            for index, start in enumerate(heads):
                finish = heads[index + 1] if index + 1 < len(heads) else end
                names = tables[key][start // 8:finish // 8]
                masks = clean_masks([pair(constants[name]) for name in names])
                name = f'clean_{key}_{start:04x}'
                entries[start // 8] = name
                chunks.append(f'    static int {name}(VU1Interpreter &vu, uint8_t *data, uint32_t dataSize, GS &gs, PS2Memory *memory, uint32_t codeSize, uint64_t budgetEnd, bool &programEnded)\n    {{\n')
                chunks.append('        if (g_vu1CleanTrace) ++g_vu1CompiledBlockEntries;\n')
                for offset, (constant, mask) in enumerate(zip(names, masks)):
                    pc = start + offset * 8
                    chunks.append(f'        if (stepClean<{constant}, {mask}>(vu, data, dataSize, gs, memory, codeSize, budgetEnd, programEnded)) return 1;\n')
                    if offset + 1 < len(names):
                        chunks.append(f'        if (vu.m_state.pc != {pc + 8}u || vu.m_cycle >= budgetEnd || vu.m_stopRequested || vu.m_state.pc + 8u > codeSize) return 0;\n')
                        chunks.append('        if (vu.m_cycle >= vu.m_nextCommitCycle || vu1ScanAll()) vu.commitReadyPipelines();\n')
                chunks.append('        return 0;\n    }\n')
                report.append({'hash': key, 'begin': start, 'end': finish, 'masks': masks})
        chunks.append(f'    static constexpr VU1Interpreter::CompiledPairFn c_{key}[2048] = {{\n')
        for index, constant in enumerate(tables[key]):
            chunks.append(('        ' if index % 8 == 0 else ' ') + ('&' + entries[index] if index in entries else f'&step<{constant}>') + ',' + ('\n' if index % 8 == 7 else ''))
        chunks.append('    };\n')
    helpers = arithmetic_body(upper) + scheduling_body(step)
    marker = '\nstruct VU1CompiledPrograms\n'
    if base.count(marker) != 1:
        raise ValueError('Unexpected generated class')
    output = base.replace(marker, '\n// VU1CleanBlockGenerator: generated from current semantics, experimental opt-in.\n'
                          'static const bool g_vu1CleanTrace = [] { const char *v = std::getenv("PS2X_VU1_TRACE_BLOCKS"); return v && *v == \'1\'; }();\n'
                          + marker)
    class_end = '\n};\n\nstatic const VU1Interpreter::CompiledPairFn *vu1FindCompiledProgram'
    if output.count(class_end) != 1:
        raise ValueError('Unexpected generated class end')
    output = output.replace(class_end, helpers + ''.join(chunks) + class_end)
    for key in regions:
        original = f'case 0x{key}ull: return VU1CompiledPrograms::t_{key};'
        selected = f'case 0x{key}ull: return clean ? VU1CompiledPrograms::c_{key} : VU1CompiledPrograms::t_{key};'
        output = replace_once(output, original, selected)
    signature = 'vu1FindCompiledProgram(uint64_t hash)\n{'
    output = replace_once(output, signature, signature + '\n    static const bool clean = [] { const char *v = std::getenv("PS2X_VU1_CLEAN_BLOCKS"); return v && *v == \'1\'; }();')
    return output, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('--upper', type=Path, required=True)
    parser.add_argument('--step', type=Path, required=True)
    parser.add_argument('--regions', type=Path, required=True)
    parser.add_argument('--block-size', type=int, default=16)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve() == args.report.resolve() or args.out.exists() or args.report.exists():
        raise ValueError('Use distinct, new output and report files')
    paths = (args.base, args.upper, args.step, args.regions,
             args.upper.parent / 'ps2_vu1_upper_body.inl', args.step.parent / 'ps2_vu1_step_body.inl')
    texts = [p.read_text(encoding='utf-8') for p in paths]
    output, blocks = generate(*texts[:3], json.loads(texts[3]), args.block_size)
    report = {'scope': __doc__, 'block_size': args.block_size, 'blocks': blocks,
              'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'input_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              'output_sha256': hashlib.sha256(output.encode()).hexdigest()}
    # Validate everything before opening either output; never truncate on invalid input.
    with args.out.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(output)
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({'blocks': len(blocks), 'specialized_pairs': sum(m != 0 for b in blocks for m in b['masks']),
                      'output_sha256': report['output_sha256']}))


if __name__ == '__main__':
    main()

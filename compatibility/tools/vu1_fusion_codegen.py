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


PIPELINE_FDIV, PIPELINE_EFU, PIPELINE_BRANCH, PIPELINE_XGKICK = 3, 4, 6, 7
SCOREBOARD_LATENCY_MAX = 4  # largest VF/VI latency the decoder attaches to a scoreboard write
ACC_FORWARD_LATENCY = 1     # VU1Interpreter::kAccForwardLatency


def full_usage(text):
    """Every InstructionUsage field the scheduler reads, from one generated initializer."""
    reads = re.search(r'\.vfRead = \{\{\{(\d+), (\d+)\}, \{(\d+), (\d+)\}\}\}', text)
    write = re.search(r'\.vfWrite = \{(\d+), (\d+)\}', text)
    if not reads or not write:
        raise ValueError('Malformed decoded VF accesses')
    def number(name):
        found = re.search(r'\.' + name + r' = (\d+)', text)
        if not found:
            raise ValueError('Missing decoded ' + name)
        return int(found[1])
    def flag(name):
        found = re.search(r'\.' + name + r' = (true|false)', text)
        if not found:
            raise ValueError('Missing decoded ' + name)
        return found[1] == 'true'
    pipeline = re.search(r'\.pipeline = static_cast<VU1Interpreter::Pipeline>\((\d+)\)', text)
    if not pipeline:
        raise ValueError('Missing decoded pipeline')
    values = list(map(int, reads.groups()))
    return {'vf_reads': list(zip(values[::2], values[1::2]))[:number('vfReadCount')],
            'vf_write': tuple(map(int, write.groups())), 'vi_read': number('viRead'), 'vi_write': number('viWrite'),
            'acc_read': number('accRead'), 'acc_write': number('accWrite'), 'latency': number('latency'),
            'vf_latency': number('vfLatency'), 'vi_latency': number('viLatency'), 'pipeline': int(pipeline[1]),
            'wait_q': flag('waitQ'), 'wait_p': flag('waitP'), 'reserved': flag('reserved')}


def full_pair(text):
    parts = re.search(r'\.lowerUsage = (.*?), \.upperUsage = (.*?), \.iBit', text)
    if not parts:
        raise ValueError('Malformed decoded pair')
    def flag(name):
        found = re.search(r'\.' + name + r' = (true|false)', text)
        if not found:
            raise ValueError('Missing decoded ' + name)
        return found[1] == 'true'
    suppressed = re.search(r'\.suppressedLowerVf = (\d+)', text)
    if not suppressed:
        raise ValueError('Missing suppressedLowerVf')
    return {'lo': full_usage(parts[1]), 'hi': full_usage(parts[2]), 'e_bit': flag('eBit'), 'd_bit': flag('dBit'),
            't_bit': flag('tBit'), 'suppressed_lower_vf': int(suppressed[1]),
            'upper_vf_direct': flag('upperVfDirect'), 'lower_vf_direct': flag('lowerVfDirect'),
            'acc_direct': flag('accDirect'), 'vi_direct': flag('viDirect')}


def result_paths(p):
    """Slots each result of ps2_vu1_step_issue.inl writes at issue (direct) or through a queue.

    Returns (direct slots, [(queued slot, latency)]), following hasUpperWrite,
    hasDistinctLowerWrite, the ACC write and writtenVi exactly.
    """
    lo, hi = p['lo'], p['hi']
    direct, queued = [], []
    upper_reg, upper_lanes = hi['vf_write']
    lower_reg, lower_lanes = lo['vf_write']
    has_upper = upper_reg != 0
    has_lower = lower_reg != 0 and p['suppressed_lower_vf'] != lower_reg
    distinct_lower = has_lower and (not has_upper or lower_reg != upper_reg)
    def lanes(reg, mask):
        return [('vf', reg, c) for c in range(4) if mask & (8 >> c)]
    if has_upper:
        if p['upper_vf_direct']:
            direct += lanes(upper_reg, upper_lanes)
        else:
            queued += [(s, hi['vf_latency'] or hi['latency']) for s in lanes(upper_reg, upper_lanes)]
    if distinct_lower:
        if p['lower_vf_direct']:
            direct += lanes(lower_reg, lower_lanes)
        else:
            queued += [(s, lo['vf_latency'] or lo['latency']) for s in lanes(lower_reg, lower_lanes)]
    if hi['acc_write']:
        slots = [('acc', c) for c in range(4) if hi['acc_write'] & (8 >> c)]
        if p['acc_direct']:
            direct += slots
        else:
            queued += [(s, ACC_FORWARD_LATENCY) for s in slots]
    vi_writes = lo['vi_write'] & 0xFFFE
    if vi_writes:
        reg = (vi_writes & -vi_writes).bit_length() - 1
        if p['vi_direct']:
            direct.append(('vi', reg))
        else:
            queued.append((('vi', reg), lo['vi_latency'] or lo['latency']))
    for (_, latency) in queued:
        if latency > SCOREBOARD_LATENCY_MAX:
            raise ValueError('Queued result latency above the fused-block bound')
    return direct, queued


def scoreboard_writes(p):
    """(slot, latency) in VU1Interpreter::markPairWrites order; later entries overwrite earlier ones."""
    out = []
    lo, hi = p['lo'], p['hi']
    reg, lanes = lo['vf_write']
    if reg != 0 and p['suppressed_lower_vf'] != reg:
        latency = lo['vf_latency'] or lo['latency']
        out += [(('vf', reg, c), latency) for c in range(4) if lanes & (8 >> c)]
    reg, lanes = hi['vf_write']
    if reg != 0:
        latency = hi['vf_latency'] or hi['latency']
        out += [(('vf', reg, c), latency) for c in range(4) if lanes & (8 >> c)]
    for reg in range(1, 16):
        if lo['vi_write'] & (1 << reg):
            out.append((('vi', reg), lo['vi_latency'] or lo['latency']))
    out += [(('acc', c), ACC_FORWARD_LATENCY) for c in range(4) if hi['acc_write'] & (8 >> c)]
    for (_, latency) in out:
        if latency > SCOREBOARD_LATENCY_MAX:
            raise ValueError('Scoreboard latency above the fused-block bound')
    return out


def scoreboard_reads(p):
    """Slots VU1Interpreter::calculatePairReadyCycle compares, for both usages."""
    out = []
    for usage in (p['hi'], p['lo']):
        for reg, lanes in usage['vf_reads']:
            out += [('vf', reg, c) for c in range(4) if lanes & 0xF & (8 >> c)]
        out += [('vi', reg) for reg in range(1, 16) if usage['vi_read'] & (1 << reg)]
        out += [('acc', c) for c in range(4) if usage['acc_read'] & 0xF & (8 >> c)]
    return out


def resource_conditions(p):
    lo = p['lo']
    conditions = []
    if lo['pipeline'] == PIPELINE_FDIV or lo['wait_q']:
        conditions.append('(vu.m_fdiv.valid && vu.m_fdiv.readyCycle > vu.m_cycle)')
    if lo['pipeline'] == PIPELINE_EFU:
        conditions.append('vu.m_efuResourceReady > vu.m_cycle')
    if lo['wait_p']:
        conditions.append('((vu.m_efu[0].valid && vu.m_efu[0].readyCycle > vu.m_cycle) || '
                          '(vu.m_efu[1].valid && vu.m_efu[1].readyCycle > vu.m_cycle))')
    if lo['pipeline'] == PIPELINE_XGKICK:
        conditions.append('vu.m_xgkick.active')
    return conditions


def slot_expression(slot):
    if slot[0] == 'vf':
        return f'vu.m_vfReady[{slot[1]}][{slot[2]}]'
    if slot[0] == 'vi':
        return f'vu.m_viReady[{slot[1]}]'
    return f'vu.m_accReady[{slot[1]}]'


def fused_plan(pairs):
    """Fast region [0, F): pairs issued back to back without a stall.

    A pair ends the region when it is a branch, carries E/D/T, is reserved, or reads a
    scoreboard slot written inside the region fewer pairs ago than that write's latency
    (it would certainly stall). Writes issued before the block (latency <= 4) can delay
    only pairs 0..2, so VF/VI reads of slots not yet written inside the region are
    checked dynamically there; ACC (latency 1) never delays a later pair. Pipeline
    resources (FDIV/EFU/WAITQ/WAITP/XGKICK) are always checked dynamically.
    """
    last = {}
    snapshots = []  # last-writer map after each executed pair
    checks = []
    stamps = []        # a direct write must stamp: an older queued write to its lanes may be pending
    queued_ready = {}  # slot -> latest ready offset (pairs from entry) of a queued write in the region
    region = len(pairs)
    branch_at = None
    for i, p in enumerate(pairs):
        if p['lo']['reserved'] or p['hi']['reserved'] or p['e_bit'] or p['d_bit'] or p['t_bit']:
            region = i
            break
        if branch_at is not None:
            # The delay slot ends the region; another branch here keeps the exact path.
            if p['lo']['pipeline'] == PIPELINE_BRANCH:
                region = i
                break
        elif p['lo']['pipeline'] == PIPELINE_BRANCH:
            if i + 1 >= len(pairs):
                region = i
                break
            branch_at = i
        dynamic = []
        hazard = False
        for slot in scoreboard_reads(p):
            if slot in last:
                j, latency = last[slot]
                if i - j < latency:
                    hazard = True
                    break
            elif slot[0] in ('vf', 'vi') and i < SCOREBOARD_LATENCY_MAX - 1 and slot not in dynamic:
                dynamic.append(slot)
        if hazard:
            region = i
            break
        checks.append([f'{slot_expression(s)} > vu.m_cycle' for s in dynamic] + resource_conditions(p))
        direct, queued = result_paths(p)
        # A queued VF/VI write from before the block (latency <= 4) can still be pending at
        # pairs 0..2; one queued at pair j of the region while i < j + latency. A queued ACC
        # write (latency 1) has retired before the next pair issues.
        stamps.append(any((s[0] in ('vf', 'vi') and i < SCOREBOARD_LATENCY_MAX - 1) or queued_ready.get(s, 0) > i
                          for s in direct))
        for slot, latency in queued:
            queued_ready[slot] = max(queued_ready.get(slot, 0), i + latency)
        for slot, latency in scoreboard_writes(p):
            last[slot] = (i, latency)
        snapshots.append(dict(last))
        if branch_at is not None and i == branch_at + 1:
            region = i + 1
            break
    # A branch whose delay slot did not qualify stays on the exact path.
    if branch_at is not None and region <= branch_at + 1:
        region = min(region, branch_at)
        checks, snapshots = checks[:region], snapshots[:region]
    stamps = stamps[:region]
    dynamic_pc = set() if branch_at is None or region < branch_at + 2 else {branch_at, branch_at + 1}
    return region, checks, snapshots, dynamic_pc, stamps


def materialize(snapshot, executed):
    """Scoreboard stores after `executed` region pairs (cycle = entry + executed).

    Slots whose exact value is still in the future are written. When fewer than three
    pairs ran, every slot written in the region is written: its old content may be a
    pre-entry value that has not elapsed yet.
    """
    lines = []
    for slot, (j, latency) in sorted(snapshot.items()):
        if executed < SCOREBOARD_LATENCY_MAX - 1 or j + latency > executed:
            lines.append(f'{slot_expression(slot)} = entry + {j + latency}u;')
    return ' '.join(lines)


def fused_segments(pairs):
    """Split a clean block into fused segments and the exact pairs between them.

    Each segment is a fused region planned from its own first pair; the pair that ended it
    (a certain stall, a branch without its delay slot, E/D/T, reserved) runs on the exact
    path, then planning restarts after it. A segment never starts in the delay slot of an
    exact branch.
    """
    segments = []
    s = 0
    after_branch = False
    while s < len(pairs):
        plan = fused_plan(pairs[s:]) if not after_branch else (0, [], [], set(), [])
        region = plan[0]
        if region >= 2:
            segments.append((s, plan))
            s += region
            if s >= len(pairs):
                break
        # This pair ended the previous segment (or no segment fits here): exact path.
        after_branch = pairs[s]['lo']['pipeline'] == PIPELINE_BRANCH
        s += 1
    return segments


def fused_block(key, start, names, masks, constants):
    pairs = [full_pair(constants[name]) for name in names]
    segments = fused_segments(pairs)
    clean = f'clean_{key}_{start:04x}'
    if not segments:
        return None, {'begin': start, 'pairs': len(names), 'fused_pairs': 0}
    name = f'fused_{key}_{start:04x}'
    cont = f'from_{key}_{start:04x}'
    args = 'vu, data, dataSize, gs, memory, codeSize, budgetEnd, programEnded'
    starts = {s: plan for s, plan in segments}
    targets = set()
    for s, (region, checks, *_rest) in segments:
        targets.add(s)
        targets |= {s + i for i in range(1, region) if checks[i]}
    targets.discard(0)
    targets = sorted(targets)

    def boundary(offset):
        return [f'        if (vu.m_state.pc != {start + offset * 8}u || vu.m_cycle >= budgetEnd || vu.m_stopRequested || vu.m_state.pc + 8u > codeSize) return 0;\n',
                '        if (vu.m_cycle >= vu.m_nextCommitCycle || vu1ScanAll()) vu.commitReadyPipelines();\n']

    def resume(index):
        return f'return {cont}({args}, {index}u);' if index else f'return {clean}({args});'

    # Exact clean continuation from any pair, entered by pair index; each label sits before
    # that pair's original boundary checks. Out of line so the fused body stays small.
    out = [f'    static PS2X_VU1_COLD int {cont}(VU1Interpreter &vu, uint8_t *data, uint32_t dataSize, GS &gs, PS2Memory *memory, uint32_t codeSize, uint64_t budgetEnd, bool &programEnded, uint32_t from)\n    {{\n',
           '        switch (from)\n        {\n']
    out += [f'        case {t}u: goto slow_{t};\n' for t in targets]
    out.append('        default: break;\n        }\n')
    for offset, (constant, mask) in enumerate(zip(names, masks)):
        if offset:
            if offset in targets:
                out.append(f'    slow_{offset}:\n')
            out += boundary(offset)
        out.append(f'        if (stepClean<{constant}, {mask}>({args})) return 1;\n')
    out.append('        return 0;\n    }\n')

    out.append(f'    static int {name}(VU1Interpreter &vu, uint8_t *data, uint32_t dataSize, GS &gs, PS2Memory *memory, uint32_t codeSize, uint64_t budgetEnd, bool &programEnded)\n    {{\n')
    out.append('        if (vu1ScanAll() || !g_vu1Fused)\n')
    out.append(f'            return {clean}({args});\n')
    out.append('        uint64_t entry;\n')
    fused_total = dynamic_total = stamping_total = 0
    offset = 0
    while offset < len(names):
        if offset:
            out += boundary(offset)
        if offset not in starts:
            out.append(f'        if (stepClean<{names[offset]}, {masks[offset]}>({args})) return 1;\n')
            offset += 1
            continue
        region, checks, snapshots, dynamic_pc, stamps = starts[offset]
        s = offset
        fused_total += region
        dynamic_total += sum(len(c) for c in checks)
        stamping_total += sum(stamps)
        out.append(f'        if (vu.m_cycle + {region}u > budgetEnd || vu.m_stopRequested || {start + 8 * (s + region)}u > codeSize ||\n'
                   f'            vu.m_state.branchPending || vu.m_state.haltAfterDelaySlot || vu.m_state.ebit)\n'
                   f'            {resume(s)}\n')
        out.append('        if (g_vu1CleanTrace) ++g_vu1FusedEntries;\n')
        out.append('        entry = vu.m_cycle;\n')
        for i in range(region):
            if checks[i]:
                stores = materialize(snapshots[i - 1], i) if i else ''
                out.append(f'        if ({" || ".join(checks[i])}) {{ {stores} if (g_vu1CleanTrace) ++g_vu1FusedBails; {resume(s + i)} }}\n')
            branch_pc = 'true' if i in dynamic_pc else 'false'
            stamp = 'true' if stamps[i] else 'false'
            out.append(f'        fastStep<{names[s + i]}, {masks[s + i]}, {branch_pc}, {stamp}>(vu, data, dataSize, gs, memory, {start + 8 * (s + i)}u, codeSize);\n')
            out.append(f'        if (fastAdvance(vu)) {{ {materialize(snapshots[i], i + 1)} return 0; }}\n')
        out.append(f'        {materialize(snapshots[region - 1], region)}\n')
        offset = s + region
    out.append('        return 0;\n    }\n')
    return ''.join(out), {'begin': start, 'pairs': len(names), 'fused_pairs': fused_total,
                          'segments': [[s, plan[0]] for s, plan in segments],
                          'dynamic_checks': dynamic_total, 'stamping_pairs': stamping_total}


FUSED_HELPERS = """
#if defined(__clang__) || defined(__GNUC__)
#define PS2X_VU1_COLD __attribute__((noinline, cold))
#else
#define PS2X_VU1_COLD __declspec(noinline)
#endif
    template <const P &K, uint8_t Clean, bool BranchPc, bool Stamp>
    static PS2X_VU1_STEP_INLINE void fastStep(VU1Interpreter &vu, uint8_t *vuData, uint32_t dataSize,
            GS &gs, PS2Memory *memory, uint32_t pc, uint32_t codeSize)
    {
        if (g_vu1CleanTrace) ++g_vu1FusedPairs;
        vu.m_pairFlagsDirect = K.flagsDirect;
        vu.m_pairProductSum = K.productSum;
        vu.m_pairStoreDirect = K.storeDirect;
        vu.m_pairFlagsLive = K.flagsLive;
        const P &decoded = K;
#define PS2X_VU1_ISSUE_UPPER(instruction) upperClean<K, Clean>(vu, instruction)
#define PS2X_VU1_STAMP_DIRECT Stamp
#include "../ps2_vu1_step_issue.inl"
#undef PS2X_VU1_STAMP_DIRECT
#undef PS2X_VU1_ISSUE_UPPER
#include "../ps2_vu1_step_post.inl"
        // No halt or E bit inside a fused region and none pending at entry. Only a final
        // branch and its delay slot use the branch-delay update of ps2_vu1_step_body.inl.
        uint32_t nextPc = pc + 8u;
        if (nextPc >= codeSize)
            nextPc = 0u;
        vu.m_state.pc = nextPc;
        if constexpr (BranchPc)
        {
            if (vu.m_state.branchPending)
            {
                if (vu.m_state.branchDelay == 0u)
                {
                    vu.m_state.pc = vu.m_state.branchTarget & vu.microAddressMask();
                    vu.m_state.branchPending = false;
                }
                else
                {
                    --vu.m_state.branchDelay;
                }
            }
        }
    }

    // advanceOneCycle without the scan-all bisect switch (fused regions require it off).
    // Returns true when XGKICK progress requested a stop.
    static PS2X_VU1_STEP_INLINE bool fastAdvance(VU1Interpreter &vu)
    {
        ++vu.m_cycle;
        vu.m_state.cycles = vu.m_cycle;
        if (vu.m_cycle >= vu.m_nextCommitCycle)
            vu.commitReadyPipelines();
        if (vu.m_xgkick.active)
        {
            vu.progressXgkick();
            return vu.m_stopRequested;
        }
        return false;
    }
"""


def shared_region_images(tables, regions):
    """Share only whole, same-PC regions with identical decoded-pair identities.

    Pair identities include scheduling and flag metadata, not only instruction
    words. Entries outside the proved regions must retain the target's table.
    """
    aliases = {}
    for target, pairs in tables.items():
        if target in regions:
            continue
        for source, spans in regions.items():
            if source not in tables or not spans:
                raise ValueError('Unknown or empty source regions')
            if any(not (0 <= a < b <= len(tables[source]) * 8)
                   or a % 8 or b % 8 for a, b in spans):
                raise ValueError('Invalid shared region bounds')
            if len(pairs) == len(tables[source]) and all(
                    pairs[a // 8:b // 8] == tables[source][a // 8:b // 8]
                    for a, b in spans):
                aliases[target] = source
                break
    return aliases


def generate(base, upper, step, regions, block_size, fused=False, share_identical=False):
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
    entries_by_image = {}
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
                row = {'hash': key, 'begin': start, 'end': finish, 'masks': masks}
                if fused:
                    code, plan = fused_block(key, start, names, masks, constants)
                    row['fused'] = plan
                    if code:
                        chunks.append(code)
                        entries[start // 8] = f'fused_{key}_{start:04x}'
                report.append(row)
        entries_by_image[key] = entries
        chunks.append(f'    static constexpr VU1Interpreter::CompiledPairFn c_{key}[2048] = {{\n')
        for index, constant in enumerate(tables[key]):
            chunks.append(('        ' if index % 8 == 0 else ' ') + ('&' + entries[index] if index in entries else f'&step<{constant}>') + ',' + ('\n' if index % 8 == 7 else ''))
        chunks.append('    };\n')
    aliases = shared_region_images(tables, regions) if share_identical else {}
    for target, source in aliases.items():
        entries = entries_by_image[source]
        chunks.append(f'    static constexpr VU1Interpreter::CompiledPairFn c_{target}[2048] = {{\n')
        for index, constant in enumerate(tables[target]):
            chunks.append(('        ' if index % 8 == 0 else ' ') +
                          ('&' + entries[index] if index in entries else f'&step<{constant}>') +
                          ',' + ('\n' if index % 8 == 7 else ''))
        chunks.append('    };\n')
        report.extend({**row, 'hash': target, 'alias_of': source}
                      for row in list(report) if row['hash'] == source)
    helpers = arithmetic_body(upper) + scheduling_body(step) + (FUSED_HELPERS if fused else '')
    marker = '\nstruct VU1CompiledPrograms\n'
    if base.count(marker) != 1:
        raise ValueError('Unexpected generated class')
    output = base.replace(marker, '\n// VU1CleanBlockGenerator: generated from current semantics, experimental opt-in.\n'
                          'static const bool g_vu1CleanTrace = [] { const char *v = std::getenv("PS2X_VU1_TRACE_BLOCKS"); return v && *v == \'1\'; }();\n'
                          + ('// Fused clean-block regions; PS2X_VU1_FUSED=0 keeps the clean blocks alone.\n'
                             'static const bool g_vu1Fused = [] { const char *v = std::getenv("PS2X_VU1_FUSED"); return !(v && *v == \'0\'); }();\n'
                             if fused else '')
                          + marker)
    class_end = '\n};\n\nstatic const VU1Interpreter::CompiledPairFn *vu1FindCompiledProgram'
    if output.count(class_end) != 1:
        raise ValueError('Unexpected generated class end')
    output = output.replace(class_end, helpers + ''.join(chunks) + class_end)
    for key in (*regions, *aliases):
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
    parser.add_argument('--fused', action='store_true', help='also emit fused fast regions for the clean blocks')
    parser.add_argument('--share-identical', action='store_true', help='reuse whole proved regions in same-PC identical images')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve() == args.report.resolve() or args.out.exists() or args.report.exists():
        raise ValueError('Use distinct, new output and report files')
    paths = (args.base, args.upper, args.step, args.regions,
             args.upper.parent / 'ps2_vu1_upper_body.inl', args.step.parent / 'ps2_vu1_step_body.inl')
    texts = [p.read_text(encoding='utf-8') for p in paths]
    output, blocks = generate(*texts[:3], json.loads(texts[3]), args.block_size,
                              fused=args.fused, share_identical=args.share_identical)
    report = {'scope': __doc__, 'block_size': args.block_size, 'fused': args.fused, 'blocks': blocks,
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

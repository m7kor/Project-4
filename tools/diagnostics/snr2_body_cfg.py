"""Audit explicit SNR2 body boundaries; never discover or approve code automatically."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def control(word):
    op, rs, fn = word >> 26, (word >> 21) & 31, word & 63
    if op == 0 and fn in (8, 9):
        return 'register'
    if op in (2, 3):
        return 'direct'
    if op in (1, 4, 5, 6, 7, 20, 21, 22, 23) or op in (16, 17, 18) and rs == 8:
        return 'conditional'
    return None


def audit_body(data, start, end, entries=(), local_jump_targets=None):
    if start < 0 or end > len(data) or start % 4 or end % 4 or end <= start:
        raise ValueError('Invalid body bounds')
    roots = {start, *entries}
    if any(pc % 4 or not start <= pc < end for pc in roots):
        raise ValueError('Entry outside body')
    targets = local_jump_targets or {}
    pending, visited, expanded, exits, indirect, bad_delay = list(roots), set(), set(), [], [], []

    def enqueue(pc, source, kind):
        if start <= pc < end and pc % 4 == 0:
            pending.append(pc)
        else:
            exits.append({'source': source, 'target': pc, 'kind': kind})

    while pending:
        pc = pending.pop()
        if pc in expanded:
            continue
        expanded.add(pc)
        visited.add(pc)
        word = struct.unpack_from('<I', data, pc)[0]
        kind = control(word)
        if not kind:
            enqueue(pc + 4, pc, 'fallthrough')
            continue
        delay = pc + 4
        if delay >= end:
            bad_delay.append({'branch': pc, 'reason': 'missing delay slot'})
            continue
        visited.add(delay)
        if control(struct.unpack_from('<I', data, delay)[0]):
            bad_delay.append({'branch': pc, 'reason': 'control transfer in delay slot'})
        op, rs, rt, rd, fn = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31, word & 63
        if kind == 'register':
            if fn == 9 and rd:
                enqueue(pc + 8, pc, 'call_return')
            elif fn != 8 or rs != 31:
                indirect.append(pc)
        elif kind == 'direct':
            if op == 3:
                enqueue(pc + 8, pc, 'call_return')
            else:
                target = targets.get(pc, (word & 0x3ffffff) << 2)
                enqueue(target, pc, 'tail_jump')
        else:
            immediate = word & 0xffff
            if immediate & 0x8000:
                immediate -= 0x10000
            # Both outcomes are conservative, except trivially constant equality.
            if not (op in (5, 21) and rs == rt):
                enqueue(pc + 4 + immediate * 4, pc, 'conditional')
            if not (op in (4, 20) and rs == rt):
                enqueue(pc + 8, pc, 'conditional_fallthrough')
    unreachable = [pc for pc in range(start, end, 4) if pc not in visited and struct.unpack_from('<I', data, pc)[0]]
    return {'start': start, 'end': end, 'reachable_words': len(visited),
            'unreachable_nonzero_words': unreachable, 'boundary_exits': exits,
            'unresolved_indirect_jumps': indirect, 'invalid_delay_slots': bad_delay,
            'scope': 'Conservative local control-flow only. Imports, jump tables, runtime behavior and code/data semantics remain unverified.'}


def main():
    from tools.diagnostics.snr2_relocations import compact_relocations
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    data = args.module.read_bytes()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    if plan.get('schema') != 1 or plan.get('identity') != hashlib.sha256(data).hexdigest():
        parser.error('Plan does not match the original module identity')
    targets = {r['offset']: r['target_offset'] for r in compact_relocations(data) if r['type'] == 4}
    reports = [audit_body(data, b['start'], b['end'], b.get('entries', ()), targets) for b in plan['bodies']]
    if args.out.resolve() in (args.module.resolve(), args.plan.resolve()):
        parser.error('Cannot replace module or plan')
    args.out.write_text(json.dumps({'bodies': reports}, indent=2) + '\n', encoding='utf-8')
    print('Bodies audited:', len(reports), 'bodies with unreachable nonzero words:',
          sum(bool(r['unreachable_nonzero_words']) for r in reports))


if __name__ == '__main__':
    main()

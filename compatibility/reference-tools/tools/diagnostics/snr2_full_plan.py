"""Plan complete native compilation of RE4 SNR2 modules.

The earlier per-function plans (snr2_native_plan.py) translate reviewed
ranges only, which cannot keep up with a game that loads 135 distinct stage,
enemy, weapon and screen modules. This tool derives a complete plan for each
module from the module's own metadata, without executing or patching it:

  text      [0x100, end of the last `jr $ra` + its delay slot). The compiler
            places constant data, vtables and jump tables in .rodata/.data
            after .text; the region is checked to contain no 32-bit data
            relocation, so a module whose text holds data is refused.
  entries   every defined symbol inside text, the constructor/destructor,
            the module entry table at header word 8 (_prolog/_epilog), and
            every 32-bit data relocation whose target lies inside text (jump
            tables and function pointers). The generator adds the return
            points after calls itself.
  bodies    text split at entries, then merged wherever a branch or J
            crosses a split or a split would separate an instruction from its
            delay slot, so every internal control transfer stays inside one
            generated function.
  relocs    every HI16/LO16/26-bit relocation inside text; the generated code
            reads those operand bits from relocated RAM at run time.

    python -I -m tools.diagnostics.snr2_full_plan ARCHIVE OUTDIR [--only NAME ...]

OUTDIR receives, per unique module image, <id>.bin (the original bytes),
<id>.toml (the codegen plan) and a manifest.json describing every module and
every refusal. Generated sources are produced by ps2_native_module_codegen.
"""
import argparse
import hashlib
import json
import ntpath
from pathlib import Path
import re
import struct

from tools.diagnostics.snr2_inventory import read_modules
from tools.diagnostics.snr2_relocations import compact_relocations

TEXT_START = 0x100


def word(data, at):
    return struct.unpack_from('<I', data, at)[0]


def has_delay_slot(w):
    op = w >> 26
    if op in (2, 3, 4, 5, 6, 7, 20, 21, 22, 23):
        return True
    if op == 0 and (w & 63) in (8, 9):
        return True
    if op == 1 and ((w >> 16) & 31) in (0, 1, 2, 3, 16, 17, 18, 19):
        return True
    if op in (16, 17, 18) and ((w >> 21) & 31) == 8:
        return True
    return False


def branch_target(w, at):
    """Static PC-relative branch or J target (image-relative), else None."""
    op = w >> 26
    if op in (4, 5, 6, 7, 20, 21, 22, 23) or (op == 1 and ((w >> 16) & 31) in (0, 1, 2, 3, 16, 17, 18, 19)) \
            or (op in (16, 17, 18) and ((w >> 21) & 31) == 8):
        imm = w & 0xFFFF
        if imm & 0x8000:
            imm -= 0x10000
        return at + 4 + (imm << 2)
    if op == 2:  # J (not JAL): image-relative before relocation
        return (w & 0x03FFFFFF) << 2
    return None


def text_end(data, limit):
    last = 0
    for off in range(TEXT_START, limit, 4):
        if word(data, off) == 0x03E00008:
            last = off
    return last + 8 if last else 0


def plan_module(meta, data):
    header = struct.unpack('<15I', data[:60])
    reloc_at = header[1]
    end = text_end(data, min(reloc_at, len(data)))
    if end <= TEXT_START:
        raise ValueError('no code found')

    def in_text(at):
        return TEXT_START <= at < end

    relocations = compact_relocations(data) + meta['relocations']
    # Tail-call stubs (lui/addiu/j) can follow the last `jr $ra` (measured in
    # sscrn at 0x381d4..0x381f8, which the game calls). Every instruction
    # relocation lies in text, so text reaches at least past the last one and
    # its delay slot.
    last_instruction_reloc = max((r['offset'] for r in relocations if r['type'] in (4, 5, 6)
                                  and r['offset'] < reloc_at), default=0)
    if last_instruction_reloc + 4 > end:
        end = last_instruction_reloc + 4
        if has_delay_slot(word(data, end - 4)):
            end += 4
    symbols = meta['symbols']
    instruction = {}
    pointer_targets = set()
    for record in relocations:
        at, kind = record['offset'], record['type']
        if in_text(at):
            if kind not in (4, 5, 6):
                raise ValueError(f'relocation type {kind} inside text at {at:#x} (data in text)')
            previous = instruction.get(at)
            if previous is not None and previous != kind:
                raise ValueError(f'conflicting relocations at {at:#x}')
            instruction[at] = kind
            continue
        if kind == 2:
            if 'symbol_index' in record:
                symbol = symbols[record['symbol_index']]
                if not symbol['value']:
                    continue  # import: resolved by the guest loader
                target = symbol['value'] + record.get('addend', 0)
            else:
                target = word(data, at)
            if in_text(target) and target % 4 == 0:
                pointer_targets.add(target)

    entries = {TEXT_START}
    for s in symbols:
        if s['value'] and in_text(s['value']) and s['value'] % 4 == 0:
            entries.add(s['value'])
    for field in (6, 7):
        if header[field]:
            if not in_text(header[field]):
                raise ValueError(f'header entry {field} outside text')
            entries.add(header[field])
    table, count = header[8], header[9]
    if table and count and table + 4 * count <= len(data):
        for i in range(count):
            value = word(data, table + 4 * i)
            if value and in_text(value):
                entries.add(value)
    entries |= pointer_targets
    # Direct JAL/J into the module: the 26-bit field of an unrelocated image
    # holds the image-relative target. Static functions have no symbol, so
    # their call targets are entries too (measured: sscrn JAL 0xDD04 -> 0xD410).
    for at, kind in instruction.items():
        w = word(data, at)
        if kind == 4 and (w >> 26) in (2, 3):
            target = (w & 0x03FFFFFF) << 2
            if in_text(target):
                entries.add(target)
    # Code addresses built in registers (lui %hi / addiu|ori %lo, both
    # relocated) are callbacks passed at run time: pair each relocated LUI
    # with the next relocated low half that uses its register.
    for at, kind in instruction.items():
        w = word(data, at)
        if kind != 5 or (w >> 26) != 15:
            continue
        reg = (w >> 16) & 31
        high = (w & 0xFFFF) << 16
        for nxt in range(at + 4, min(at + 64, end), 4):
            if instruction.get(nxt) != 6:
                continue
            lw = word(data, nxt)
            op = lw >> 26
            if ((lw >> 21) & 31) != reg:
                continue
            low = lw & 0xFFFF
            if op in (9, 8):  # addiu/addi: signed
                target = (high + (low - 0x10000 if low & 0x8000 else low)) & 0xFFFFFFFF
            elif op == 13:  # ori
                target = high | low
            else:
                break
            if in_text(target) and target % 4 == 0:
                entries.add(target)
            break
    for record in meta['relocations']:
        if record['type'] == 4 and in_text(record['offset']):
            symbol = symbols[record['symbol_index']]
            if symbol['value'] and in_text(symbol['value']):
                entries.add(symbol['value'])

    # Initial segments split at every entry, then merged until no control
    # transfer leaves its segment and no delay slot is separated.
    starts = sorted(entries)
    segment_of = {}
    bounds = []
    for i, start in enumerate(starts):
        stop = starts[i + 1] if i + 1 < len(starts) else end
        bounds.append([start, stop])
    parent = list(range(len(bounds)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    import bisect
    seg_starts = [b[0] for b in bounds]

    def seg(at):
        return bisect.bisect_right(seg_starts, at) - 1

    merges = []
    for at in range(TEXT_START, end, 4):
        w = word(data, at)
        here = seg(at)
        target = branch_target(w, at)
        if target is not None and in_text(target):
            there = seg(target)
            if there != here:
                merges.append((min(here, there), max(here, there)))
        if has_delay_slot(w) and at + 4 < end and seg(at + 4) != here:
            merges.append((here, here + 1))
        elif has_delay_slot(w) and at + 4 >= end:
            raise ValueError(f'delay slot of {at:#x} falls outside text')
    # Contiguous union: merging i..j joins every segment between them.
    merged_to = list(range(len(bounds)))
    for lo, hi in merges:
        for k in range(lo, hi + 1):
            merged_to[k] = max(merged_to[k], hi)
    bodies = []
    i = 0
    while i < len(bounds):
        j = i
        reach = merged_to[i]
        while j < reach:
            j += 1
            reach = max(reach, merged_to[j])
        start, stop = bounds[i][0], bounds[j][1]
        body_entries = sorted(e for e in entries if start <= e < stop)
        bodies.append({'start': start, 'end': stop, 'entries': body_entries})
        i = j + 1

    return {
        'identity': meta['sha256'], 'text_start': TEXT_START, 'text_end': end,
        'instructions': (end - TEXT_START) // 4, 'bodies': bodies,
        'instruction_relocations': sorted(instruction.items()),
        'entries': len(entries), 'pointer_targets': len(pointer_targets),
    }


def identifier_for(name, sha):
    stem = re.sub(r'[^A-Za-z0-9_]', '_', ntpath.basename(name).rsplit('.', 1)[0]) or 'module'
    return f're4_{stem}_{sha[:8]}'


def write_toml(path, identifier, identity, image_name, plan):
    lines = ['schema = 1', f'identifier = {json.dumps(identifier)}', f'identity = {json.dumps(identity)}',
             f'image = {json.dumps(image_name)}']
    for body in plan['bodies']:
        lines += ['', '[[bodies]]', f'start = {body["start"]}', f'end = {body["end"]}',
                  'entries = [' + ', '.join(str(e) for e in body['entries']) + ']']
    if plan['instruction_relocations']:
        for at, kind in plan['instruction_relocations']:
            lines += ['', '[[instruction_relocations]]', f'offset = {at}', f'type = {kind}']
    else:
        lines.insert(4, 'instruction_relocations = []')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('archive', type=Path)
    parser.add_argument('outdir', type=Path)
    parser.add_argument('--only', nargs='*', help='module base names (e.g. st1_0 em10)')
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    manifest = {'archive': str(args.archive), 'modules': [], 'refused': []}
    seen = set()
    for meta, data in read_modules(args.archive):
        sha = meta['sha256']
        if sha in seen:
            continue
        seen.add(sha)
        base = ntpath.basename(meta['original_image_name']).rsplit('.', 1)[0]
        if args.only and base not in args.only:
            continue
        identifier = identifier_for(meta['original_image_name'], sha)
        try:
            plan = plan_module(meta, data)
        except ValueError as error:
            manifest['refused'].append({'name': meta['original_image_name'], 'identity': sha,
                                        'afs_index': meta['afs_index'], 'reason': str(error)})
            continue
        image = args.outdir / f'{identifier}.bin'
        if not image.exists() or hashlib.sha256(image.read_bytes()).hexdigest() != sha:
            image.write_bytes(data)
        write_toml(args.outdir / f'{identifier}.toml', identifier, sha, image.name, plan)
        manifest['modules'].append({
            'identifier': identifier, 'name': meta['original_image_name'], 'identity': sha,
            'afs_index': meta['afs_index'], 'bytes': len(data),
            'header': list(struct.unpack('<15I', data[:60])),
            'text_end': plan['text_end'], 'instructions': plan['instructions'],
            'bodies': len(plan['bodies']), 'entries': plan['entries'],
            'pointer_targets': plan['pointer_targets'],
            'instruction_relocations': len(plan['instruction_relocations'])})
    (args.outdir / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    total = sum(m['instructions'] for m in manifest['modules'])
    print(f"{len(manifest['modules'])} modules planned ({total} instructions), {len(manifest['refused'])} refused")
    for refused in manifest['refused'][:20]:
        print('  refused', refused['name'], refused['reason'])


if __name__ == '__main__':
    main()

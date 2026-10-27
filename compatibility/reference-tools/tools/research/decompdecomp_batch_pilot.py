"""Bounded automatic m2c -> native PS2 GCC -> unchanged decompdecomp judge."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import sys
from dataclasses import replace
from io import BytesIO

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'research/decomp-wtf-evaluation'
os.environ['DECOMPNET_TOOLCHAINS'] = str(BASE / 'toolchains')
from decompnet import seeds
from decompnet.rom.split import parse_function
from decompnet.rom.match import target_from_split, canonical_target, link, diff
from decompnet.rom.symbols import SymbolTable, Symbol
from elftools.elf.elffile import ELFFile

TYPES = '''typedef signed char s8; typedef unsigned char u8;
typedef signed short s16; typedef unsigned short u16;
typedef signed int s32; typedef unsigned int u32;
typedef signed long s64; typedef unsigned long u64;
typedef signed long long s128; typedef unsigned long long u128;
typedef float f32; typedef double f64;
typedef char verify_s32_width[(sizeof(s32) == 4) ? 1 : -1];
typedef char verify_s64_width[(sizeof(s64) == 8) ? 1 : -1];
typedef char verify_s128_width[(sizeof(s128) == 16) ? 1 : -1];
typedef char verify_pointer_width[(sizeof(void *) == 4) ? 1 : -1];
#define NULL ((void *)0)
'''


def export_reference(out):
    out = out.resolve()
    if not out.is_relative_to((BASE / 'batch').resolve()):
        raise ValueError('Reference must remain inside the local batch directory')
    report = json.loads((out / 'report.json').read_text())
    program = (ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34').read_bytes()
    assert hashlib.sha256(program).hexdigest() == report['elf_sha256']
    elf = ELFFile(BytesIO(program))
    segments = [(int(s['p_vaddr']), int(s['p_filesz']), int(s['p_offset']))
                for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    def read(addr, size):
        for start, length, offset in segments:
            if start <= addr and addr + size <= start + length:
                at = offset + addr - start
                return program[at:at + size]
        return None
    entries = []
    for item in report['functions']:
        if item['status'] != 'matched':
            continue
        name = item['name']
        flag = next(a['flags'][0] for a in item['attempts'] if a.get('exact'))
        folder = out / name
        src, obj = folder / 'candidate.c', folder / (flag[1:] + '.o')
        asm = BASE / 'runs/20261017T045959/asm/nonmatchings/cod' / (name + '.s')
        fn = parse_function(asm, 'cod', False)
        symbols = SymbolTable([Symbol(name, fn.vram, fn.size, 'func')])
        target = target_from_split(fn, symbols.resolve, False, 0x3d1df0)
        assert read(target.vram, len(target.code)) == target.code
        positive = link(obj.read_bytes(), name, target, symbols, read)
        assert positive.exact and not positive.problems
        # Keep the original target immutable; the extra test checks that changing
        # one non-relocation instruction byte cannot be silently accepted.
        relocation_offsets = {off + i for off, _, _ in target.relocs for i in range(4)}
        at = next((i for i in range(len(target.code)) if i not in relocation_offsets), None)
        if at is None:
            raise RuntimeError('No non-relocation byte for negative control')
        changed = bytearray(target.code)
        changed[at] ^= 1
        negative = link(obj.read_bytes(), name, replace(target, code=bytes(changed)), symbols, read)
        assert not negative.exact
        entry = {'name': name, 'address': item['address'], 'size': item['size'],
            'source': str(src.relative_to(out)), 'object': str(obj.relative_to(out)),
            'source_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
            'object_sha256': hashlib.sha256(obj.read_bytes()).hexdigest(),
            'target_sha256': hashlib.sha256(target.code).hexdigest(),
            'flags': [flag, '-G0'], 'exact_reverified': True,
            'mutated_target_rejected': True, 'relocation_count': len(target.relocs),
            'origin': 'assisted' if item.get('context_sha256') or item.get('candidate_repairs') else 'automatic',
            'candidate_repairs': item.get('candidate_repairs', [])}
        if item.get('context_sha256'):
            context_path = folder / 'context.c'
            assert hashlib.sha256(context_path.read_bytes()).hexdigest() == item['context_sha256']
            entry.update(context=str(context_path.relative_to(out)), context_sha256=item['context_sha256'])
        entries.append(entry)
    manifest = {'elf_sha256': report['elf_sha256'], 'fork_commit': report['fork_commit'],
                'compiler': report['compiler'], 'm2c': json.loads(
                    (BASE / 'toolchains/m2c/.decompnet-toolchain.json').read_text()),
                'matched_bytes': sum(e['size'] for e in entries), 'entries': entries,
                'scope': 'Local analysis references. Not native host replacements. No runtime integration.'}
    (out / 'matched-reference.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'REFERENCE {len(entries)} functions, {manifest["matched_bytes"]} bytes; all controls passed', flush=True)


def index_references():
    entries = {}
    elf_hash = None
    for manifest_path in sorted(BASE.glob('batch/*/matched-reference.json')):
        manifest = json.loads(manifest_path.read_text())
        if elf_hash is None:
            elf_hash = manifest['elf_sha256']
        assert manifest['elf_sha256'] == elf_hash
        for entry in manifest['entries']:
            old = entries.get(entry['name'])
            assert old is None or old['target_sha256'] == entry['target_sha256']
            item = dict(entry)
            for field in ('source', 'object'):
                path = manifest_path.parent / entry[field]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == entry[field + '_sha256']
                item[field] = str(path.resolve())
            if entry.get('context'):
                path = manifest_path.parent / entry['context']
                assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['context_sha256']
                item['context'] = str(path.resolve())
            assert entry['exact_reverified'] and entry['mutated_target_rejected']
            item['evidence'] = str(manifest_path.resolve())
            entries[entry['name']] = item
    index = {'elf_sha256': elf_hash, 'unique_functions': len(entries),
             'matched_bytes': sum(e['size'] for e in entries.values()),
             'scope': 'Verified analysis references, not host-native replacements or game completion.',
             'entries': sorted(entries.values(), key=lambda e: int(e['address'], 16))}
    (BASE / 'analysis-reference.json').write_text(json.dumps(index, indent=2), encoding='utf-8')
    print(f'INDEX {len(entries)} unique functions, {index["matched_bytes"]} bytes', flush=True)


def main():
    out = BASE / 'batch' / time.strftime('%Y%m%dT%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    elf_path = ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34'
    original = elf_path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    assert digest == '465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'
    elf = ELFFile(BytesIO(original))
    loads = [(int(s['p_vaddr']), int(s['p_filesz']), int(s['p_offset']))
             for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    def read(addr, size):
        for start, length, offset in loads:
            if start <= addr and addr + size <= start + length:
                at = offset + addr - start
                return original[at:at + size]
        return None
    rows = list(csv.DictReader((ROOT / 'analysis/functions.csv').open(encoding='utf-8-sig')))
    asm_dir = BASE / 'runs/20261017T045959/asm/nonmatchings/cod'
    selected = []
    # Six evenly spaced addresses in each size bin; include two prior manual
    # successes separately, so their automatic outcome is visible too.
    for low, high in ((12, 32), (36, 64), (68, 128), (132, 384)):
        pool = [r for r in rows if low <= int(r['Size']) <= high]
        for index in sorted({round(i * (len(pool) - 1) / 5) for i in range(6)}):
            row = pool[index]
            selected.append((row, f'{low}-{high}'))
    near = len(sys.argv) == 3 and sys.argv[1] == '--near'
    if near:
        center = next(i for i, row in enumerate(rows) if int(row['Start'], 16) == int(sys.argv[2], 0))
        selected = [(row, 'adjacent-to-' + sys.argv[2])
                    for row in rows[max(0, center - 3):center + 4]]
    for addr in ('0x00105910', '0x00109430'):
        row = next(r for r in rows if r['Start'] == addr)
        if row not in [r for r, _ in selected]:
            selected.append((row, 'prior-manual-match'))
    compiler = BASE / 'native-ee-gcc-2.95.3/bin/ee-gcc.exe'
    prefix = BASE / 'native-ee-gcc-2.95.3/lib/gcc-lib/ee/2.95.3'
    m2c = BASE / 'toolchains/m2c/venv/Scripts/python.exe'
    report = {'elf_sha256': digest, 'sampling': ('seven adjacent functions around ' + sys.argv[2] if near else
              'six evenly spaced addresses per size bin') + ' plus prior manual matches',
              'compiler': json.loads((BASE / 'native-ee-gcc-2.95.3/provenance.json').read_text()),
              'fork_commit': subprocess.check_output(['git', '-C', str(BASE / 'decompdecomp'),
                                                      'rev-parse', 'HEAD'], text=True).strip(), 'functions': []}
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    for row, group in selected:
        name = 'func_' + row['Start'][2:]
        folder = out / name
        folder.mkdir()
        item = {'name': name, 'address': row['Start'], 'size': int(row['Size']), 'group': group, 'attempts': []}
        report['functions'].append(item)
        if item['size'] > 2048:
            item['status'] = 'over_size_budget'
            save()
            continue
        asm = asm_dir / (name + '.s')
        if not asm.exists():
            item['status'] = 'missing_assembly'
            save()
            continue
        fn = parse_function(asm, 'cod', False)
        if not fn or fn.size != int(row['Size']):
            item['status'] = 'boundary_disagrees'
            save()
            continue
        symbols = SymbolTable([Symbol(name, fn.vram, fn.size, 'func')])
        target = target_from_split(fn, symbols.resolve, False, 0x3d1df0)
        assert read(target.vram, len(target.code)) == target.code
        item['target_verified_against_elf'] = True
        proc = subprocess.run([str(m2c), '-c', 'from m2c.main import main; import sys; sys.exit(main())',
            '--valid-syntax', '-t', 'mipsee-gcc-c', '-f', name, str(asm)], capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=30)
        (folder / 'm2c.log').write_text(proc.stderr, encoding='utf-8')
        (folder / 'draft.c').write_text(proc.stdout, encoding='utf-8')
        item['m2c_exit'] = proc.returncode
        if proc.returncode or not proc.stdout.strip():
            item['status'] = 'draft_failed'
        elif 'M2C_ERROR' in proc.stdout:
            item['status'] = 'unsupported_instructions'
        else:
            src = folder / 'candidate.c'
            src.write_text(TYPES + seeds.M2C_MACROS + '\n' + proc.stdout, encoding='utf-8')
            item['status'] = 'compile_failed'
            for opt in ('-O2', '-O1'):
                obj = folder / (opt[1:] + '.o')
                res = subprocess.run([str(compiler), '-c', '-B', prefix.as_posix() + '/', opt, '-G0',
                    src.as_posix(), '-o', obj.as_posix()], capture_output=True, text=True, timeout=30)
                (folder / (opt[1:] + '.log')).write_text(res.stdout + res.stderr, encoding='utf-8')
                attempt = {'flags': [opt, '-G0'], 'compile_exit': res.returncode}
                item['attempts'].append(attempt)
                if res.returncode == 0 and obj.exists():
                    verdict = link(obj.read_bytes(), name, target, symbols, read)
                    score = diff(canonical_target(target, symbols), verdict)
                    attempt.update(exact=verdict.exact, score=score.score, problems=verdict.problems)
                    (folder / (opt[1:] + '.diff.txt')).write_text('\n'.join(str(r) for r in score.rows), encoding='utf-8')
                    item['status'] = 'matched' if verdict.exact else 'not_matched'
                    if verdict.exact:
                        break
        save()
        print(name + ': ' + item['status'], flush=True)
    report['summary'] = {status: sum(f['status'] == status for f in report['functions'])
                         for status in sorted({f['status'] for f in report['functions']})}
    report['elf_unchanged'] = hashlib.sha256(elf_path.read_bytes()).hexdigest() == digest
    save()
    print(json.dumps(report['summary']), flush=True)
    print('REPORT ' + str(out / 'report.json'), flush=True)
    export_reference(out)
    index_references()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--export':
        export_reference(Path(sys.argv[2]))
        index_references()
    elif len(sys.argv) == 2 and sys.argv[1] == '--index':
        index_references()
    else:
        main()

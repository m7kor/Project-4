"""Bounded compiler flag survey; report regressions instead of switching global settings."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from io import BytesIO
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'research/decomp-wtf-evaluation'
os.environ['DECOMPNET_TOOLCHAINS'] = str(BASE / 'toolchains')
from decompnet.rom.split import parse_function
from decompnet.rom.match import target_from_split, canonical_target, link, diff
from decompnet.rom.symbols import SymbolTable, Symbol
from elftools.elf.elffile import ELFFile


def main():
    batch = BASE / 'batch/20261017T051012'
    prior = json.loads((batch / 'report.json').read_text())
    out = BASE / 'flag-survey' / time.strftime('%Y%m%dT%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    program = ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34'
    original = program.read_bytes()
    assert hashlib.sha256(original).hexdigest() == prior['elf_sha256']
    elf = ELFFile(BytesIO(original))
    segments = [(int(s['p_vaddr']), int(s['p_filesz']), int(s['p_offset']))
                for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    def read(addr, size):
        for start, length, offset in segments:
            if start <= addr and addr + size <= start + length:
                at = offset + addr - start
                return original[at:at + size]
        return None
    compiler = BASE / 'native-ee-gcc-2.95.3/bin/ee-gcc.exe'
    prefix = BASE / 'native-ee-gcc-2.95.3/lib/gcc-lib/ee/2.95.3'
    options = ['-fno-schedule-insns', '-fno-schedule-insns2', '-fno-strength-reduce',
               '-fno-expensive-optimizations', '-fno-cse-follow-jumps', '-fno-regmove']
    report = {'elf_sha256': prior['elf_sha256'], 'fork_commit': prior['fork_commit'],
              'compiler': prior['compiler'], 'options': options, 'attempts': []}
    library = json.loads((batch / 'matched-reference.json').read_text())
    new = {}
    for item in prior['functions']:
        if item['status'] not in ('matched', 'not_matched'):
            continue
        name = item['name']
        folder = out / name
        folder.mkdir()
        src = batch / name / 'candidate.c'
        asm = BASE / 'runs/20261017T045959/asm/nonmatchings/cod' / (name + '.s')
        fn = parse_function(asm, 'cod', False)
        symbols = SymbolTable([Symbol(name, fn.vram, fn.size, 'func')])
        target = target_from_split(fn, symbols.resolve, False, 0x3d1df0)
        assert read(target.vram, len(target.code)) == target.code
        canonical = canonical_target(target, symbols)
        for k, option in enumerate(options):
            obj = folder / f'{k}.o'
            flags = ['-O2', '-G0', option]
            proc = subprocess.run([str(compiler), '-c', '-B', prefix.as_posix() + '/', *flags,
                src.as_posix(), '-o', obj.as_posix()], capture_output=True, text=True, timeout=30)
            (folder / f'{k}.log').write_text(proc.stdout + proc.stderr, encoding='utf-8')
            row = {'name': name, 'previous_status': item['status'], 'flags': flags,
                   'compile_exit': proc.returncode, 'exact': False}
            if proc.returncode == 0 and obj.exists():
                verdict = link(obj.read_bytes(), name, target, symbols, read)
                score = diff(canonical, verdict)
                row.update(exact=verdict.exact, score=score.score, problems=verdict.problems)
                (folder / f'{k}.diff.txt').write_text('\n'.join(str(r) for r in score.rows), encoding='utf-8')
                if verdict.exact and item['status'] != 'matched' and name not in new:
                    excluded = {off + i for off, _, _ in target.relocs for i in range(4)}
                    at = next(i for i in range(len(target.code)) if i not in excluded)
                    changed = bytearray(target.code)
                    changed[at] ^= 1
                    negative = link(obj.read_bytes(), name, replace(target, code=bytes(changed)), symbols, read)
                    assert not negative.exact
                    new[name] = {'name': name, 'address': item['address'], 'size': item['size'],
                        'flags': flags, 'source': str(src), 'object': str(obj),
                        'source_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
                        'object_sha256': hashlib.sha256(obj.read_bytes()).hexdigest(),
                        'target_sha256': hashlib.sha256(target.code).hexdigest(),
                        'exact_reverified': True, 'mutated_target_rejected': True}
            report['attempts'].append(row)
        print(name + ': ' + ('NEW MATCH' if name in new else 'surveyed'), flush=True)
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    report['summary'] = {option: {
        'new_matches': sum(a['exact'] and a['previous_status'] != 'matched' and option in a['flags'] for a in report['attempts']),
        'preserved_previous': sum(a['exact'] and a['previous_status'] == 'matched' and option in a['flags'] for a in report['attempts']),
        'lost_previous': sum(not a['exact'] and a['previous_status'] == 'matched' and option in a['flags'] for a in report['attempts'])}
        for option in options}
    report['new_unique_matches'] = list(new.values())
    report['total_unique_with_previous'] = len(library['entries']) + len(new)
    report['elf_unchanged'] = hashlib.sha256(program.read_bytes()).hexdigest() == prior['elf_sha256']
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']), flush=True)
    print('NEW UNIQUE ' + str(len(new)), flush=True)
    print('REPORT ' + str(out / 'report.json'), flush=True)


if __name__ == '__main__':
    main()

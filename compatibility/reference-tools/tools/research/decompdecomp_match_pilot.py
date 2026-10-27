"""Compile isolated C candidates with pinned native PS2 GCC and use the fork's judge."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from io import BytesIO

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'research/decomp-wtf-evaluation'
os.environ['DECOMPNET_TOOLCHAINS'] = str(BASE / 'toolchains')
from decompnet.rom.split import parse_function
from decompnet.rom.match import target_from_split, canonical_target, link, diff
from decompnet.rom.symbols import SymbolTable, Symbol
from elftools.elf.elffile import ELFFile


def main():
    out = BASE / 'matching' / time.strftime('%Y%m%dT%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    program = ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34'
    original = program.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    assert digest == '465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'
    elf = ELFFile(BytesIO(original))
    segments = [(int(s['p_vaddr']), int(s['p_filesz']), int(s['p_offset']))
                for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    def read(addr, length):
        for start, size, offset in segments:
            if start <= addr and addr + length <= start + size:
                at = offset + addr - start
                return original[at:at + length]
        return None
    fn = parse_function(BASE / 'runs/20261017T045959/samples/func_00100748.s', 'cod', False)
    symbols = SymbolTable([Symbol(fn.name, fn.vram, fn.size, 'func')])
    target = target_from_split(fn, symbols.resolve, False, 0x3d1df0)
    assert read(target.vram, len(target.code)) == target.code
    source = (BASE / 'match-control.c').read_text()
    header = source[:source.index('void func_')]
    cases = [('original', source),
        ('if_zero_first', header + '''void func_00100748(State *p, s32 n) {
            if (n == 0) { p->flags |= 8; }
            else if (n == 1) { p->flags = (p->flags & ~8) | 16; }
        }'''),
        ('if_one_first', header + '''void func_00100748(State *p, s32 n) {
            if (n == 1) { p->flags = (p->flags & ~8) | 16; }
            else if (n == 0) { p->flags |= 8; }
        }'''),
        ('early_return', header + '''void func_00100748(State *p, s32 n) {
            if (n == 0) { p->flags |= 8; return; }
            if (n != 1) return;
            p->flags = (p->flags & ~8) | 16;
        }''')]
    report = {'compilers': ['ee-gcc-2.95.2', 'ee-gcc-2.95.3'], 'elf_sha256': digest,
              'target_bytes_verified_against_original_elf': True, 'attempts': []}
    report['compiler_provenance'] = [json.loads((BASE / f'native-ee-gcc-{v}/provenance.json').read_text())
                                     for v in ('2.95.2', '2.95.3')]
    report['fork_commit'] = subprocess.check_output(
        ['git', '-C', str(BASE / 'decompdecomp'), 'rev-parse', 'HEAD'], text=True).strip()
    for version in ('2.95.2', '2.95.3'):
      compiler = BASE / f'native-ee-gcc-{version}/bin/ee-gcc.exe'
      prefix = BASE / f'native-ee-gcc-{version}/lib/gcc-lib/ee/{version}'
      for variant, code in cases:
        for opt in ('-O2', '-O1', '-O3'):
            stem = version + '_' + variant + opt.replace('-', '_')
            src, obj = out / (stem + '.c'), out / (stem + '.o')
            src.write_text(code, encoding='utf-8')
            cmd = [str(compiler), '-c', '-B', prefix.as_posix() + '/', opt, '-G0',
                   src.as_posix(), '-o', obj.as_posix()]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            (out / (stem + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
            row = {'compiler': version, 'case': variant, 'flags': [opt, '-G0'], 'compile_exit': result.returncode}
            if result.returncode == 0 and obj.exists():
                verdict = link(obj.read_bytes(), fn.name, target, symbols, read)
                score = diff(canonical_target(target, symbols), verdict)
                row.update(exact=verdict.exact, score=score.score, max_score=score.max_score,
                           problems=verdict.problems)
                (out / (stem + '.diff.txt')).write_text('\n'.join(str(r) for r in score.rows), encoding='utf-8')
            report['attempts'].append(row)
            (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    # Small, non-empty real functions establish whether the end-to-end judge works.
    smoke = [
        ('func_001058D0', header + 's32 func_001058D0(State *p) { return (p->flags & 0x20) != 0; }'),
        ('func_00105910', '''typedef struct { char pad[0x250]; int value; } Inner;
            typedef struct { char pad[0x870]; Inner *inner; } Outer;
            void func_00105910(Outer *p, int value) { p->inner->value = value; }'''),
        ('func_00109430', '''typedef struct { char pad[4]; unsigned char a, b; char tail[26]; int value; } S;
            void func_00109430(S *p, int value, unsigned char a) { p->value = value; p->a = a; p->b = 0; }'''),
        ('func_001211D0', '''extern int D_003CE178;
            int func_001211D0(int value) { D_003CE178 = value; return 1; }'''),
        ('func_00105910', '''typedef struct { char pad[0x254]; int value; } Inner;
            typedef struct { char pad[0x870]; Inner *inner; } Outer;
            void func_00105910(Outer *p, int value) { p->inner->value = value; }'''),
    ]
    report['small_functions'] = []
    for k, (name, code) in enumerate(smoke):
        asm = BASE / 'runs/20261017T045959/asm/nonmatchings/cod' / (name + '.s')
        small_fn = parse_function(asm, 'cod', False)
        small_symbols = SymbolTable([Symbol(name, small_fn.vram, small_fn.size, 'func')])
        small_target = target_from_split(small_fn, small_symbols.resolve, False, 0x3d1df0)
        assert read(small_target.vram, len(small_target.code)) == small_target.code
        src, obj = out / f'small_{k}.c', out / f'small_{k}.o'
        src.write_text(code, encoding='utf-8')
        res = subprocess.run([str(compiler), '-c', '-B', prefix.as_posix() + '/', '-O2', '-G0',
                              src.as_posix(), '-o', obj.as_posix()], capture_output=True, text=True, timeout=30)
        (out / f'small_{k}.log').write_text(res.stdout + res.stderr, encoding='utf-8')
        row = {'name': name, 'negative_control': k == 4, 'compile_exit': res.returncode}
        if res.returncode == 0:
            verdict = link(obj.read_bytes(), name, small_target, small_symbols, read)
            score = diff(canonical_target(small_target, small_symbols), verdict)
            row.update(exact=verdict.exact, score=score.score, problems=verdict.problems)
            (out / f'small_{k}.diff.txt').write_text('\n'.join(str(r) for r in score.rows), encoding='utf-8')
        report['small_functions'].append(row)
        print(json.dumps(row), flush=True)
    good = [r for r in report['small_functions'] if not r['negative_control'] and r.get('exact')]
    bad = [r for r in report['small_functions'] if r['negative_control']]
    report['matched_functions'] = len(good)
    report['negative_control_rejected'] = bool(bad) and all(r.get('exact') is False for r in bad)
    report['elf_unchanged'] = hashlib.sha256(program.read_bytes()).hexdigest() == digest
    assert report['matched_functions'] >= 2 and report['negative_control_rejected']
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('REPORT ' + str(out / 'report.json'), flush=True)


if __name__ == '__main__':
    main()

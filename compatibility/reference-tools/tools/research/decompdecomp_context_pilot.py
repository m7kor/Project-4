"""Test assembly-supported prototypes, retaining m2c output and exact byte judging."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import sys

from decompdecomp_batch_pilot import BASE, ROOT, TYPES, export_reference, index_references
sys.path.insert(0, str(ROOT))
from decompnet import seeds
from decompnet.rom.split import parse_function
from decompnet.rom.match import target_from_split, canonical_target, link, diff
from decompnet.rom.symbols import SymbolTable, Symbol
from ps2l.decompref import target_bytes


def main():
    out = BASE / 'batch' / time.strftime('%Y%m%dT%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    program = (ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34').read_bytes()
    digest = hashlib.sha256(program).hexdigest()
    assert digest == '465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'
    def read(addr, size):
        try:
            return target_bytes(program, addr, size)
        except ValueError:
            return None
    compiler = BASE / 'native-ee-gcc-2.95.3/bin/ee-gcc.exe'
    prefix = BASE / 'native-ee-gcc-2.95.3/lib/gcc-lib/ee/2.95.3'
    m2c = BASE / 'toolchains/m2c/venv/Scripts/python.exe'
    contexts = {
        'func_001D5160': '''typedef void (*Callback)(void *, void *);
extern Callback D_00321DE0[];
void func_001D5080(void *);
void func_001D5160(void *);
''',
        'func_001769E8': '''s64 *func_001768E0(u16, void *, s32);
void *func_001791C8(void *, s32);
void *func_001769E8(void *, void *, s32);
''',
    }
    report = {'elf_sha256': digest, 'sampling': 'two failed drafts; prototypes inferred from target register uses',
        'compiler': json.loads((BASE / 'native-ee-gcc-2.95.3/provenance.json').read_text()),
        'fork_commit': subprocess.check_output(['git', '-C', str(BASE / 'decompdecomp'), 'rev-parse', 'HEAD'], text=True).strip(),
        'functions': []}
    for name, declarations in contexts.items():
        folder = out / name
        folder.mkdir()
        context = folder / 'context.c'
        # m2c models long long as 64-bit; native EE-GCC uses long for s64.
        # Only declarations below this prefix are reused in the compiler input.
        context.write_text('typedef int s32; typedef unsigned short u16; typedef long long s64;\n' + declarations)
        asm = BASE / 'runs/20261017T045959/asm/nonmatchings/cod' / (name + '.s')
        fn = parse_function(asm, 'cod', False)
        symbols = SymbolTable([Symbol(name, fn.vram, fn.size, 'func')])
        target = target_from_split(fn, symbols.resolve, False, 0x3d1df0)
        assert read(target.vram, len(target.code)) == target.code
        item = {'name': name, 'address': f'0x{fn.vram:08X}', 'size': fn.size, 'attempts': [],
                'target_verified_against_elf': True, 'status': 'draft_failed', 'context_sha256': hashlib.sha256(context.read_bytes()).hexdigest()}
        proc = subprocess.run([str(m2c), '-c', 'from m2c.main import main; import sys; sys.exit(main())',
            '--valid-syntax', '--no-cache', '--context', str(context), '-t', 'mipsee-gcc-c', '-f', name,
            str(asm)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        (folder / 'm2c.log').write_text(proc.stderr, encoding='utf-8')
        (folder / 'draft.c').write_text(proc.stdout, encoding='utf-8')
        item['m2c_exit'] = proc.returncode
        if proc.returncode == 0 and proc.stdout.strip() and 'M2C_ERROR' not in proc.stdout:
            src = folder / 'candidate.c'
            candidate = proc.stdout
            repairs = []
            if name == 'func_001D5160':
                old, new = '*temp_5(arg0, temp_5);', '(*temp_5)(arg0, temp_5);'
                assert candidate.count(old) == 1
                candidate = candidate.replace(old, new)
                repairs.append('Parenthesize the indirect call dereference, matching lw + jalr at 0x001D51A0/4')
            if name == 'func_001769E8':
                old, new = '(s32) *arg1;', 'M2C_FIELD(arg1, s32 *, 0);'
                assert candidate.count(old) == 1
                candidate = candidate.replace(old, new)
                repairs.append('Use an explicit 32-bit load through the byte-addressed pointer, matching lw at 0x00176A44')
            item['candidate_repairs'] = repairs
            src.write_text(TYPES + seeds.M2C_MACROS + '\n' + declarations + candidate, encoding='utf-8')
            item['status'] = 'compile_failed'
            for opt in ('-O2', '-O1'):
                obj = folder / (opt[1:] + '.o')
                build = subprocess.run([str(compiler), '-c', '-B', prefix.as_posix() + '/', opt, '-G0',
                    src.as_posix(), '-o', obj.as_posix()], capture_output=True, text=True, timeout=30)
                (folder / (opt[1:] + '.log')).write_text(build.stdout + build.stderr, encoding='utf-8')
                attempt = {'flags': [opt, '-G0'], 'compile_exit': build.returncode}
                item['attempts'].append(attempt)
                if build.returncode == 0:
                    verdict = link(obj.read_bytes(), name, target, symbols, read)
                    score = diff(canonical_target(target, symbols), verdict)
                    attempt.update(exact=verdict.exact, score=score.score, problems=verdict.problems)
                    (folder / (opt[1:] + '.diff.txt')).write_text('\n'.join(str(r) for r in score.rows), encoding='utf-8')
                    item['status'] = 'matched' if verdict.exact else 'not_matched'
                    if verdict.exact:
                        break
        report['functions'].append(item)
        print(json.dumps(item), flush=True)
    report['summary'] = {s: sum(f['status'] == s for f in report['functions'])
                         for s in sorted({f['status'] for f in report['functions']})}
    report['elf_unchanged'] = hashlib.sha256((ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34').read_bytes()).hexdigest() == digest
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    export_reference(out)
    index_references()
    print('REPORT ' + str(out / 'report.json'))


if __name__ == '__main__':
    main()

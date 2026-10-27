"""Local, isolated RE4 analysis pilot; never edits runtime or generated runners."""
from pathlib import Path
import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
import sys
import tempfile
import struct
import re
import yaml
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'research/decomp-wtf-evaluation'
os.environ['DECOMPNET_TOOLCHAINS'] = str(BASE / 'toolchains')
os.environ['DECOMP_HOME'] = str(BASE / 'pilot-home')
from decompnet.rom import ps2
from decompnet.rom.split import split_rom, parse_function, parse_data, segments_from_config, _complete_delay_slot
from decompnet.rom.match import target_from_split
from decompnet import seeds, classes
from elftools.elf.elffile import ELFFile
from io import BytesIO


def main():
    reuse = len(sys.argv) == 3 and sys.argv[1] == '--reuse'
    run = Path(sys.argv[2]).resolve() if reuse else BASE / 'runs' / time.strftime('%Y%m%dT%H%M%S')
    if not run.is_relative_to((BASE / 'runs').resolve()):
        raise RuntimeError('Run must stay inside the evaluation runs directory')
    run.mkdir(parents=True, exist_ok=reuse)
    scratch = run / 'temp'
    scratch.mkdir(exist_ok=True)
    tempfile.tempdir = str(scratch)
    elf = ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34'
    original = elf.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    expected = '465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'
    if digest != expected:
        raise RuntimeError('ELF differs from the recorded RE4 profile')
    _, identity = ps2.read_elf(original, elf.name)
    identity['symbols_heuristic'] = identity.pop('symbols')
    identity['symbols_verified'] = ELFFile(BytesIO(original)).get_section_by_name('.symtab') is not None
    report = {'elf_sha256': digest, 'identity': identity, 'compiler_style': ps2.code_style(original),
              'fork_commit': subprocess.check_output(['git', '-C', str(BASE / 'decompdecomp'),
                                                      'rev-parse', 'HEAD'], text=True).strip(),
              'byte_matching_tested': False, 'samples': []}
    report_path = run / 'report.json'
    def save():
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    if not reuse:
        shutil.copyfile(elf, run / elf.name)
    started = time.monotonic()
    try:
        if reuse:
            config = run / (elf.name + '.yaml')
            functions = [parse_function(p, p.parent.name, False) for p in
                         sorted((run / 'asm/nonmatchings').glob('*/*.s'))]
            data = [d for p in (run / 'asm/data').rglob('*.s') for d in parse_data(p)]
            cfg = yaml.safe_load(config.read_text(encoding='utf-8'))
            flat = (run / (elf.name + '.rom')).read_bytes()
            for f in functions:
                if f:
                    _complete_delay_slot(f, flat, False)
            result = SimpleNamespace(functions=[f for f in functions if f], data=data,
                                     gp=cfg['options'].get('gp_value', 0),
                                     compiler='EEGCC', segments=segments_from_config(config))
            report['reused_split'] = True
        else:
            result = split_rom(run, elf.name, log=lambda line: print(line, flush=True))
    except Exception as exc:
        report['split_error'] = str(exc)
        report['split_details'] = getattr(exc, 'details', '')
        save()
        raise
    report['split_seconds'] = time.monotonic() - started
    report['functions'] = len(result.functions)
    report['data_symbols'] = len(result.data)
    report['gp'] = hex(result.gp)
    report['split_compiler'] = result.compiler
    bounds = {int(r['Start'], 16): int(r['Size']) for r in
              csv.DictReader((ROOT / 'analysis/functions.csv').open(encoding='utf-8-sig'))}
    report['existing_map'] = {'functions': len(bounds),
        'shared_starts': sum(f.vram in bounds for f in result.functions),
        'same_start_and_size': sum(bounds.get(f.vram) == f.size for f in result.functions)}
    image = (run / (elf.name + '.rom')).read_bytes()
    def read(address, length):
        for segment in result.segments:
            if segment.contains(address, length):
                offset = segment.rom_start + address - segment.vram
                return image[offset:offset + length]
        return None
    names = {f.name: f.vram for f in result.functions} | {d.name: d.vram for d in result.data}
    def resolve(name):
        if name in names:
            return names[name]
        match = re.fullmatch(r'(?:D_|func_|L)([0-9A-Fa-f]{8})', name)
        return int(match[1], 16) if match else None
    targets = [target_from_split(f, resolve, False, result.gp) for f in result.functions]
    report['function_bytes_agree_with_image'] = all(read(t.vram, len(t.code)) == t.code for t in targets)
    recovered = classes.recover(((t.vram, t.code, t.relocs) for t in targets), read, False)
    report['candidate_classes'] = len(recovered.by_vtable)
    (run / 'class-candidates.txt').write_text('\n\n'.join(
        classes.describe(c, recovered, lambda a: f'0x{a:08X}') for c in
        sorted(recovered.by_vtable.values(), key=lambda c: c.vtable)), encoding='utf-8')
    save()
    candidates = sorted((f for f in result.functions if 64 <= f.size <= 384 and bounds.get(f.vram) == f.size),
                        key=lambda f: f.vram)
    selected = []
    for category, predicate in [
        ('branch', lambda f: any(i.mnemonic.startswith('b') for i in f.lines)),
        ('calls', lambda f: any(i.mnemonic == 'jal' for i in f.lines)),
        ('floating_point', lambda f: any('.s' in i.mnemonic for i in f.lines)),
        ('memory', lambda f: any(i.mnemonic in ('lw', 'sw') for i in f.lines)),
        ('integer', lambda f: True),
    ]:
        fn = next((f for f in candidates if f not in [x[1] for x in selected] and predicate(f)), None)
        if fn:
            selected.append((category, fn))
    sample_dir = run / 'samples'
    sample_dir.mkdir(exist_ok=True)
    for category, fn in selected:
        asm = fn.asm_path.read_text(encoding='utf-8')
        (sample_dir / (fn.name + '.s')).write_text(asm, encoding='utf-8')
        start = time.monotonic()
        # Invoke the same pinned entry point with Python: uv's Windows launcher
        # cannot canonicalize its script under the desktop sandbox.
        m2c_python = BASE / 'toolchains/m2c/venv/Scripts/python.exe'
        proc = subprocess.run([str(m2c_python), '-c',
            'from m2c.main import main; import sys; sys.exit(main())',
            '-t', seeds.M2C_TARGETS['ee-gcc-2.96'], '-f', fn.name,
            str(sample_dir / (fn.name + '.s'))], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=30)
        (sample_dir / (fn.name + '.m2c.log')).write_text(proc.stderr, encoding='utf-8')
        draft = proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None
        sample = {'category': category, 'name': fn.name, 'address': hex(fn.vram), 'size': fn.size,
                  'draft_generated': draft is not None, 'seconds': time.monotonic() - start,
                  'existing_boundary_agrees': True, 'm2c_exit': proc.returncode}
        if draft:
            (sample_dir / (fn.name + '.c')).write_text(draft + '\n', encoding='utf-8')
            sample['draft_lines'] = len(draft.splitlines())
            sample['unresolved_markers'] = any(x in draft for x in ('ERROR', '?', 'M2C_ERROR'))
        report['samples'].append(sample)
        save()
        print(json.dumps(sample), flush=True)
    report['elf_unchanged'] = hashlib.sha256(elf.read_bytes()).hexdigest() == digest
    save()
    print('REPORT ' + str(report_path), flush=True)


if __name__ == '__main__':
    main()

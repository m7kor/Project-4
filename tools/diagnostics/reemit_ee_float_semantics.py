"""Re-emit generated EE bodies whose float divide/root code predates PS2 float semantics.

The code generator now emits ps2FpuDivide/ps2FpuSqrt/ps2FpuRsqrt for COP1
DIV.S/SQRT.S/RSQRT.S and ps2VuDivide/ps2VuSqrt/ps2VuRsqrt for VU0 macro
VDIV/VSQRT/VRSQRT (PS2 hardware has no infinities: divide by zero gives
+/-FLT_MAX and sets flags; VRSQRT is FS/sqrt(|FT|)). Bodies generated
earlier still contain the old expressions. This tool re-emits exactly those
bodies with ps2_ee_body_codegen from the original ELF words, keeping each
body's bounds and every existing resume entry, and refuses any change outside
the float expressions. Same safeguards as reemit_ee_fpu_roots.py: separate
output directory, source-change detection, backups of every replaced file.

    python -m tools.diagnostics.reemit_ee_float_semantics --elf ELF --generated DIR \
        --emitter ps2_ee_body_codegen.exe --out OUTDIR [--apply]
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

OLD_MARKERS = ('copysignf(INFINITY', 'FPU_SQRT_S(', '(ft != 0.0f) ? (fs / ft) : 0.0f',
               'sqrtf(std::max(0.0f, ft))', '(ft > 0.0f) ? (1.0f / sqrtf(ft)) : 0.0f')
NEW_MARKERS = ('ps2FpuDivide(', 'ps2FpuSqrt(', 'ps2FpuRsqrt(', 'ps2VuDivide(', 'ps2VuSqrt(', 'ps2VuRsqrt(')


def float_line(line):
    return any(m in line for m in OLD_MARKERS + NEW_MARKERS)


def comparable(text):
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('// Function:') or float_line(line):
            continue
        lines.append(line)
    return lines


def load_ram(elf):
    if elf[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H', elf, 18)[0] != 8:
        raise ValueError('Expected original little endian MIPS32 ELF')
    ram = bytearray(32 * 1024 * 1024)
    segments = []
    ph = struct.unpack_from('<I', elf, 28)[0]
    ents, count = struct.unpack_from('<HH', elf, 42)
    for i in range(count):
        kind, at, va, _, fs, ms, flags, _ = struct.unpack_from('<8I', elf, ph + ents * i)
        if kind != 1:
            continue
        if va + ms > len(ram) or fs > ms or at + fs > len(elf):
            raise ValueError('Invalid ELF segment')
        ram[va:va + fs] = elf[at:at + fs]
        segments.append((va, va + fs, flags))
    return ram, segments


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--generated', type=Path, required=True)
    parser.add_argument('--emitter', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    elf = args.elf.read_bytes()
    ram, segments = load_ram(elf)
    out = args.out.absolute()
    out.mkdir(parents=True, exist_ok=True)
    if out == args.generated.absolute():
        raise ValueError('Output must be separate from the generated tree')
    raw = out / 'original-elf-ram.bin'
    raw.write_bytes(ram)

    report = {'schema': 1, 'elf_sha256': hashlib.sha256(elf).hexdigest(), 'applied': False,
              'functions': [], 'skipped': []}
    prepared = []
    for source in sorted(args.generated.glob('*.cpp')):
        old_bytes = source.read_bytes()
        old = old_bytes.decode('utf-8')
        if not any(m in old for m in OLD_MARKERS):
            continue
        bounds = re.search(r'// Address: (0x[\da-fA-F]+) - (0x[\da-fA-F]+)', old)
        signature = re.search(r'void (\w+)\(uint8_t\* rdram, R5900Context\* ctx, PS2Runtime \*runtime\)', old)
        if not bounds or not signature:
            report['skipped'].append({'source': source.name, 'reason': 'not a single generated body'})
            continue
        start, end = (int(v, 16) for v in bounds.groups())
        if start % 4 or end % 4 or end <= start or \
                sum(a <= start and end <= b and flags & 1 for a, b, flags in segments) != 1:
            report['skipped'].append({'source': source.name, 'reason': 'body not in one executable segment'})
            continue
        for address, value in re.findall(r'// (0x[\da-fA-F]+): (0x[\da-fA-F]+)', old):
            at, w = int(address, 16), int(value, 16)
            if start <= at < end and struct.unpack_from('<I', ram, at)[0] != w:
                raise ValueError(f'{source.name}: source word at {at:#x} differs from the ELF')
        entries = sorted({int(v, 16) for v in re.findall(r'case (0x[\da-fA-F]+)u: goto label_', old)})
        plan = out / (source.stem + '.toml')
        new = out / source.name
        plan.write_text(f'schema = 1\nimage = {json.dumps(raw.as_posix())}\nstart = {start}\nend = {end}\n'
                        f'name = {json.dumps(signature[1])}\nentries = {json.dumps(entries)}\n')
        result = subprocess.run([str(args.emitter.absolute()), str(plan), str(new)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'{source.name}: {result.stderr}')
        emitted = new.read_text(encoding='utf-8')
        if comparable(old) != comparable(emitted):
            raise ValueError(f'{source.name}: re-emission changed code outside float expressions')
        if any(m in emitted for m in OLD_MARKERS):
            raise ValueError(f'{source.name}: emitter still produced old float expressions')
        for entry in entries:
            if f'case 0x{entry:x}u:' not in emitted:
                raise ValueError(f'{source.name}: lost resume entry {entry:#x}')
        report['functions'].append({'source': source.name, 'start': start, 'end': end, 'entries': len(entries),
                                    'before_sha256': hashlib.sha256(old_bytes).hexdigest(),
                                    'after_sha256': hashlib.sha256(new.read_bytes()).hexdigest()})
        prepared.append((source, new, hashlib.sha256(old_bytes).hexdigest()))

    if args.apply:
        for source, _, sha in prepared:
            if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
                raise ValueError('Source changed during preparation')
        backup = out / 'before'
        backup.mkdir(exist_ok=True)
        for source, new, _ in prepared:
            (backup / source.name).write_bytes(source.read_bytes())
            source.write_bytes(new.read_bytes())
        report['applied'] = True
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Re-emitted {len(prepared)} bodies (skipped {len(report['skipped'])}); applied={report['applied']}")
    for item in report['skipped'][:10]:
        print('  skipped', item)


if __name__ == '__main__':
    main()

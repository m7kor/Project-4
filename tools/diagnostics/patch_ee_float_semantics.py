"""Rewrite old float divide/root expressions in generated EE bodies in place.

reemit_ee_float_semantics.py re-emits whole bodies, which drops jump-table
dispatch blocks the original emission had. This tool instead replaces only the
single generated statement of each COP1 DIV.S/SQRT.S and VU0 VDIV/VSQRT/VRSQRT,
after decoding the instruction word in the preceding address comment, checking
that word against the ELF and checking the old statement's registers against
the decoded fields. Any statement that does not verify aborts the run.

    python -m tools.diagnostics.patch_ee_float_semantics --elf ELF --generated DIR --out OUTDIR [--apply]
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from tools.diagnostics.reemit_ee_float_semantics import load_ram

WORD = re.compile(r'^\s*// (0x[\da-f]+): (0x[\da-f]+)\b', re.I)
SHUF = r'_mm_cvtss_f32\(_mm_shuffle_ps\(ctx->vu0_vf\[(\d+)\], ctx->vu0_vf\[\1\], _MM_SHUFFLE\(0,0,0,(\d)\)\)\)'
OLD_DIV = re.compile(r'if \(ctx->f\[(\d+)\] == 0\.0f\) \{ ctx->fcr31 \|= 0x100000; /\* DZ flag \*/ '
                     r'ctx->f\[(\d+)\] = copysignf\(INFINITY, ctx->f\[(\d+)\] \* 0\.0f\); \} '
                     r'else ctx->f\[(\d+)\] = ctx->f\[(\d+)\] / ctx->f\[(\d+)\];$')
OLD_SQRT = re.compile(r'ctx->f\[(\d+)\] = FPU_SQRT_S\(ctx->f\[(\d+)\]\);$')
OLD_VDIV = re.compile(r'\{ float fs = ' + SHUF + r'; float ft = ' + SHUF.replace(r'\1', r'\3')
                      + r'; ctx->vu0_q = \(ft != 0\.0f\) \? \(fs / ft\) : 0\.0f; \}$')
OLD_VSQRT = re.compile(r'\{ float ft = ' + SHUF + r'; ctx->vu0_q = sqrtf\(std::max\(0\.0f, ft\)\); \}$')
OLD_VRSQRT = re.compile(r'\{ float ft = ' + SHUF + r'; ctx->vu0_q = \(ft > 0\.0f\) \? \(1\.0f / sqrtf\(ft\)\) : 0\.0f; \}$')


def shuf(reg, field):
    return f'_mm_cvtss_f32(_mm_shuffle_ps(ctx->vu0_vf[{reg}], ctx->vu0_vf[{reg}], _MM_SHUFFLE(0,0,0,{field})))'


def rewrite(word, stmt):
    """Return the new statement for one old statement, or raise if they disagree."""
    ft, fs, fd = (word >> 16) & 31, (word >> 11) & 31, (word >> 6) & 31
    cop1s = word >> 21 == (0x11 << 5 | 0x10)
    vspecial = word >> 25 == 0x25  # COP2, CO bit set
    ftf, fsf = (word >> 23) & 3, (word >> 21) & 3
    if m := OLD_DIV.match(stmt):
        if not (cop1s and word & 63 == 3) or tuple(map(int, m.groups())) != (ft, fd, fs, fd, fs, ft):
            raise ValueError('DIV.S mismatch')
        return f'ctx->f[{fd}] = ps2FpuDivide(ctx->fcr31, ctx->f[{fs}], ctx->f[{ft}]);'
    if m := OLD_SQRT.match(stmt):
        if not (cop1s and word & 63 == 4) or tuple(map(int, m.groups())) != (fd, ft):
            raise ValueError('SQRT.S mismatch')
        return f'ctx->f[{fd}] = ps2FpuSqrt(ctx->fcr31, ctx->f[{ft}]);'
    if m := OLD_VDIV.match(stmt):
        if not (vspecial and word & 0x7FF == 0x3BC) or tuple(map(int, m.groups())) != (fs, fsf, ft, ftf):
            raise ValueError('VDIV mismatch')
        return (f'{{ float fs = {shuf(fs, fsf)}; float ft = {shuf(ft, ftf)}; '
                f'ctx->vu0_q = ps2VuDivide(ctx->vu0_status, fs, ft); }}')
    if m := OLD_VSQRT.match(stmt):
        if not (vspecial and word & 0x7FF == 0x3BD) or tuple(map(int, m.groups())) != (ft, ftf):
            raise ValueError('VSQRT mismatch')
        return f'{{ float ft = {shuf(ft, ftf)}; ctx->vu0_q = ps2VuSqrt(ctx->vu0_status, ft); }}'
    if m := OLD_VRSQRT.match(stmt):
        if not (vspecial and word & 0x7FF == 0x3BE) or tuple(map(int, m.groups())) != (ft, ftf):
            raise ValueError('VRSQRT mismatch')
        return (f'{{ float fs = {shuf(fs, fsf)}; float ft = {shuf(ft, ftf)}; '
                f'ctx->vu0_q = ps2VuRsqrt(ctx->vu0_status, fs, ft); }}')
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--generated', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    elf = args.elf.read_bytes()
    ram, _ = load_ram(elf)
    out = args.out.absolute()
    out.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'elf_sha256': hashlib.sha256(elf).hexdigest(), 'applied': False, 'files': []}
    counts = {}
    prepared = []
    for source in sorted(args.generated.glob('*.cpp')):
        old_bytes = source.read_bytes()
        text = old_bytes.decode('utf-8')
        if not any(k in text for k in ('copysignf(INFINITY', 'FPU_SQRT_S(', 'vu0_q = (ft', 'sqrtf(std::max(0.0f, ft))')):
            continue
        lines = text.split('\n')
        word = at = None
        changed = 0
        for i, line in enumerate(lines):
            if w := WORD.match(line):
                at, word = int(w[1], 16), int(w[2], 16)
                continue
            stmt = line.strip()
            if word is None:
                continue
            try:
                new = rewrite(word, stmt)
            except ValueError as error:
                raise ValueError(f'{source.name}:{i + 1}: {error}: {stmt}') from None
            if new is None:
                continue
            if at + 4 > len(ram) or struct.unpack_from('<I', ram, at)[0] != word:
                raise ValueError(f'{source.name}:{i + 1}: word at {at:#x} differs from the ELF')
            lines[i] = line[:len(line) - len(line.lstrip())] + new
            kind = new.split('(')[0].split()[-1] if new.startswith('ctx') else new.split('ps2Vu')[1].split('(')[0]
            counts[kind] = counts.get(kind, 0) + 1
            changed += 1
        result = '\n'.join(lines)
        for marker in ('copysignf(INFINITY', 'FPU_SQRT_S(', '(fs / ft) : 0.0f', 'sqrtf(std::max(0.0f, ft))',
                       '(1.0f / sqrtf(ft))'):
            if marker in result:
                raise ValueError(f'{source.name}: unpatched old expression {marker!r}')
        if changed:
            prepared.append((source, result.encode('utf-8'), hashlib.sha256(old_bytes).hexdigest()))
            report['files'].append({'source': source.name, 'statements': changed,
                                    'before_sha256': hashlib.sha256(old_bytes).hexdigest()})
    if args.apply:
        backup = out / 'before'
        backup.mkdir(exist_ok=True)
        for source, _, sha in prepared:
            if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
                raise ValueError('Source changed during preparation')
        for source, data, _ in prepared:
            (backup / source.name).write_bytes(source.read_bytes())
            source.write_bytes(data)
        report['applied'] = True
    report['counts'] = counts
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'{len(prepared)} files, statements {counts}; applied={report["applied"]}')


if __name__ == '__main__':
    main()

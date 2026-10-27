"""Assemble complete native SNR2 modules into buildable, deduplicated sources.

Input is the directory written by snr2_full_plan.py after every <id>.toml has
been turned into <id>.cpp by ps2_native_module_codegen. Generated module
bodies never call one another by name (calls read their relocated targets from
RAM and dispatch), so two bodies whose generated code is identical apart from
their name are one implementation. Enemy and weapon variants share most of
their code this way.

Output (OUTDIR):
  snr2_bodies_NNN.cpp       unique bodies, re4_snr2_body_<hash>, ~4 MB each
  snr2_descriptors_NNN.cpp  one compact descriptor per module: text range,
                            masked text hash, relocated words, entry table
  re4-native-modules-full.cpp
                            the installer (ps2xInstallNativeModules) with one
                            catalogue entry per module image

The descriptors use the registry's compact identity: FNV-1a 64 over the text
words with relocated operand bits cleared, recomputed from RAM at bind time.

    python -m tools.diagnostics.snr2_full_build PLANDIR OUTDIR
"""
import argparse
import hashlib
import json
import ntpath
from pathlib import Path
import re
import struct

FUNCTION_MARK = re.compile(r'^// Function: (\S+)\n', re.M)
GUARD = re.compile(r'ps2_module_base > 0x[0-9a-f]+u')
ENTRY = re.compile(r'\{(\d+)u, (\d+)u, (\d+)u, (\w+)\},')
CHUNK_BYTES = 4 << 20

PRELUDE = ('#include <stdexcept>\n#include "ps2_runtime.h"\n#include "ps2_runtime_macros.h"\n'
           '#include "runtime/ps2_vu_control.h"\n'
           '#include "runtime/native_module_registry.h"\n')


def read_plan_relocations(toml_text):
    relocs = []
    for block in toml_text.split('[[instruction_relocations]]')[1:]:
        offset = int(re.search(r'offset = (\d+)', block).group(1))
        kind = int(re.search(r'type = (\d+)', block).group(1))
        relocs.append((offset, kind))
    return sorted(relocs)


def masked_text_hash(data, start, end, relocs):
    mask = {at: (0x03FFFFFF if kind == 4 else 0xFFFF) for at, kind in relocs}
    h = 0xCBF29CE484222325
    for at in range(start, end, 4):
        w = struct.unpack_from('<I', data, at)[0] & ~mask.get(at, 0) & 0xFFFFFFFF
        for i in range(4):
            h ^= (w >> (8 * i)) & 0xFF
            h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def base_of(module):
    return ntpath.basename(module['name']).rsplit('.', 1)[0]


def split_module(source):
    """Return ({name: function text}, descriptor text) of one generated module."""
    descriptor_at = source.index('const ps2x::NativeModuleDescriptor& ')
    body = source[:descriptor_at]
    marks = list(FUNCTION_MARK.finditer(body))
    functions = {}
    for i, mark in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        functions[mark.group(1)] = body[mark.start():stop]
    return functions, source[descriptor_at:]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('plandir', type=Path)
    parser.add_argument('outdir', type=Path)
    parser.add_argument('--hybrid-partial-dir', type=Path,
                        help='also include the hand-reviewed sscrn/st1_0/wep02 descriptors from this directory, '
                             'selected at run time with PS2X_NATIVE_PARTIAL')
    args = parser.parse_args()
    manifest = json.loads((args.plandir / 'manifest.json').read_text(encoding='utf-8'))
    args.outdir.mkdir(parents=True, exist_ok=True)

    unique = {}          # canonical name -> normalized text
    module_records = []
    total_bodies = 0
    for module in manifest['modules']:
        identifier = module['identifier']
        source = (args.plandir / f'{identifier}.cpp').read_text(encoding='utf-8')
        functions, descriptor = split_module(source)
        rename = {}
        for name, text in functions.items():
            normalized = GUARD.sub('ps2_module_base > 0xFE000000u', text.replace(name, '@@BODY@@'))
            canonical = 're4_snr2_body_' + hashlib.sha1(normalized.encode()).hexdigest()[:16]
            unique.setdefault(canonical, normalized)
            rename[name] = canonical
            total_bodies += 1
        entries = [(int(a), int(b), int(c), rename[n]) for a, b, c, n in ENTRY.findall(descriptor)]
        if not entries:
            raise SystemExit(f'{identifier}: no entries parsed')
        plan_text = (args.plandir / f'{identifier}.toml').read_text(encoding='utf-8')
        relocs = read_plan_relocations(plan_text)
        data = (args.plandir / f'{identifier}.bin').read_bytes()
        start = min(b for _, b, _, _ in entries)
        end = max(c for _, _, c, _ in entries)
        module_records.append({
            'module': module, 'entries': entries, 'relocs': relocs,
            'text_start': start, 'text_end': end,
            'hash': masked_text_hash(data, start, end, relocs)})

    # Bodies, chunked for parallel compilation.
    for old in args.outdir.glob('snr2_bodies_*.cpp'):
        old.unlink()
    for old in args.outdir.glob('snr2_descriptors_*.cpp'):
        old.unlink()
    chunk, chunk_bytes, index = [], 0, 0

    def flush():
        nonlocal chunk, chunk_bytes, index
        if not chunk:
            return
        (args.outdir / f'snr2_bodies_{index:03d}.cpp').write_text(PRELUDE + ''.join(chunk), encoding='utf-8')
        chunk, chunk_bytes, index = [], 0, index + 1

    for canonical in sorted(unique):
        text = unique[canonical].replace('@@BODY@@', canonical)
        chunk.append(text)
        chunk_bytes += len(text)
        if chunk_bytes >= CHUNK_BYTES:
            flush()
    flush()
    body_files = index

    # Descriptors.
    declared = 'void {}(uint8_t*, R5900Context*, PS2Runtime*, uint32_t);\n'
    per_file = 8
    descriptor_files = 0
    for group_start in range(0, len(module_records), per_file):
        group = module_records[group_start:group_start + per_file]
        names = sorted({e[3] for record in group for e in record['entries']})
        out = [PRELUDE] + [declared.format(n) for n in names]
        for record in group:
            module = record['module']
            ident = module['identifier']
            relocated = ', '.join(f'{(at >> 2) | (0x80000000 if kind == 4 else 0x40000000):#x}u'
                                  for at, kind in record['relocs'])
            entries = ',\n'.join(f'        {{{a}u, {b}u, {c}u, {n}}}' for a, b, c, n in record['entries'])
            out.append(
                f'const ps2x::NativeModuleDescriptor& {ident}_descriptor() {{\n'
                f'    static const ps2x::NativeModuleDescriptor descriptor = [] {{\n'
                f'        ps2x::NativeModuleDescriptor d;\n'
                f'        d.identity = "{module["identity"]}";\n'
                f'        d.imageSize = {module["bytes"]}u;\n'
                f'        d.textStart = {record["text_start"]}u;\n'
                f'        d.textEnd = {record["text_end"]}u;\n'
                f'        d.maskedTextHash = {record["hash"]:#x}ull;\n'
                f'        d.relocatedWords = {{{relocated}}};\n'
                f'        d.entries = {{\n{entries}\n        }};\n'
                f'        return d;\n'
                f'    }}();\n    return descriptor;\n}}\n')
        (args.outdir / f'snr2_descriptors_{descriptor_files:03d}.cpp').write_text(''.join(out), encoding='utf-8')
        descriptor_files += 1

    # Installer.
    lines = ['// Generated by tools/diagnostics/snr2_full_build.py from the original SNR2 modules.',
             '#include "runtime/snr2_native_binding.h"', '#include <cstdlib>', '#include <stdexcept>',
             '#include <string>', '#include <utility>', '']
    partial = {}
    if args.hybrid_partial_dir:
        # Hand-reviewed partial descriptors, selectable per image at run time
        # with PS2X_NATIVE_PARTIAL=name[,name...] (base names, e.g. st1_0) for
        # A/B comparison against the complete generated module.
        for base, source in (('sscrn', 'sscrn-native-lifecycle.cpp'), ('st1_0', 'st1_0-native-r120-events.cpp'),
                             ('wep02', 'wep02-native-events.cpp')):
            path = (args.hybrid_partial_dir / source).resolve()
            lines.append(f'#include "{path.as_posix()}"')
            partial[base] = f're4_{base}_descriptor'
        lines.append('')
    for record in module_records:
        lines.append(f'const ps2x::NativeModuleDescriptor& {record["module"]["identifier"]}_descriptor();')
    lines += ['', 'namespace {', 'bool usePartial(const char* base) {',
              '    const char* list = std::getenv("PS2X_NATIVE_PARTIAL");',
              '    if (!list) return false;',
              '    const std::string all = std::string(",") + list + ",";',
              '    return all.find(std::string(",") + base + ",") != std::string::npos;',
              '}', '}', '',
              'void ps2xInstallNativeModules(PS2Runtime& runtime) {',
              '    std::vector<ps2x::Snr2NativeBinding> catalogue;']
    for record in module_records:
        module = record['module']
        header = ', '.join(f'{w:#010x}u' for w in module['header'])
        name = module['name'].replace('\\', '\\\\')
        lines += ['    {', '    ps2x::Snr2NativeBinding item;',
                  '    item.loadSource = 0x2A57D8u;', '    item.loadSourceWord = 0x80F809u;',
                  '    item.unloadSource = 0x2A5870u;', '    item.unloadSourceWord = 0xC0A9578u;',
                  '    item.unloadTarget = 0x2A55E0u;', '    item.loadBaseRegister = 0x12u;',
                  '    item.unloadBaseRegister = 0x4u;',
                  f'    item.originalHeader = {{{header}}};',
                  f'    item.imageName = "{name}";',
                  (f'    item.descriptor = usePartial("{base_of(module)}") ? {partial[base_of(module)]}() : '
                   f'{module["identifier"]}_descriptor();' if base_of(module) in partial else
                   f'    item.descriptor = {module["identifier"]}_descriptor();'),
                  '    catalogue.push_back(std::move(item));', '    }']
    lines += ['    ps2x::installSnr2NativeBindings(runtime, std::move(catalogue));', '}', '']
    (args.outdir / 're4-native-modules-full.cpp').write_text('\n'.join(lines), encoding='utf-8')

    unique_bytes = sum(len(t) for t in unique.values())
    print(f'{len(module_records)} modules, {total_bodies} bodies -> {len(unique)} unique '
          f'({unique_bytes / 1e6:.0f} MB) in {body_files} body files, {descriptor_files} descriptor files')


if __name__ == '__main__':
    main()

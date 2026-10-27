"""Emit a game-specific native installer from pinned originals and reviewed loader sites."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from tools.diagnostics.snr2_inventory import parse_snr2, span


def elf_word(elf, address):
    span(elf, 0, 52)
    if elf[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H', elf, 18)[0] != 8:
        raise ValueError('Expected 32-bit little-endian MIPS ELF')
    at = struct.unpack_from('<I', elf, 28)[0]
    stride, count = struct.unpack_from('<HH', elf, 42)
    if stride < 32 or address % 4 or not 0 <= address <= 0xFFFFFFFC:
        raise ValueError('Invalid loader address or program headers')
    span(elf, at, stride*count)
    candidates = []
    for i in range(count):
        kind, offset, base, _, length, memlen, flags, _ = struct.unpack_from('<8I', elf, at+i*stride)
        if kind != 1:
            continue
        span(elf, offset, length)
        if length > memlen or base+memlen > 0x100000000:
            raise ValueError('Invalid ELF load segment')
        if base <= address and address+4 <= base+length and flags & 1:
            candidates.append(struct.unpack_from('<I', elf, offset+address-base)[0])
    if len(candidates) != 1:
        raise ValueError('Loader instruction lacks unique executable file mapping')
    return candidates[0]


def build_profile(module, elf, plan, sites):
    metadata = parse_snr2(module)
    identifier = plan.get('identifier', '')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', identifier):
        raise ValueError('Invalid native identifier')
    if plan.get('schema') != 1 or plan.get('identity') != metadata['sha256'] or plan.get('bytes') != len(module):
        raise ValueError('Native plan does not belong to original module')
    header = list(struct.unpack_from('<15I', module))
    name = metadata['original_image_name']
    if not name or '\ufffd' in name:
        raise ValueError('Expected original ASCII image name')
    for key in ('load_source', 'unload_source', 'unload_target', 'load_base_register', 'unload_base_register'):
        if type(sites.get(key)) is not int:
            raise ValueError('Explicit integer loader sites/registers required')
    if not all(0 <= sites[key] < 32 for key in ('load_base_register', 'unload_base_register')):
        raise ValueError('Invalid loader register')
    if sites['load_source'] == sites['unload_source']:
        raise ValueError('Loader boundaries must differ')
    load = elf_word(elf, sites['load_source'])
    unload = elf_word(elf, sites['unload_source'])
    # Require the actual original JALR/JAL rather than a guessed instruction word.
    if load >> 26 or load & 63 != 9 or (load >> 11 & 31) != 31:
        raise ValueError('Constructor boundary must be JALR with RA link')
    target = ((sites['unload_source']+4) & 0xF0000000) | ((unload & 0x3FFFFFF) << 2)
    if unload >> 26 != 3 or target != sites['unload_target']:
        raise ValueError('Unlink JAL does not target reviewed original function')
    elf_word(elf, sites['unload_target'])
    for entry in (header[6], header[7]):
        if not entry or not any(body['start'] <= entry < body['end'] for body in plan['bodies']):
            raise ValueError('Both lifecycle entries require reviewed native bodies')
    return dict(schema=1, identifier=identifier, module_sha256=metadata['sha256'],
                elf_sha256=hashlib.sha256(elf).hexdigest(), original_header=header,
                image_name=name, load_source_word=load, unload_source_word=unload, **sites)


def emit_installer(profile, native_source):
    return emit_catalogue([(profile, native_source)])


def emit_catalogue(items):
    if not items:
        raise ValueError('Empty loader catalogue')
    common_keys = ('elf_sha256', 'load_source', 'unload_source', 'unload_target',
                   'load_source_word', 'unload_source_word', 'load_base_register', 'unload_base_register')
    signature = tuple(items[0][0][key] for key in common_keys)
    names, identifiers, sources = set(), set(), set()
    for profile, source in items:
        if tuple(profile[key] for key in common_keys) != signature:
            raise ValueError('Catalogue loader sites must belong to one original ELF and loader')
        if profile['image_name'] in names or profile['identifier'] in identifiers or source.resolve() in sources:
            raise ValueError('Duplicate native image, identifier or source')
        names.add(profile['image_name'])
        identifiers.add(profile['identifier'])
        sources.add(source.resolve())
    lines = ['// Local game-specific installer. Generated from original ELF and SNR2 metadata.',
             '#include "runtime/snr2_native_binding.h"', '#include <stdexcept>', '#include <utility>']
    lines += [f'#include {json.dumps(source.resolve().as_posix())}' for _, source in items]
    lines += ['void ps2xInstallNativeModules(PS2Runtime& runtime) {',
              '    std::vector<ps2x::Snr2NativeBinding> catalogue;']
    for profile, _ in items:
        header = ', '.join(f'0x{value:08X}u' for value in profile['original_header'])
        lines += ['    {', '    ps2x::Snr2NativeBinding item;']
        for member, key in [('loadSource','load_source'), ('loadSourceWord','load_source_word'),
                        ('unloadSource','unload_source'), ('unloadSourceWord','unload_source_word'),
                        ('unloadTarget','unload_target'), ('loadBaseRegister','load_base_register'),
                        ('unloadBaseRegister','unload_base_register')]:
            lines.append(f'    item.{member} = 0x{profile[key]:X}u;')
        lines += [f'    item.originalHeader = {{{header}}};',
              f'    item.imageName = {json.dumps(profile["image_name"])};',
              f'    item.descriptor = {profile["identifier"]}_descriptor();',
              f'    if (item.descriptor.identity != {json.dumps(profile["module_sha256"])})',
              '        throw std::invalid_argument("Native descriptor identity differs from loader profile");',
              '    catalogue.push_back(std::move(item));', '    }']
    lines += ['    ps2x::installSnr2NativeBindings(runtime, std::move(catalogue));', '}']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--module', type=Path)
    group.add_argument('--catalogue', type=Path, help='JSON list of module/native_plan/native_source paths, relative to this file')
    for name in ('native-plan', 'native-source'):
        parser.add_argument('--'+name, type=Path)
    for name in ('elf', 'sites', 'output', 'report'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if args.module and (not args.native_plan or not args.native_source):
        parser.error('Single module requires native-plan and native-source')
    if args.catalogue and (args.native_plan or args.native_source):
        parser.error('Catalogue supplies its own native plans and sources')
    try:
        if args.catalogue:
            entries = json.loads(args.catalogue.read_text(encoding='utf-8-sig'))
            if not isinstance(entries, list) or not entries:
                raise ValueError('Catalogue must be a nonempty list')
            specs = [tuple(args.catalogue.parent / entry[key] for key in ('module','native_plan','native_source'))
                     for entry in entries]
        else:
            specs = [(args.module, args.native_plan, args.native_source)]
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    inputs = [args.elf, args.sites] + ([args.catalogue] if args.catalogue else [])
    inputs += [path for spec in specs for path in spec]
    outputs = (args.output.resolve(), args.report.resolve())
    if len(set(outputs)) != 2 or any(path.resolve() in outputs for path in inputs):
        parser.error('Outputs must differ from inputs and each other')
    try:
        elf = args.elf.read_bytes()
        sites = json.loads(args.sites.read_text(encoding='utf-8-sig'))
        items = []
        for module, plan, native_source in specs:
            profile = build_profile(module.read_bytes(), elf, json.loads(plan.read_text(encoding='utf-8-sig')), sites)
            source = native_source.read_text(encoding='utf-8-sig')
            if profile['identifier']+'_descriptor()' not in source:
                raise ValueError('Native source has no matching descriptor factory')
            profile['native_source_sha256'] = hashlib.sha256(native_source.read_bytes()).hexdigest()
            profile['scope'] = 'Reviewed loader profile; runtime validates header/code. Not full-image cryptographic validation or complete module translation.'
            items.append((profile, native_source))
        emitted = emit_catalogue(items)
        report = items[0][0] if args.module else dict(schema=1, modules=[p for p, _ in items])
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    for output in (args.output, args.report):
        output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(emitted, encoding='utf-8')
    args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()

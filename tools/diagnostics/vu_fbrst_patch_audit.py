"""Verify FBRST source edits against preserved sources and original game words."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def elf_word(data, address):
    if data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('Expected ELF32LE source')
    at = struct.unpack_from('<I', data, 28)[0]
    stride, count = struct.unpack_from('<HH', data, 42)
    if stride != 32:
        raise ValueError('Expected ELF32 program headers')
    for index in range(count):
        kind, offset, virtual, _, size, _, _, _ = struct.unpack_from('<8I', data, at + index * stride)
        if kind == 1 and virtual <= address and address + 4 <= virtual + size:
            return struct.unpack_from('<I', data, offset + address - virtual)[0]
    raise ValueError('Instruction address has no file-backed LOAD span')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Preserve existing reports')
    root = Path(__file__).resolve().parents[2]
    backup = root / 'artifacts/tool-audit/20261013/vu-control-before'
    sources = [('recomp/generated/SLUS_211.34/FUN_002A5938_0x2a5938.cpp', 4, 2),
               ('recomp/native/SLUS_211.34/full/re4_sscrn_07d89778.cpp', 8, 1),
               ('recomp/native/SLUS_211.34/full_build/snr2_bodies_062.cpp', 8, 1)]
    result = {'sources': [], 'original_instructions': [], 'passed': False,
              'scope': 'Exact source edit and original instruction identity; game effect is not proved.'}
    for relative, register, count in sources:
        source = root / relative
        old_path = backup / source.name
        old, current = old_path.read_text(), source.read_text()
        assignment = f'ctx->vu0_fbrst = GPR_U32(ctx, {register}) & 0x00000C0Cu;'
        replacement = f'ps2WriteVuFbrst(*runtime, *ctx, GPR_U32(ctx, {register}));'
        if old.count(assignment) != count:
            raise ValueError('Unexpected baseline control-write count')
        expected = old.replace(assignment, replacement).replace(
            '#include "ps2_runtime.h"\n', '#include "ps2_runtime.h"\n#include "runtime/ps2_vu_control.h"\n', 1)
        if expected != current:
            raise ValueError(f'Additional source edit: {source}')
        result['sources'].append({'path': str(source), 'before_sha256': hashlib.sha256(old_path.read_bytes()).hexdigest(),
                                 'after_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                 'reset_calls': count, 'only_expected_changes': True})
    main_data = (root / 'Resident Evil 4/SLUS_211.34').read_bytes()
    for address in (0x2A596C, 0x2A5994):
        word = elf_word(main_data, address)
        if word != 0x48C4E000:
            raise ValueError('Main ELF does not contain expected CTC2 instruction')
        result['original_instructions'].append({'format': 'ELF', 'address': hex(address), 'word': hex(word)})
    module = root / 'artifacts/tool-audit/20261013/game-binaries-extracted/snr2/07d89778381b7da214677c3a5d0f12e3b42fc67a15f5049baf5f47e648c9a5f9.snr2'
    data = module.read_bytes()
    if hashlib.sha256(data).hexdigest() != module.stem or struct.unpack_from('<I', data, 0x381A8)[0] != 0x48C8E000:
        raise ValueError('Screen module source identity differs')
    result['original_instructions'].append({'format': 'SNR2', 'offset': '0x381a8', 'word': '0x48c8e000', 'sha256': module.stem})
    plan = json.loads((root / 'recomp/native/SLUS_211.34/full/manifest.json').read_text())
    census = {'scope': 'Only existing native-plan text ranges, not arbitrary data or unplanned code.',
              'verified_images': [], 'fbrst_writes': [], 'instructions_scanned': 0}
    for image in plan['modules']:
        source = root / 'artifacts/tool-audit/20261013/game-binaries-extracted/snr2' / (image['identity'] + '.snr2')
        image_data = source.read_bytes()
        if hashlib.sha256(image_data).hexdigest() != image['identity']:
            raise ValueError('Current native-plan image differs from extracted game image')
        end = image['text_end']
        if not 0x100 < end <= len(image_data) or end % 4:
            raise ValueError('Unbounded native-plan text range')
        census['verified_images'].append(image['identity'])
        for index, (word,) in enumerate(struct.iter_unpack('<I', image_data[0x100:end])):
            if word & 0xFFE0F800 == 0x48C0E000:
                census['fbrst_writes'].append({'name': image['name'], 'sha256': image['identity'],
                                              'offset': hex(0x100 + index * 4), 'word': hex(word),
                                              'source_register': (word >> 16) & 31})
        census['instructions_scanned'] += (end - 0x100) // 4
    result['native_plan_census'] = census
    result['passed'] = True
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'source_files': len(sources), 'distinct_original_instructions': 3,
                      'native_images': len(census['verified_images']),
                      'native_fbrst_writes': len(census['fbrst_writes']),
                      'instructions_scanned': census['instructions_scanned']}))


if __name__ == '__main__':
    main()

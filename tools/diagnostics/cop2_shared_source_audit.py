"""Audit scoped shared-control reader edits against preserved source/game words."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from vu_fbrst_patch_audit import elf_word


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    backup = root / 'artifacts/tool-audit/20261013/cop2-shared-before'
    sources = [('recomp/generated/SLUS_211.34/FUN_00251758_0x251758.cpp', 1, 'ELF'),
               ('recomp/generated/SLUS_211.34/FUN_002A5938_0x2a5938.cpp', 2, 'ELF'),
               ('recomp/generated/SLUS_211.34/FUN_002A59D8_0x2a59d8.cpp', 1, 'ELF'),
               ('recomp/native/SLUS_211.34/full_build/snr2_bodies_062.cpp', 1, 'SNR2')]
    elf = (root / 'Resident Evil 4/SLUS_211.34').read_bytes()
    module_identity = '07d89778381b7da214677c3a5d0f12e3b42fc67a15f5049baf5f47e648c9a5f9'
    module = (root / 'artifacts/tool-audit/20261013/game-binaries-extracted/snr2' / (module_identity + '.snr2')).read_bytes()
    if hashlib.sha256(module).hexdigest() != module_identity:
        raise ValueError('Original screen image identity mismatch')
    report = {'scope': __doc__, 'files': [], 'instructions': [], 'passed': False}
    for relative, count, kind in sources:
        path = root / relative
        old_path = backup / path.name
        old = old_path.read_text()
        expected = old.replace('ctx->vu0_fbrst', 'ps2ReadVuFbrst(*runtime, *ctx)').replace(
            'ctx->vu0_vpu_stat', 'ps2ReadVuStatus(*runtime, *ctx)')
        if '#include "runtime/ps2_vu_control.h"' not in expected:
            expected = expected.replace('#include "ps2_runtime.h"\n',
                                        '#include "ps2_runtime.h"\n#include "runtime/ps2_vu_control.h"\n', 1)
        if expected != path.read_text():
            raise ValueError(f'Additional source edit: {path}')
        actual_count = 0
        address = word = None
        for line in old.splitlines():
            match = re.search(r'// (0x[0-9a-fA-F]+): (0x[0-9a-fA-F]+)', line)
            if match:
                address, word = (int(item, 16) for item in match.groups())
            read = re.search(r'SET_GPR_U32\(ctx, (\d+), ctx->vu0_(fbrst|vpu_stat)\);', line)
            if not read:
                continue
            actual = elf_word(elf, address) if kind == 'ELF' else struct.unpack_from('<I', module, address)[0]
            rd = 28 if read[2] == 'fbrst' else 29
            if actual != word or word & 0xFFE0F800 != (0x48400000 | rd << 11) or (word >> 16) & 31 != int(read[1]):
                raise ValueError('Reader and original CFC2 instruction disagree')
            actual_count += 1
            report['instructions'].append({'format': kind, 'address_or_offset': hex(address),
                                           'word': hex(word), 'control_register': rd})
        if actual_count != count:
            raise ValueError('Unexpected source reader count')
        report['files'].append({'path': str(path), 'before_sha256': hashlib.sha256(old_path.read_bytes()).hexdigest(),
                                'after_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'readers': count})
    plan = json.loads((root / 'recomp/native/SLUS_211.34/full/manifest.json').read_text())
    census = []
    words = 0
    for image in plan['modules']:
        data = (root / 'artifacts/tool-audit/20261013/game-binaries-extracted/snr2' / (image['identity'] + '.snr2')).read_bytes()
        if hashlib.sha256(data).hexdigest() != image['identity'] or not 0x100 < image['text_end'] <= len(data) or image['text_end'] % 4:
            raise ValueError('Native-plan identity or text range mismatch')
        for index, (word,) in enumerate(struct.iter_unpack('<I', data[0x100:image['text_end']])):
            if word & 0xFFE0F800 in (0x4840E000, 0x4840E800):
                census.append({'name': image['name'], 'sha256': image['identity'], 'offset': hex(0x100 + index * 4), 'word': hex(word)})
        words += (image['text_end'] - 0x100) // 4
    report.update(passed=True, native_plan_readers=census, native_images=len(plan['modules']),
                  native_words=words, limits=['Census follows current planned text ranges; does not certify all possible code.'])
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({'passed': True, 'source_files': len(sources), 'original_readers': len(report['instructions']),
                      'native_images': report['native_images'], 'native_readers': len(census)}))


if __name__ == '__main__':
    main()

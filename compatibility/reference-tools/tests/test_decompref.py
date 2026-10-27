"""Reject stale or inconsistent references before presenting recorded matches."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from ps2l.decompref import lookup, address

ROOT = Path(__file__).resolve().parent.parent


class DecompReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='decompref-test-', dir=ROOT / 'tmp')
        self.root = Path(self.tmp.name).resolve()
        assert self.root.is_relative_to((ROOT / 'tmp').resolve())
        self.addCleanup(self.tmp.cleanup)
        self.code = bytes.fromhex('0800e0030000000000000000')
        elf = bytearray(84 + len(self.code))
        elf[:6] = b'\x7fELF\x01\x01'
        struct.pack_into('<H', elf, 18, 8)
        struct.pack_into('<I', elf, 28, 52)
        struct.pack_into('<HH', elf, 42, 32, 1)
        struct.pack_into('<IIIIIIII', elf, 52, 1, 84, 0x1000, 0x1000, len(self.code), len(self.code), 5, 4)
        elf[84:] = self.code
        self.elf = self.root / 'game.elf'
        self.elf.write_bytes(elf)
        self.source = self.root / 'candidate.c'
        self.source.write_text('void func_00001000(void) {}\n')
        self.obj = self.root / 'candidate.o'
        self.obj.write_bytes(b'fixture object')
        self.evidence = self.root / 'evidence.json'
        self.index = self.root / 'index.json'
        self.entry = {'name': 'func_00001000', 'address': '0x00001000', 'size': len(self.code),
            'source': str(self.source), 'object': str(self.obj), 'evidence': str(self.evidence),
            'source_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
            'object_sha256': hashlib.sha256(self.obj.read_bytes()).hexdigest(),
            'target_sha256': hashlib.sha256(self.code).hexdigest(), 'flags': ['-O2', '-G0'],
            'exact_reverified': True, 'mutated_target_rejected': True}
        self.data = {'elf_sha256': hashlib.sha256(elf).hexdigest(), 'entries': [self.entry]}
        self.write()

    def write(self):
        self.index.write_text(json.dumps(self.data))
        self.evidence.write_text(json.dumps(self.data))

    def test_inside_function_returns_offset_and_verifies_files(self):
        result = lookup(self.index, self.elf, 0x1004)
        self.assertEqual(result['status'], 'verified_artifacts')
        self.assertEqual(result['entries'][0]['offset'], 4)

    def test_changed_source_or_object_is_rejected(self):
        for path, message in ((self.source, 'Source'), (self.obj, 'Object')):
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.assertRaisesRegex(ValueError, message + ' has changed'):
                lookup(self.index, self.elf, 0x1000)
            path.write_bytes(original)

    def test_wrong_elf_identity_is_rejected(self):
        self.elf.write_bytes(self.elf.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'ELF identity'):
            lookup(self.index, self.elf)

    def test_assisted_context_is_verified(self):
        context = self.root / 'context.c'
        context.write_text('void helper(void *);\n')
        self.entry.update(context=str(context), context_sha256=hashlib.sha256(context.read_bytes()).hexdigest(),
                          origin='assisted', candidate_repairs=['Fix indirect call parentheses'])
        self.write()
        result = lookup(self.index, self.elf)
        self.assertEqual(result['entries'][0]['origin'], 'assisted')
        context.write_text('void changed(int);\n')
        with self.assertRaisesRegex(ValueError, 'Context has changed'):
            lookup(self.index, self.elf)

    def test_target_hash_checked_even_if_manifests_agree(self):
        self.entry['target_sha256'] = '0' * 64
        self.write()
        with self.assertRaisesRegex(ValueError, 'Target bytes differ'):
            lookup(self.index, self.elf)

    def test_index_cannot_change_recorded_flags(self):
        self.entry['flags'] = ['-O0']
        self.index.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError, 'manifest disagree: flags'):
            lookup(self.index, self.elf)

    def test_duplicate_ranges_are_rejected(self):
        self.data['entries'].append(copy.deepcopy(self.entry))
        self.write()
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            lookup(self.index, self.elf)

    def test_missing_negative_control_is_rejected(self):
        self.entry['mutated_target_rejected'] = False
        self.write()
        with self.assertRaisesRegex(ValueError, 'negative control'):
            lookup(self.index, self.elf)

    def test_missing_coverage_is_not_a_match(self):
        self.assertEqual(lookup(self.index, self.elf, 0x1100)['status'], 'not_found')

    def test_paths_outside_artifact_root_are_rejected(self):
        self.entry['source'] = str(self.root.parent / 'outside.c')
        self.write()
        with self.assertRaisesRegex(ValueError, 'outside the index directory'):
            lookup(self.index, self.elf)

    def test_target_file_bounds_are_checked(self):
        program = bytearray(self.elf.read_bytes())
        struct.pack_into('<I', program, 56, len(program) - 1)
        self.elf.write_bytes(program)
        self.data['elf_sha256'] = hashlib.sha256(program).hexdigest()
        self.write()
        with self.assertRaisesRegex(ValueError, 'extends beyond'):
            lookup(self.index, self.elf)

    def test_address_spellings(self):
        for value in ('0x00001000', '0X00001000', '00001000', 'func_00001000', 'FUN_00001000', 'sub_00001000'):
            self.assertEqual(address(value), 0x1000)
        with self.assertRaises(ValueError):
            address('not-an-address')


if __name__ == '__main__':
    unittest.main()

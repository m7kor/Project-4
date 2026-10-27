import hashlib
from pathlib import Path
import struct
import unittest

from tools.diagnostics.snr2_loader_profile import build_profile, emit_installer, emit_catalogue, elf_word


class Snr2LoaderProfileTests(unittest.TestCase):
    def fixture(self):
        module = bytearray(160)
        struct.pack_into('<15I', module, 0, 0x32524E53, 0, 0, 0, 0, 80, 60, 64, 0, 0, 128, 160, 0, 0, 0)
        module[80:92] = b'fixture.elf\0'
        elf = bytearray(256)
        elf[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<H', elf, 18, 8)
        struct.pack_into('<I', elf, 28, 52)
        struct.pack_into('<HH', elf, 42, 32, 1)
        struct.pack_into('<8I', elf, 52, 1, 0, 0x2000, 0, len(elf), len(elf), 5, 16)
        struct.pack_into('<I', elf, 0x90, 0x0080F809)
        struct.pack_into('<I', elf, 0x98, 0x0C000828)
        plan = dict(schema=1, identifier='fixture', bytes=len(module),
                    identity=hashlib.sha256(module).hexdigest(), bodies=[dict(start=60, end=76)])
        sites = dict(load_source=0x2090, unload_source=0x2098, unload_target=0x20A0,
                     load_base_register=18, unload_base_register=4)
        return module, elf, plan, sites

    def test_original_elf_opcodes_and_module_identity_are_emitted(self):
        module, elf, plan, sites = self.fixture()
        profile = build_profile(module, elf, plan, sites)
        self.assertEqual(profile['load_source_word'], 0x0080F809)
        self.assertEqual(profile['unload_source_word'], 0x0C000828)
        self.assertEqual(profile['image_name'], 'fixture.elf')
        source = emit_installer(profile, Path('local.cpp'))
        self.assertIn('item.loadSourceWord = 0x80F809u;', source)
        self.assertIn('fixture_descriptor()', source)
        self.assertIn(profile['module_sha256'], source)

    def test_wrong_originals_missing_lifecycle_and_guessed_sites_reject(self):
        for variant in range(7):
            module, elf, plan, sites = self.fixture()
            if variant == 0:
                plan['identity'] = 'wrong'
            elif variant == 1:
                plan['bodies'] = [dict(start=60, end=64)]
            elif variant == 2:
                struct.pack_into('<I', elf, 0x90, 0x00400008)  # JR, not JALR.
            elif variant == 3:
                sites['unload_target'] = 0x20A4
            elif variant == 4:
                sites['load_base_register'] = 32
            elif variant == 5:
                sites['unload_source'] = 0x2100  # Outside file mapping.
            else:
                struct.pack_into('<I', elf, 52+24, 4)  # No executable mapping.
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                build_profile(module, elf, plan, sites)

    def test_elf_mapping_cannot_read_past_segment_or_use_unaligned_address(self):
        _, elf, _, _ = self.fixture()
        for at in (0x2091, 0x2100, 0xFFFFFFFC):
            with self.assertRaises(ValueError):
                elf_word(elf, at)

    def test_catalogue_installs_all_modules_once_and_rejects_duplicate_or_different_loader(self):
        module, elf, plan, sites = self.fixture()
        first = build_profile(module, elf, plan, sites)
        second = dict(first, identifier='second', image_name='second.elf')
        emitted = emit_catalogue([(first, Path('first.cpp')), (second, Path('second.cpp'))])
        self.assertEqual(emitted.count('ps2x::installSnr2NativeBindings('), 1)
        self.assertEqual(emitted.count('catalogue.push_back('), 2)
        for variant in range(5):
            other = dict(second)
            path = Path('second.cpp')
            if variant == 0: other['image_name'] = first['image_name']
            elif variant == 1: other['identifier'] = first['identifier']
            elif variant == 2: path = Path('first.cpp')
            elif variant == 3: other['load_source'] += 4
            else: other['elf_sha256'] = 'another-original'
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                emit_catalogue([(first,Path('first.cpp')),(other,path)])


if __name__ == '__main__':
    unittest.main()

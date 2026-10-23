import struct
import unittest
from tools.diagnostics.snr2_imports import resolve_imports, relocate_selected_imports


class Snr2ImportTests(unittest.TestCase):
    def fixture(self):
        module = bytearray(0x400)
        struct.pack_into('<15I', module, 0, 0x32524E53, 0x80, 1, 0x120, 1, 0, 0, 0, 0, 0, 128, len(module), 0, 0x300, 0)
        struct.pack_into('<IIi', module, 0x80, 0x100, 4, 12)
        struct.pack_into('<I', module, 0x100, 0x0C000000)
        struct.pack_into('<IIHBB', module, 0x120, 0x160, 0, 0x1234, 1, 0)
        module[0x160:0x167] = b'import\0'
        elf = bytearray(0x300)
        elf[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<HH', elf, 16, 2, 8)
        struct.pack_into('<I', elf, 28, 52)
        struct.pack_into('<HH', elf, 42, 32, 1)
        struct.pack_into('<8I', elf, 52, 1, 0, 0x100000, 0, len(elf), len(elf), 5, 16)
        elf[0x100:0x107] = b'import\0'
        struct.pack_into('<IIHBB', elf, 0x180, 0x100100, 0x100200, 0x1234, 2, 0)
        return module, elf

    def test_original_named_record_and_full_symbol_addend_patch(self):
        module, elf = self.fixture()
        original = bytes(module)
        resolution = resolve_imports(module, elf, ['import'])
        self.assertEqual(resolution['imports'][0]['address'], 0x100200)
        self.assertEqual(resolution['imports'][0]['export_record'], 0x100180)
        patched = relocate_selected_imports(module, 0x800000, resolution)
        self.assertEqual(struct.unpack_from('<I', patched, 0x100)[0], 0x0C000000 | (0x10020C >> 2))
        self.assertEqual(module, original)

    def test_duplicate_export_wrong_hash_and_truncated_segments_reject(self):
        for variant in range(5):
            module, elf = self.fixture()
            if variant == 0:
                elf[0x190:0x19C] = elf[0x180:0x18C]
            elif variant == 1:
                struct.pack_into('<H', elf, 0x188, 0x5678)
            elif variant == 2:
                struct.pack_into('<I', elf, 52 + 16, len(elf) + 4)
            elif variant == 3:
                struct.pack_into('<I', elf, 52 + 16, 0x188)
            else:
                struct.pack_into('<I', elf, 52 + 16, 0x105)
            with self.assertRaises(ValueError):
                resolve_imports(module, elf, ['import'])

    def test_resolution_cannot_patch_a_different_original_module(self):
        module, elf = self.fixture()
        resolution = resolve_imports(module, elf, ['import'])
        module[0x250] = 1
        with self.assertRaises(ValueError):
            relocate_selected_imports(module, 0x800000, resolution)


if __name__ == '__main__':
    unittest.main()

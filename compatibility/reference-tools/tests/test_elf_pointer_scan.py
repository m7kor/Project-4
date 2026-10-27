import struct
import unittest

from tools.diagnostics.elf_pointer_scan import scan


def fixture():
    data = bytearray(256)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<H', data, 18, 8)
    struct.pack_into('<I', data, 32, 52)
    struct.pack_into('<HH', data, 46, 40, 3)
    struct.pack_into('<10I', data, 92, 0, 1, 6, 0x1000, 172, 8, 0, 0, 4, 0)
    struct.pack_into('<10I', data, 132, 0, 1, 2, 0x2000, 180, 24, 0, 0, 4, 0)
    struct.pack_into('<2I', data, 172, 0x27BDFFE0, 0x03E00008)
    struct.pack_into('<6I', data, 180, 0x1000, 0x1004, 0x1008, 0x1001, 0x2000, 0x1000)
    return data


class PointerScanTests(unittest.TestCase):
    def test_boundaries_duplicates_and_hints(self):
        result = scan(fixture())['candidates']
        self.assertEqual([r['target'] for r in result], [0x1000, 0x1004])
        self.assertEqual([r['address'] for r in result[0]['references']], [0x2000, 0x2014])
        self.assertEqual(result[0]['entry_hint'], 'negative_stack_adjustment')
        self.assertEqual(result[1]['entry_hint'], 'return_stub')

    def test_nobits_not_scanned(self):
        data = fixture()
        struct.pack_into('<I', data, 136, 8)
        self.assertEqual(scan(data)['candidates'], [])

    def test_invalid_headers_and_truncation(self):
        for offset, value in ((4, 2), (5, 2), (18, 62)):
            data = fixture()
            data[offset] = value
            with self.assertRaises(ValueError):
                scan(data)
        with self.assertRaises(ValueError):
            scan(fixture()[:200])

    def test_unclassified_target_retained_for_review(self):
        data = fixture()
        struct.pack_into('<I', data, 172, 0)
        self.assertEqual(scan(data)['candidates'][0]['entry_hint'], 'unclassified')

    def test_virtual_range_wrap_rejected(self):
        data = fixture()
        struct.pack_into('<I', data, 104, 0xFFFFFFFC)
        with self.assertRaises(ValueError):
            scan(data)


if __name__ == '__main__':
    unittest.main()

import struct
import unittest
from tools.diagnostics.re4_name_table import recover


def image(value=0x100040, kind=2, reserved=0):
    data = bytearray(0x500)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<H', data, 18, 8)
    struct.pack_into('<I', data, 28, 52)
    struct.pack_into('<HH', data, 42, 32, 1)
    struct.pack_into('<8I', data, 52, 1, 0x100, 0x100000, 0x100000, 0x400, 0x600, 7, 0x1000)
    name = b'move__7cPlayer\0'
    data[0x300:0x300 + len(name)] = name
    struct.pack_into('<I', data, 0x17c, 0x100080)  # tempting but unrelated preceding word
    struct.pack_into('<IIHBB', data, 0x180, 0x100200, value, 0xabcd, kind, reserved)
    return bytes(data)


class NameTableTests(unittest.TestCase):
    def test_export_value_follows_name_pointer(self):
        names, total = recover(image())
        self.assertEqual(total, 1)
        self.assertEqual(names, {0x100040: 'move__7cPlayer'})

    def test_bad_metadata_and_unmapped_values_are_not_nearest_code(self):
        for data in (image(kind=9), image(reserved=1), image(value=0x90000000)):
            with self.subTest(data=data[0x180:0x18c]):
                self.assertEqual(recover(data)[0], {})

    def test_bss_export_is_an_address_without_claiming_it_is_a_function(self):
        self.assertEqual(recover(image(value=0x100500))[0], {0x100500: 'move__7cPlayer'})

    def test_invalid_elf_and_truncated_segment_are_rejected(self):
        for data in (b'bad', image()[:-1]):
            with self.subTest(size=len(data)):
                with self.assertRaises(ValueError):
                    recover(data)

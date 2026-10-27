from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from architecture_ammo import packed_counter


class PackedCounterTests(unittest.TestCase):
    def fixture(self, counter=5, flags=0):
        memory = bytearray(128)
        struct.pack_into('<I', memory, 8, 34)  # Two-byte aligned, not necessarily four.
        struct.pack_into('<H', memory, 34, 0x23)
        struct.pack_into('<H', memory, 42, (counter << 3) | flags)
        return memory

    def test_packed_count_is_not_raw_byte(self):
        self.assertEqual(packed_counter(self.fixture(), 8, 0x23)['counter'], 5)

    def test_low_bits_do_not_restore_ammunition(self):
        for flags in range(8):
            result = packed_counter(self.fixture(4, flags), 8, 0x23)
            self.assertEqual((result['counter'], result['low_bits']), (4, flags))

    def test_unknown_item_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported item'):
            packed_counter(self.fixture(), 8, 0x24)

    def test_out_of_bounds_pointer_and_null_are_rejected(self):
        for pointer in (0, 127, 0xffffffff):
            memory = self.fixture()
            struct.pack_into('<I', memory, 8, pointer)
            with self.assertRaises(ValueError):
                packed_counter(memory, 8, 0x23)

    def test_invalid_field_contract_is_rejected(self):
        for offset, shift in ((-2, 3), (3, 3), (8, 16)):
            with self.assertRaises(ValueError):
                packed_counter(self.fixture(), 8, 0x23, offset, shift)


if __name__ == '__main__':
    unittest.main()

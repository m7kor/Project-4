import struct
import unittest

from tools.diagnostics.snr2_relocations import compact_relocations, patch_word, relocate_local_code


class Snr2RelocationTests(unittest.TestCase):
    def fixture(self, stream):
        data = bytearray(0x400)
        header = [0x32524E53, 0, 0, 0, 0, 0, 0, 0, 0, 0, 128, len(data), 0, 0x300, 0]
        struct.pack_into('<15I', data, 0, *header)
        data[0x300:0x300 + len(stream)] = stream
        return data

    def test_local_patches_and_explicit_hi_lo_chain(self):
        # Two HI patches share a later LO; scanning the pair must not consume
        # the outer stream. Finally relocate a call and a local pointer.
        stream = bytes([1]) + struct.pack('<I', 0x100) + bytes([5, 4, 6, 7]) + bytes(5)
        data = self.fixture(stream)
        struct.pack_into('<5I', data, 0x100, 0x3C070004, 0x3C080004,
                         0x24E7AF30, 0x0C000040, 0x100)
        records = compact_relocations(data)
        self.assertEqual([r['offset'] for r in records], [0x100, 0x104, 0x108, 0x10C, 0x110])
        self.assertEqual(records[0]['pair_scan_offsets'], [0x104, 0x108])
        self.assertEqual(records[0]['final_low_offset'], 0x108)
        self.assertEqual(records[0]['target_offset'], 0x3AF30)
        for base in (0x10FD800, 0x20F100):
            output = relocate_local_code(data, base)
            high = struct.unpack_from('<I', output, 0x100)[0] & 65535
            low = struct.unpack_from('<I', output, 0x108)[0] & 65535
            self.assertEqual((high << 16) + (low if low < 32768 else low - 65536), base + 0x3AF30)
            self.assertEqual(struct.unpack_from('<I', output, 0x10C)[0], 0x0C000000 | ((base + 0x100) >> 2))
            self.assertEqual(struct.unpack_from('<I', output, 0x110)[0], base + 0x100)
        self.assertEqual(struct.unpack_from('<I', data, 0x100)[0], 0x3C070004)

    def test_low_patch_signed_carry_and_word_wrapping(self):
        self.assertEqual(patch_word(0x3C070000, 5, 0x12348000), 0x3C071235)
        self.assertEqual(patch_word(0x8CE50000, 6, 0x12348000), 0x8CE58000)
        self.assertEqual(patch_word(0x3C070000, 5, 0xFFFF8000), 0x3C070000)
        self.assertEqual(patch_word(0, 2, -1), 0xFFFFFFFF)

    def test_truncated_stream_invalid_chain_and_patch_rejected(self):
        for stream in (bytes([1]) + struct.pack('<I', 0x100) + bytes(5),
                       bytes([3]) + struct.pack('<I', 0x3FE)):
            with self.assertRaises(ValueError):
                compact_relocations(self.fixture(stream))
        data = self.fixture(bytes([0]))
        struct.pack_into('<I', data, 0x34, len(data) - 1)
        with self.assertRaises(ValueError):
            compact_relocations(data)
        with self.assertRaises(ValueError):
            patch_word(0xD, 5, 0x100)
        with self.assertRaises(ValueError):
            patch_word(0, 123, 0x100)
        with self.assertRaises(ValueError):
            relocate_local_code(data, 0xFFFFFFFF)


if __name__ == '__main__':
    unittest.main()

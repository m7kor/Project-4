import struct
import unittest

from tools.diagnostics.snr2_inventory import parse_snr2, verify_runtime_header


class Snr2InventoryTests(unittest.TestCase):
    def fixture(self):
        data = bytearray(0xE00)
        symbol_at = 0x100
        name_at = symbol_at + 261 * 12
        reloc_at = name_at + 32
        header = [0x32524E53, reloc_at, 1, symbol_at, 261, name_at,
                  0x80, 0, 0, 0, 0x80, len(data), 0, 0, 0]
        struct.pack_into("<15I", data, 0, *header)
        struct.pack_into("<4I", data, 0x80, 0x3C070000, 0x27BDFFD0, 0x8CE50000, 0x2402FFFF)
        data[name_at:name_at + 10] = b"test.elf\0\0"
        for i in range(261):
            struct.pack_into("<IIHBB", data, symbol_at + i * 12, name_at, 0, i, 1, 0)
        struct.pack_into("<IIi", data, reloc_at, 0x80, (260 << 8) | 5, 0x12345678)
        return data

    def test_full_symbol_index_and_aligned_signed_addend(self):
        data = self.fixture()
        result = parse_snr2(data)
        relocation = result["relocations"][0]
        self.assertEqual(relocation["symbol_index"], 260)
        self.assertEqual(relocation["type"], 5)
        self.assertEqual(relocation["addend"], 0x12345678)
        reloc_at = struct.unpack_from("<I", data, 4)[0]
        struct.pack_into("<i", data, reloc_at + 8, -12345)
        self.assertEqual(parse_snr2(data)["relocations"][0]["addend"], -12345)

    def test_truncated_header_and_tables_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_snr2(b"SNR2")
        data = self.fixture()
        struct.pack_into("<I", data, 4, 0xFFFFFFF0)
        with self.assertRaises(ValueError):
            parse_snr2(data)

    def test_runtime_header_checks_every_field_at_multiple_bases(self):
        data = self.fixture()
        for base in (0x100000, 0x10FD800):
            observed = bytearray(data[:60])
            for index in (1, 3, 5, 6, 7, 8, 13, 14):
                value = struct.unpack_from("<I", observed, index * 4)[0]
                struct.pack_into("<I", observed, index * 4, value + base if value else 0)
            self.assertTrue(verify_runtime_header(data, observed, base)["all_fields_match"])
            observed[16] ^= 1
            self.assertFalse(verify_runtime_header(data, observed, base)["all_fields_match"])

    def test_runtime_header_rejects_truncation_and_address_overflow(self):
        data = self.fixture()
        with self.assertRaises(ValueError):
            verify_runtime_header(data, b"SNR2", 0x100000)
        with self.assertRaises(ValueError):
            verify_runtime_header(data, data[:60], 0xFFFFFFFF)

    def test_absent_symbol_and_out_of_range_patch_are_rejected(self):
        data = self.fixture()
        reloc_at = struct.unpack_from("<I", data, 4)[0]
        struct.pack_into("<I", data, reloc_at + 4, (261 << 8) | 5)
        with self.assertRaises(ValueError):
            parse_snr2(data)
        struct.pack_into("<I", data, reloc_at + 4, (260 << 8) | 5)
        struct.pack_into("<I", data, reloc_at, len(data) - 3)
        with self.assertRaises(ValueError):
            parse_snr2(data)

    def test_unterminated_name_and_file_size_mismatch_are_rejected(self):
        data = self.fixture()
        struct.pack_into("<I", data, 5 * 4, len(data) - 1)
        data[-1] = 65
        with self.assertRaises(ValueError):
            parse_snr2(data)
        data = self.fixture()
        struct.pack_into("<I", data, 11 * 4, len(data) + 1)
        with self.assertRaises(ValueError):
            parse_snr2(data)


if __name__ == "__main__":
    unittest.main()

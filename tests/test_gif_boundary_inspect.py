import tempfile
from pathlib import Path
import struct
import unittest
from tools.diagnostics.gif_boundary_inspect import HEADER, MAGIC, inspect, read_capture, replay


class GifBoundaryTests(unittest.TestCase):
    def test_packed_fragment_and_independent_path(self):
        low = 1 | (2 << 60)
        initial = (0, 0, low, 0xFF)
        first, _, _ = replay(bytes(16), initial)
        self.assertEqual(first, (0, 1, low, 0xFF))
        fence = struct.pack('<4Q', 0x1000000000008001, 0xE, 0, 0x61)
        other, _, _ = replay(fence, (0, 0, 0, 0))
        self.assertEqual(other[:2], (1, 0))
        final, _, _ = replay(bytes(16), first)
        self.assertEqual(final, (1, 0, low, 0xFF))

    def test_reglist_padding_does_not_become_a_tag(self):
        low = 1 | (1 << 58) | (3 << 60)
        payload = struct.pack('<6Q', low, 0xFFF, 1, 2, 3, 0xDEADBEEF)
        final, tags, _ = replay(payload, (0, 0, 0, 0))
        self.assertEqual(final, (1, 0, low, 0xFFF))
        self.assertEqual(len(tags), 1)

    def test_both_image_formats_continue_as_payload(self):
        for flg in (2, 3):
            low = 2 | (flg << 58)
            final, tags, _ = replay(bytes(16), (0, 0, low, 0))
            self.assertEqual(final, (1, 0, low, 0))
            self.assertEqual(tags, [])

    def test_file_identity_length_and_expected_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = struct.pack('<2Q', 0x8000, 0)
            values = (MAGIC, 1, 7, 2, 16, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x8000, 0)
            path = root / 'packet.giftrace'
            path.write_bytes(HEADER.pack(*values) + payload)
            self.assertTrue(inspect(root, 7, 1)['framing_verified'])
            with self.assertRaises(ValueError): inspect(root, 7, 2)
            path.write_bytes(HEADER.pack(*values) + payload[:-1])
            with self.assertRaises(ValueError): read_capture(path)
            path.write_bytes(b'x' * HEADER.size)
            with self.assertRaises(ValueError): read_capture(path)

    def test_reset_reinterprets_payload_and_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending = 3 | (1 << 60)
            payload = struct.pack('<2Q', 0x8000, 0)
            values = (MAGIC, 1, 9, 2, 16, 10, 0, 1,
                      1, 0, pending, 0xF, 3, 0, pending, 0xF, 0, 0, 0x8000, 0)
            (root / 'packet.giftrace').write_bytes(HEADER.pack(*values) + payload)
            report = inspect(root, 9, 1)
            self.assertTrue(report['framing_verified'])
            self.assertTrue(report['records'][0]['reset_changes_framing'])
            self.assertEqual(report['resync_transfers'], [9])


if __name__ == '__main__':
    unittest.main()

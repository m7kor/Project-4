from pathlib import Path
import struct
import tempfile
import unittest
from tools.diagnostics.vif_direct_inspect import HEADER, MAGIC, inspect, read


class VifDirectCaptureTests(unittest.TestCase):
    def fixture(self, root, command=0x50000001, hl=0):
        payload = struct.pack('<2Q', 0x8000, 0)
        source = struct.pack('<I', command) + payload
        h = (MAGIC, 1, 0, len(source), len(payload), len(source), 6130, len(source), 64, command, hl, 0x145, 0x1000, 0, 0x2000, 7)
        path = root / 'source.viftrace'
        path.write_bytes(HEADER.pack(*h) + source + payload)
        return path, payload

    def test_full_direct_is_preserved_with_completing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, expected = self.fixture(root)
            h, source, payload = read(path)
            self.assertEqual(payload, expected)
            self.assertEqual(source[4:], expected)
            self.assertEqual(h[8], 64)
            self.assertTrue(inspect(root, 1)['source_validated'])
            with self.assertRaises(ValueError): inspect(root, 2)

    def test_wrong_command_length_and_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.fixture(Path(directory), command=0x50000002)
            with self.assertRaises(ValueError): read(path)
            path, _ = self.fixture(Path(directory))
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError): read(path)

    def test_directhl_flag_must_match_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = self.fixture(root, command=0x51000001, hl=1)
            self.assertTrue(inspect(root, 1)['records'][0]['direct_hl'])
            path, _ = self.fixture(root, command=0x51000001, hl=0)
            with self.assertRaises(ValueError): read(path)

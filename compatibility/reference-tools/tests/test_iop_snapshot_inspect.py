import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location("iop_snapshot_inspect", Path(__file__).resolve().parents[1] / "tools/diagnostics/iop_snapshot_inspect.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IopSnapshotInspectTests(unittest.TestCase):
    def test_alias_reads_actual_word_at_physical_location(self):
        data = bytearray(2 * 1024 * 1024)
        struct.pack_into("<I", data, 0x1000, 0x03E00008)
        report = module.inspect(bytes(data), 0x80001000, 1)
        self.assertEqual(report["instructions"][0]["word"], "0x3e00008")
        self.assertEqual(report["instructions"][0]["decoded"]["mnem"], "jr")

    def test_truncated_overlong_and_unaligned_windows_are_rejected(self):
        data = bytes(2 * 1024 * 1024)
        for payload, start, words in ((data[:-1], 0, 1), (data, 3, 1),
                                      (data, len(data) - 4, 2), (data, 0, 513)):
            with self.assertRaises(ValueError):
                module.inspect(payload, start, words)

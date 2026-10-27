import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("trace_payload_identity",
    Path(__file__).resolve().parents[1] / "tools/diagnostics/trace_payload_identity.py")
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


class PayloadIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "archive.bin"
        self.source.write_bytes(b"outside!" + b"ABCDABCD\x00\x00\x00\x00")

    def trace(self, values):
        return {"observations": [{"line": number + 1, "memory_snapshots": {
            "mem_1000": value[:2].hex(), "mem_1002": value[2:].hex()}}
            for number, value in enumerate(values)], "entries_at_shared_cap": True}

    def run_compare(self, values):
        return identity.compare(self.trace(values), self.source, 8, 12,
                                ["mem_1000", "mem_1002"])

    def test_identity_and_ambiguous_offsets(self):
        result = self.run_compare([b"ABCD", b"ABCD"])
        sample = result["samples"][0]
        self.assertEqual(sample["relative_offsets"], [0, 4])
        self.assertEqual(sample["absolute_offsets"], [8, 12])
        self.assertEqual(sample["observations"], 2)
        self.assertTrue(result["trace_cap_reached"])

    def test_zero_never_proves_delivery(self):
        sample = self.run_compare([b"\0" * 4])["samples"][0]
        self.assertEqual(sample["classification"], "zero_unproven")
        self.assertEqual(sample["relative_offsets"], [])

    def test_unmatched_and_extent_isolation(self):
        self.assertEqual(self.run_compare([b"outs"])["samples"][0]["classification"], "unmatched")

    def test_rejects_invalid_bounds(self):
        for offset, size in [(-1, 1), (0, 0), (0, identity.MAX_EXTENT + 1), (19, 2)]:
            with self.assertRaises(ValueError):
                identity.compare(self.trace([b"ABCD"]), self.source, offset, size,
                                 ["mem_1000", "mem_1002"])

    def test_rejects_noncontiguous_or_pointer_samples(self):
        for keys in [["mem_1002", "mem_1000"], ["mem_1000", "mem_1000"], ["mem_1000_ptr"]]:
            with self.assertRaises(ValueError):
                identity.compare(self.trace([b"ABCD"]), self.source, 8, 12, keys)
        trace = self.trace([b"ABCD"])
        trace["observations"][0]["memory_snapshots"]["mem_1002"] = "434445"
        trace["observations"][0]["memory_snapshots"]["mem_1000"] = "41"
        with self.assertRaises(ValueError):
            identity.compare(trace, self.source, 8, 12, ["mem_1000", "mem_1002"])

    def test_rejects_changing_sample_width_and_bad_hex(self):
        for values in [[b"ABCD", b"ABCDE"]]:
            with self.assertRaises(ValueError):
                self.run_compare(values)
        trace = self.trace([b"ABCD"])
        trace["observations"][0]["memory_snapshots"]["mem_1000"] = "ZZ"
        with self.assertRaises(ValueError):
            identity.compare(trace, self.source, 8, 12, ["mem_1000", "mem_1002"])

    def test_missing_samples_remain_unproven(self):
        trace = self.trace([b"ABCD"])
        del trace["observations"][0]["memory_snapshots"]["mem_1002"]
        result = identity.compare(trace, self.source, 8, 12, ["mem_1000", "mem_1002"])
        self.assertEqual(result["missing_rows"], 1)
        self.assertEqual(result["samples"], [])


if __name__ == "__main__":
    unittest.main()

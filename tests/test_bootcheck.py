import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from ps2l import run as native_run

from ps2l.bootcheck import audit_capture, covered, disc_path


class BootEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "DATA").mkdir()
        self.archive = self.root / "DATA/BIO4DAT.AFS"
        self.archive.write_bytes(b"AFS\0" + struct.pack("<I", 2628) + bytes(22528 - 8))
        (self.root / "report.json").write_text(json.dumps({"elf": str(self.root / "game.elf"),
                                                        "timed_out": True}))
        self.search = "[CDVD search] path=\\DATA\\BIO4DAT.AFS;1 found=1 directory=0 lsn=25 size=22528\n"

    def read(self, lsn, count, result=1):
        return (f"[CDVD import] ordinal=63 pc=0x18e80 ra=0x153d4 a0={lsn:#x} "
                f"a1={count:#x} a2=0x122ac8 a3=0x197f0 v0={result:#x} handled=1\n")

    def audit(self, log):
        (self.root / "stderr.txt").write_text(log)
        return audit_capture(self.root)

    def test_retries_and_outside_reads_do_not_inflate_table_coverage(self):
        result = self.audit(self.search + self.read(25, 10) * 3 + self.read(50, 22))
        table = result["archives"][0]
        self.assertEqual(table["table_sectors"], 11)
        self.assertEqual(table["accepted_table_sectors"], 10)
        self.assertFalse(table["all_table_sectors_requested_and_accepted"])
        self.assertEqual(result["verdict"], "disc-read-acceptance-observed")

    def test_complete_acceptance_then_rejected_payload_is_failure(self):
        result = self.audit(self.search + self.read(25, 11) + self.read(36, 22, 0)
                            + "SRD: Drive Error (sceCdGetError = 0xfd)\n")
        self.assertTrue(result["archives"][0]["all_table_sectors_requested_and_accepted"])
        self.assertEqual(result["failed_reads"][0]["lsn"], 36)
        self.assertEqual(result["failed_reads"][0]["sectors"], 22)
        self.assertEqual(result["verdict"], "disc-read-failure-observed")
        self.assertEqual(result["game_compatibility"], "unverified")

    def test_rejected_reads_are_not_coverage(self):
        result = self.audit(self.search + self.read(25, 11, 0))
        self.assertEqual(result["archives"][0]["accepted_table_sectors"], 0)

    def test_missing_trace_does_not_claim_hang(self):
        self.assertEqual(self.audit("")["verdict"], "insufficient-disc-evidence")

    def test_corrupt_or_truncated_archive_has_explicit_error(self):
        self.archive.write_bytes(b"AFS\0" + struct.pack("<I", 0xffffffff))
        result = self.audit(self.search)
        self.assertEqual(len(result["source_errors"]), 1)
        self.assertEqual(result["archives"], [])

    def test_guest_paths_cannot_escape_root(self):
        for guest in ("\\..\\secret.afs", "C:\\secret.afs", "\\DATA\\..\\secret.afs"):
            with self.assertRaises(ValueError):
                disc_path(self.root, guest)

    def test_interval_union_handles_overlap_and_clipping(self):
        self.assertEqual(covered([(9, 12), (11, 14), (16, 19), (11, 12)], 10, 18), 6)

    def test_unhandled_import_cannot_count_as_accepted(self):
        result = self.audit(self.search + self.read(25, 11).replace("handled=1", "handled=0"))
        self.assertEqual(result["trace_rows"], 0)
        self.assertEqual(result["archives"][0]["accepted_table_sectors"], 0)

    def test_run_enables_trace_and_retains_audit_of_rejected_read(self):
        elf, runner = self.root / "game.elf", self.root / "runner.exe"
        elf.write_bytes(b"fixture")
        runner.write_bytes(b"fixture")

        def execute(*args, **kwargs):
            self.assertEqual(kwargs["env"]["PS2X_TRACE_CDVD"], "1")
            kwargs["stderr"].write(self.read(36, 22, 0).encode())
            process = MagicMock()
            process.__enter__.return_value = process
            process.pid = 123
            process.returncode = 0
            process.wait.return_value = 0
            return process

        with patch.object(native_run.subprocess, "Popen", side_effect=execute):
            code = native_run.main([str(elf), "--runner", str(runner), "--out",
                                    str(self.root / "captures"), "--trace-disc"])
        self.assertEqual(code, 1)
        capture = next((self.root / "captures").iterdir())
        report = json.loads((capture / "report.json").read_text())
        self.assertEqual(report["result"], "fault-observed")
        self.assertEqual(report["exit_code"], 0)  # original process status is preserved
        audit = json.loads((capture / "boot-audit.json").read_text())
        self.assertEqual(audit["failed_reads"][0]["sectors"], 22)

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("gs_transfer_audit", Path(__file__).resolve().parents[1] / "tools/diagnostics/gs_transfer_audit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TransferAuditTests(unittest.TestCase):
    def line(self, size, prefix):
        return f"[gs:transfer] stage=input dbp=13440 dbw=1 dpsm=0 direction=0 x=0 y=0 rrw=16 rrh=1 copied=0 total=16 bytes={size} prefix={prefix}"

    def test_complete_and_bounded_prefixes_are_distinct(self):
        result = module.audit(self.line(4, "00010203") + "\n" + self.line(1024, "00" * 512))
        self.assertTrue(result["usable"])
        self.assertTrue(result["events"][0]["payload_complete"])
        self.assertFalse(result["events"][1]["payload_complete"])

    def test_missing_or_truncated_evidence_cannot_pass(self):
        self.assertFalse(module.audit("")["usable"])
        self.assertFalse(module.audit(self.line(4, "00"))["usable"])
        self.assertFalse(module.audit(self.line(4, "zz"))["usable"])
        self.assertFalse(module.audit(self.line(4, "00010203").replace("dbp=13440", "dbp=99999"))["usable"])

    def test_character_or_invalid_register_fields_cannot_pass(self):
        line = self.line(4, "00010203")
        for old, new in (("dbw=1", "dbw=\x01"), ("dbw=1", "dbw=64"),
                         ("direction=0", "direction=4"), ("rrw=16", "rrw=4096"),
                         ("copied=0", "copied=-1")):
            with self.subTest(field=new):
                self.assertFalse(module.audit(line.replace(old, new))["usable"])

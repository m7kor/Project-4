import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("rpc_wait_audit", Path(__file__).resolve().parents[1] / "tools/diagnostics/rpc_wait_audit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RpcWaitAuditTests(unittest.TestCase):
    def test_yield_is_not_a_completed_return_and_busy_bytes_are_preserved(self):
        payload = bytearray(64)
        payload[8:11] = b"\x01\x01\x00"
        line = f"[EE call leave] target=0x100 source=0x200 pc=0x208 v0=0x0 mem_300={payload.hex()}\n"
        report = module.summarize([line, line.replace("pc=0x208", "pc=0x444")], 0x100, 0x200, 0x208, 0x300, [8, 9, 10])
        self.assertTrue(report["usable"])
        self.assertEqual(report["counts"]["completed_leaf_returns"], 1)
        self.assertEqual(report["counts"]["nonreturn_leaves"], 1)
        self.assertEqual(report["reply_flag_patterns"], {"01/01/00": 1})

    def test_empty_and_truncated_observations_never_pass(self):
        self.assertFalse(module.summarize([], 1, 2, 3, 4, [8])["usable"])
        line = "[EE call leave] target=0x1 source=0x2 pc=0x3 v0=0x0 mem_4=0100"
        self.assertFalse(module.summarize([line], 1, 2, 3, 4, [8])["usable"])
        with self.assertRaises(ValueError):
            module.summarize([], 1, 2, 3, 4, [64])

import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


def load_tool(name):
    path = Path(__file__).resolve().parents[1] / "tools/diagnostics" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jobs = load_tool("ee_job_trace")
polls = load_tool("ee_file_poll_trace")


class EeTraceReportTests(unittest.TestCase):
    def summarize(self, module, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stderr.txt"
            path.write_text(text, encoding="utf-8")
            return module.summarize(path)

    def test_other_targets_can_exhaust_shared_budget(self):
        header = bytearray(24)
        struct.pack_into("<I", header, 12, 172)
        trace = "[EE call enter] target=0x256010 source=0x1b5af0 a0=0x1 mem_451680_at_0_resolved_455578=" + header.hex() + "\n"
        trace += "[EE call enter] target=0x29cc60 source=0x256074 a0=0xac\n" * 255
        report = self.summarize(jobs, trace)
        self.assertEqual(report["observed_entries"], 1)
        self.assertEqual(report["shared_observed_entries"], 256)
        self.assertTrue(report["entries_at_shared_cap"])
        self.assertEqual(report["observations"][0]["reply_semaphore_at_12"], 172)

    def test_leave_lines_do_not_consume_entry_budget(self):
        trace = "[EE call enter] target=0x29cc60 source=0x256074 a0=0xac\n"
        trace += "[EE call leave] target=0x29cc60 source=0x256074 returned=1\n" * 256
        report = self.summarize(jobs, trace)
        self.assertEqual(report["shared_observed_entries"], 1)
        self.assertFalse(report["entries_at_shared_cap"])

    def test_poll_yield_keeps_state_and_does_not_invent_completion(self):
        trace = "[EE trace:armed] target=0x206280 source=0x1189da0\n"
        trace += "[EE call leave] target=0x1b4618 source=0x1b5b10 pc=0x16c6d0 v0=0x30 returned=0 a0=0x41c144 bytes0=010000400103\n"
        report = self.summarize(polls, trace)
        self.assertEqual(len(report["arm_events"]), 1)
        row = report["observations"][0]
        self.assertEqual(row["returned"], 0)
        self.assertEqual(row["object_header"]["word_0"], "0x40000001")
        self.assertEqual(row["object_header"]["type_at_4"], 1)
        self.assertEqual(row["object_header"]["state_at_5"], 3)
        self.assertNotIn("completed", row)

    def test_short_snapshot_is_not_decoded_as_a_file_header(self):
        report = self.summarize(polls, "[EE call enter] target=0x1b4618 a0=0x41c144 bytes0=010000\n")
        self.assertNotIn("object_header", report["observations"][0])

    def test_odd_hex_is_reported_without_losing_the_call(self):
        report = self.summarize(polls, "[EE call enter] target=0x1b4618 a0=0x41c144 bytes0=abc\n")
        self.assertEqual(report["malformed_snapshots"], 1)
        self.assertEqual(report["observed_entries"], 1)
        self.assertNotIn("object_header", report["observations"][0])

    def test_event_payload_and_indirect_memory_are_preserved_raw(self):
        trace = "[EE call enter] target=0x2068d8 source=0x2064e0 a1=0x131a8f0 bytes1=6576656e74000000 mem_4243d0_at_0_resolved_1314430=01000000\n"
        report = self.summarize(polls, trace)
        row = report["observations"][0]
        self.assertEqual(row["argument_snapshots"]["1"], "6576656e74000000")
        self.assertEqual(row["memory_snapshots"]["mem_4243d0_at_0_resolved_1314430"], "01000000")
        self.assertNotIn("object_header", row)

    def test_invalid_memory_snapshot_is_counted_without_inventing_bytes(self):
        report = self.summarize(polls, "[EE call enter] target=0x205e38 mem_4243d0=abc\n")
        self.assertEqual(report["malformed_snapshots"], 1)
        self.assertEqual(report["observations"][0]["memory_snapshots"], {})

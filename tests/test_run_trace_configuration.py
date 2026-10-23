from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ps2l.run import main, validate_trace_environment


class TraceConfigurationTests(unittest.TestCase):
    def test_ipu_trace_records_presence_without_environment_values(self):
        self.assertFalse(validate_trace_environment({})["ipu_mmio_enabled"])
        result = validate_trace_environment({"PS2X_TRACE_IPU": "0", "PRIVATE_VALUE": "secret"})
        self.assertTrue(result["ipu_mmio_enabled"])
        self.assertNotIn("secret", str(result))

    def test_records_actual_windows_and_presence_flags(self):
        result = validate_trace_environment({"PS2X_TRACE_EE": "0", "PS2X_TRACE_EE_CHANGES": "1",
            "PS2X_TRACE_CALL_MEMORY": "0xde2140,0x455948:0x40",
            "PS2X_TRACE_CALLS": "0x2cf160,3070464", "UNRELATED_SECRET": "hidden"})
        self.assertTrue(result["ee_dispatch_enabled"])
        self.assertTrue(result["ee_changes_enabled"])
        windows = result["selectors"]["PS2X_TRACE_CALL_MEMORY"]
        self.assertEqual(windows[0], {"base": 0xde2140, "indirect": False, "offset": 0, "bytes": 64})
        self.assertEqual(windows[1]["offset"], 0x40)
        self.assertTrue(windows[1]["indirect"])
        self.assertNotIn("hidden", str(result))

    def test_rejects_silent_selector_truncation(self):
        for count in (17, 94):
            with self.assertRaisesRegex(ValueError, "at most 16"):
                validate_trace_environment({"PS2X_TRACE_CALLS": ",".join(["0x1000"] * count)})
        self.assertEqual(len(validate_trace_environment({"PS2X_TRACE_CALLS":
            ",".join(["0x1000"] * 16)})["selectors"]["PS2X_TRACE_CALLS"]), 16)

    def test_rejects_partial_or_ambiguous_numbers(self):
        for value in ("0x1000,", "0x1000junk", "010", "-4", "0x100000000", "0x1001", "0x1000:4"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_trace_environment({"PS2X_TRACE_CALLS": value})

    def test_ram_and_pointer_window_bounds(self):
        for value in ("0xffc", "0x1ffffc4", "0x2000000:0", "0x1000:", "0x1000:0x100000000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_trace_environment({"PS2X_TRACE_CALL_MEMORY": value})
        validate_trace_environment({"PS2X_TRACE_CALL_MEMORY": "0x1ffffc0,0x1fffffc:0xffffffff"})
        with self.assertRaises(ValueError):
            validate_trace_environment({"PS2X_TRACE_WORDS": "0x2000000"})
        validate_trace_environment({"PS2X_TRACE_WORDS": "0,0x1fffffc"})

    def test_empty_and_disabled_configuration(self):
        result = validate_trace_environment({"PS2X_TRACE_CALLS": "", "PS2X_TRACE_EE_CHANGES": "1"})
        self.assertFalse(result["ee_changes_enabled"])
        self.assertEqual(result["selectors"]["PS2X_TRACE_CALLS"], [])

    def test_invalid_plan_rejected_before_launch_or_capture_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            elf, runner, output = root / "game.elf", root / "runner.exe", root / "captures"
            elf.write_bytes(b"test")
            runner.write_bytes(b"test")
            with patch.dict("os.environ", {"PS2X_TRACE_CALLS": ",".join(["0x1000"] * 94)}, clear=True), \
                    patch("ps2l.run.subprocess.Popen") as launch, redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as stopped:
                main([str(elf), "--runner", str(runner), "--out", str(output), "--stop-on-fault"])
            self.assertEqual(stopped.exception.code, 2)
            launch.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

"""Regression tests for build orchestration and retained failure evidence."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ps2l"))
import build
from agent import Runner
import run as native_run


class BuildTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / "artifacts/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / "core/out/build"
        self.generated = self.root / "recomp/generated/SLUS_211.34"
        self.generated.mkdir(parents=True)
        (self.generated / "a.cpp").write_text("int a;", encoding="utf-8")
        for name, value in {"ROOT": self.root, "CORE": self.root / "core", "BUILD": self.build,
                            "GENERATED": self.generated,
                            "STAMP": self.build / "stamp.json"}.items():
            p = patch.object(build, name, value)
            p.start()
            self.addCleanup(p.stop)

    def existing(self):
        self.build.mkdir(parents=True)
        (self.build / "CMakeCache.txt").write_text(
            f"PS2X_ENABLE_AGRESSIVE_LOGS:BOOL=OFF\nPS2X_RUNNER_SRC_DIR:PATH={self.generated}\nFEATURE:STRING=old\n",
            encoding="utf-8")
        build.STAMP.write_text(json.dumps(build._generated_stamp()), encoding="utf-8")

    def invoke(self, args, configure=0, result=0):
        def run(command, label):
            if label == "build" and result == 0:
                exe = self.build / "ps2xRuntime" / (build.TARGET + (".exe" if os.name == "nt" else ""))
                exe.parent.mkdir(parents=True, exist_ok=True)
                exe.touch()
            return configure if label == "configure" else result
        with patch.object(build, "_run", side_effect=run) as calls, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = build.main(args)
        return code, calls.call_args_list

    def test_fresh_build_configures_then_builds(self):
        code, calls = self.invoke([])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[1] for c in calls], ["configure", "build"])
        self.assertTrue(any("PS2X_RUNNER_SRC_DIR=" in f for f in calls[0].args[0]))

    def test_failed_configure_does_not_build_or_stamp(self):
        code, calls = self.invoke([], configure=7)
        self.assertEqual(code, 7)
        self.assertEqual(len(calls), 1)
        self.assertFalse(build.STAMP.exists())

    def test_explicit_non_boolean_flag_reconfigures(self):
        self.existing()
        code, calls = self.invoke(["--configure-flag", "FEATURE:STRING=new"])
        self.assertEqual(code, 0)
        self.assertIn("-DFEATURE:STRING=new", calls[0].args[0])
        self.assertEqual(calls[0].args[1], "configure")

    def test_same_size_rename_changes_membership(self):
        old = build._generated_stamp()
        (self.generated / "a.cpp").rename(self.generated / "b.cpp")
        self.assertNotEqual(old, build._generated_stamp())

    def test_content_edit_does_not_reconfigure(self):
        self.existing()
        (self.generated / "a.cpp").write_text("int changed;", encoding="utf-8")
        code, calls = self.invoke([])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[1] for c in calls], ["build"])

    def test_lock_is_preserved(self):
        self.existing()
        lock = self.build / ".ninja_lock"
        lock.write_text("owned", encoding="utf-8")
        self.invoke([])
        self.assertEqual(lock.read_text(), "owned")

    def test_build_failure_propagates(self):
        self.existing()
        self.assertEqual(self.invoke([], result=9)[0], 9)

    def test_malformed_stamp_is_replaced(self):
        self.existing()
        build.STAMP.write_text("null", encoding="utf-8")
        code, calls = self.invoke([])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0].args[1], "configure")

    def test_missing_executable_is_failure(self):
        self.existing()
        with patch.object(build, "_run", return_value=0), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build.main([]), 1)

    def test_separate_game_build_uses_its_own_sources(self):
        other = self.root / "other-game"
        other.mkdir()
        (other / "b.cpp").write_text("int b;", encoding="utf-8")
        code, calls = self.invoke(["--build-dir", str(self.build), "--generated-dir", str(other)])
        self.assertEqual(code, 0)
        self.assertIn(f"-DPS2X_RUNNER_SRC_DIR={other.as_posix()}", calls[0].args[0])
        self.assertEqual(json.loads(build.STAMP.read_text())["dir"], str(other.resolve()))


class CaptureTests(unittest.TestCase):
    def test_timeout_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "capture.txt"
            with patch("agent.subprocess.run", side_effect=subprocess.TimeoutExpired("guest", 1, stderr=b"guest fault")):
                text, code = Runner(("guest",), 1, log).capture()
            self.assertEqual(code, 124)
            self.assertEqual(log.read_text(encoding="utf-8"), text)
            self.assertIn("guest fault", text)


class NativeCaptureTests(unittest.TestCase):
    def capture(self, script, timeout=5, diagnostics=False):
        scratch = Path(__file__).resolve().parents[1] / "artifacts/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            guest = root / "synthetic.py"
            guest.write_text(script, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = native_run.main([str(guest), "--runner", sys.executable,
                                        "--timeout", str(timeout), "--out", str(root / "runs"),
                                        *(["--diagnostics"] if diagnostics else [])])
            report = json.loads(next((root / "runs").glob("*/report.json")).read_text())
        return code, report

    def test_clean_exit_does_not_certify_game(self):
        code, report = self.capture("print('finished')")
        self.assertEqual(code, 0)
        self.assertEqual(report["game_compatibility"], "unverified")
        self.assertEqual(report["result"], "process-exited")

    def test_diagnostics_without_capture_directory_remain_reportable(self):
        code, report = self.capture("print('no capture produced')", diagnostics=True)
        self.assertEqual(code, 0)
        self.assertFalse(report['diagnostics']['frame_audit']['complete'])
        self.assertEqual(report['diagnostics']['frame_audit']['decoded_frames'], 0)
        self.assertEqual(report['game_compatibility'], 'unverified')

    def test_diagnostic_capture_survives_truncated_final_snapshot(self):
        code, report = self.capture("""import os, pathlib
directory = pathlib.Path(os.environ['PS2X_CAPTURE_DIR'])
directory.mkdir()
(directory / 'state.jsonl').write_text('{"pc":4096,"host_frame":false,"gs_writes":0}\\n{"pc":')
""", diagnostics=True)
        self.assertEqual(code, 0)
        self.assertEqual(report['diagnostics']['samples'], 1)
        self.assertEqual(report['diagnostics']['malformed_rows'], 1)
        self.assertEqual(report['diagnostics']['last_state']['pc'], 4096)
        self.assertFalse(report['diagnostics']['host_frame_observed'])
        self.assertEqual(report['diagnostics']['captured_frame_files'], [])
        self.assertEqual(report['game_compatibility'], 'unverified')

    def test_fault_with_zero_exit_is_failure(self):
        code, report = self.capture("import sys; print('[guest-branch:missing-target] target=0x1234', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report["result"], "fault-observed")
        self.assertEqual(report["fault_counts"]["[guest-branch:missing-target]"], 1)

    def test_vulkan_device_loss_with_clean_exit_is_failure(self):
        code, report = self.capture("import sys; print('[ERROR]: vkQueueSubmit2 failed (code: -4).', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['result'], 'fault-observed')
        self.assertEqual(report['fault_counts']['[ERROR]: vkQueueSubmit2 failed (code: -4)'], 1)

    def test_successful_shader_compile_warning_is_not_device_failure(self):
        code, report = self.capture("import sys; print('[WARN]: Stalled compile (compute): success: yes.', file=sys.stderr)")
        self.assertEqual(code, 0)
        self.assertEqual(report['fault_counts'], {})

    def test_native_timeout_is_recorded(self):
        code, report = self.capture("import time; time.sleep(10)", timeout=0.2)
        self.assertEqual(code, 124)
        self.assertTrue(report["timed_out"])

    def test_native_loader_rejection_is_failure_even_with_zero_process_exit(self):
        code, report = self.capture("import sys; print('[native-module:binding-rejected] reason=header mismatch', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['result'], 'fault-observed')
        self.assertEqual(report['fault_counts']['[native-module:binding-rejected]'], 1)

    def test_caught_guest_exception_with_zero_exit_is_failure(self):
        code, report = self.capture("import sys; print('Error during program execution: Unhandled SPECIAL instruction', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report["result"], "fault-observed")

    def test_iop_scheduler_exception_with_zero_exit_is_failure(self):
        code, report = self.capture("import sys; print('[IOP runtime exception] invalid native SPU2 DMA RAM range', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['fault_counts']['[IOP runtime exception]'], 1)

    def test_delayed_rpc_delivery_failure_is_reported_as_fault(self):
        code, report = self.capture("import sys; print('[SIF RPC timing delivery failed] receive buffer unavailable', file=sys.stderr)")
        self.assertNotEqual(code, 0)
        self.assertEqual(report['fault_counts']['[SIF RPC timing delivery failed]'], 1)

    def test_unsupported_rpc_is_reported_as_fault(self):
        code, report = self.capture("import sys; print('[SIF RPC unsupported] sid=0x80000593 function=0x1', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['fault_counts']['[SIF RPC unsupported]'], 1)

    def test_guest_initialization_failure_is_not_a_clean_exit(self):
        code, report = self.capture("import sys; print('PS2RNA: E01112903: Failed, sceSifAllocIopHeap(266304)', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['result'], 'fault-observed')

    def test_assertion_message_is_a_fault_even_with_clean_process_exit(self):
        code, report = self.capture("import sys; print('assertion eflSifRpc.c:222 failed: priority', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['result'], 'fault-observed')

    def test_disc_read_error_is_observed_even_with_clean_process_exit(self):
        code, report = self.capture("import sys; print('SRD: Drive Error (sceCdGetError = 0xfe)', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['result'], 'fault-observed')
        self.assertEqual(report['fault_counts']['Drive Error (sceCdGetError = 0xfe)'], 1)


    def test_rejected_iop_module_is_reported_as_fault(self):
        code, report = self.capture("import sys; print('[IOP module buffer rejected] ptr=0x1000', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['fault_counts']['[IOP module buffer rejected]'], 1)

    def test_failed_module_start_and_arena_exhaustion_are_faults(self):
        code, report = self.capture("import sys; print('[IOP module start rejected] id=4', file=sys.stderr); print('[IOP] module arena exhausted', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['fault_counts']['[IOP module start rejected]'], 1)
        self.assertEqual(report['fault_counts']['[IOP] module arena exhausted'], 1)

    def test_iop_failure_diagnostics_are_reported_as_faults(self):
        code, report = self.capture("import sys; print('[IOP call incomplete] pc=0x80', file=sys.stderr); print('[IOP] unhandled import ioman:4', file=sys.stderr)")
        self.assertEqual(code, 1)
        self.assertEqual(report['fault_counts']['[IOP call incomplete]'], 1)
        self.assertEqual(report['fault_counts']['[IOP] unhandled import'], 1)

    def test_missing_runner_replaces_stale_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "capture.txt"
            log.write_text("old success", encoding="utf-8")
            with patch("agent.subprocess.run", side_effect=FileNotFoundError):
                text, code = Runner(("absent",), 1, log).capture()
            self.assertEqual(code, 127)
            self.assertEqual(log.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()

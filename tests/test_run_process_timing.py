"""Exercise real child creation, normal exit, timeout and diagnostic termination."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from ps2l.run import main


class ProcessTimingTests(unittest.TestCase):
    def capture(self, script, expected, *options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'child.py'
            source.write_text(script, encoding='utf-8')
            before = time.time_ns()
            code = main([str(source), '--runner', sys.executable, '--out', str(root / 'runs'), *options])
            after = time.time_ns()
            self.assertEqual(code, expected)
            report = json.loads(next((root / 'runs').glob('*/report.json')).read_text(encoding='utf-8'))
            requested = report['process_spawn_requested_unix_ns']
            started = report['process_start_observed_unix_ns']
            ended = report['process_exit_observed_unix_ns']
            self.assertTrue(before <= requested <= started <= ended <= after)
            self.assertGreater(report['process_pid'], 0)
            return report

    def test_ordinary_exit(self):
        report = self.capture('raise SystemExit(7)', 7, '--timeout', '5')
        self.assertFalse(report['process_exit_forced'])
        self.assertFalse(report['timed_out'])
        self.assertEqual(report['process_returncode'], 7)

    def test_timeout_without_fault_monitor(self):
        report = self.capture('import time; time.sleep(10)', 124, '--timeout', '.2')
        self.assertTrue(report['process_exit_forced'])
        self.assertTrue(report['timed_out'])
        self.assertIsNotNone(report['process_returncode'])

    def test_fault_monitor_stops_real_child(self):
        report = self.capture("import os,time; os.write(2,b'[guest-branch:missing-target]\\n'); time.sleep(10)",
                              1, '--timeout', '5', '--stop-on-fault')
        self.assertTrue(report['process_exit_forced'])
        self.assertTrue(report['stopped_on_fault'])
        self.assertFalse(report['timed_out'])


if __name__ == '__main__':
    unittest.main()

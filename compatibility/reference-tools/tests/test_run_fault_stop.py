import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ps2l.run import wait_for_fault_or_exit


class FaultStopTests(unittest.TestCase):
    def capture(self, script, timeout):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stderr.txt'
            with path.open('wb') as log:
                with subprocess.Popen([sys.executable, '-c', script], stderr=log,
                                      stdout=subprocess.DEVNULL) as process:
                    started = time.monotonic()
                    result = wait_for_fault_or_exit(process, path, timeout)
                    elapsed = time.monotonic() - started
                    self.assertIsNotNone(process.poll(), 'Child must be reaped')
            return result, elapsed, path.read_bytes()

    def test_split_fault_after_large_log_stops_and_preserves_evidence(self):
        result, elapsed, evidence = self.capture(
            "import os,time;os.write(2,b'x'*65530+b'[guest-branch:miss');"
            "time.sleep(.1);os.write(2,b'ing-target] pc=0x1234\\n');time.sleep(10)", 5)
        self.assertEqual(result, (1, False, True))
        self.assertLess(elapsed, 5)
        self.assertIn(b'[guest-branch:missing-target] pc=0x1234', evidence)

    def test_ordinary_diagnostic_does_not_stop_process(self):
        result, _, evidence = self.capture(
            "import os,sys;os.write(2,b'[native-module:loaded] name=test\\n');sys.exit(7)", 5)
        self.assertEqual(result, (7, False, False))
        self.assertIn(b'[native-module:loaded]', evidence)

    def test_deadline_stops_silent_child_and_reports_timeout(self):
        result, elapsed, _ = self.capture('import time;time.sleep(10)', .2)
        self.assertEqual(result, (124, True, False))
        self.assertLess(elapsed, 5)

    def test_untranslated_thread_entry_is_a_fault(self):
        result, _, evidence = self.capture(
            "import os,time;os.write(2,b'[EE thread:missing-entry] id=31 entry=0x1189ca0\\n');time.sleep(10)", 5)
        self.assertEqual(result, (1, False, True))
        self.assertIn(b'entry=0x1189ca0', evidence)


if __name__ == '__main__':
    unittest.main()

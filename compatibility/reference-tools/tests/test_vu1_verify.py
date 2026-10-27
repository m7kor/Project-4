import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('vu1_verify', Path(__file__).resolve().parents[1] / 'tools/diagnostics/vu1_verify.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class Vu1VerifyTests(unittest.TestCase):
    def output(self, compiled=0, status=False, digest='0123456789abcdef'):
        return f'snapshots=2 vu1_cycles=100 best=0.001 s ns/cycle=10.0 result={digest}\ncompiled={compiled}/2 status_hashed={"yes" if status else "no"}\n'

    def run_report(self, mismatch=False, exact_compiled=False):
        outputs = [self.output(2), self.output(), self.output(digest='1111111111111111' if mismatch else '0123456789abcdef'),
                   self.output(2 if exact_compiled else 0, True), self.output(status=True)]
        with patch.object(verify.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, text, '') for text in outputs]) as run:
            report = verify.verify(Path('bench'), Path('snapshots'))
            self.assertNotIn('--no-status', run.call_args_list[-1].args[0])
            self.assertIn('--no-status', run.call_args_list[0].args[0])
            return report

    def test_matching_modes(self):
        self.assertTrue(self.run_report()['passed'])

    def test_mismatch_fails(self):
        self.assertFalse(self.run_report(mismatch=True)['passed'])

    def test_exact_mode_must_fall_back(self):
        self.assertFalse(self.run_report(exact_compiled=True)['passed'])

    def test_missing_and_invalid_results_fail(self):
        for output in ('', self.output(3), self.output().replace('cycles=100', 'cycles=0')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                verify.parse_result(output)

    def test_benchmark_failure_is_not_a_matching_empty_hash(self):
        with patch.object(verify.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'invalid snapshot')):
            with self.assertRaisesRegex(ValueError, 'invalid snapshot'):
                verify.verify(Path('bench'), Path('snapshots'))

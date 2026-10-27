import json
from pathlib import Path
import sys
import tempfile
import unittest

from tools.diagnostics.toolchain_check import run_step


class ToolchainCheckTests(unittest.TestCase):
    def execute(self, code, content=None, timeout=5):
        with tempfile.TemporaryDirectory() as folder:
            logs = Path(folder)
            expected = logs / 'evidence.json'
            if content is not None:
                code = ('import sys;from pathlib import Path;'
                        f'Path(sys.argv[1]).write_text({content!r},encoding="utf-8");' + code)
            return run_step([sys.executable, '-c', code, str(expected)], expected, 'accepted', logs, 'test', timeout)

    def test_zero_exit_without_evidence_rejected(self):
        self.assertEqual(self.execute('pass')['status'], 'failed')

    def test_false_invalid_or_non_boolean_acceptance_rejected(self):
        for content in ('not-json', '{}', '[]', 'null', '{"accepted":false}', '{"accepted":1}'):
            self.assertEqual(self.execute('pass', content)['status'], 'failed')

    def test_process_failure_cannot_use_successful_evidence(self):
        self.assertEqual(self.execute('raise SystemExit(7)', '{"accepted":true}')['exit_code'], 7)

    def test_timeout_not_success(self):
        result = self.execute('import time;time.sleep(5)', '{"accepted":true}', timeout=0.1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Timed out', result['error'])

    def test_completed_evidence_accepted(self):
        self.assertEqual(self.execute('pass', json.dumps({'accepted': True}))['status'], 'passed')

    def test_stale_evidence_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = Path(folder)
            evidence = logs / 'evidence.json'
            evidence.write_text('{"accepted":true}', encoding='utf-8')
            result = run_step([sys.executable, '-c', 'raise SystemExit(7)'],
                              evidence, 'accepted', logs, 'test')
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('exit_code', result)
            self.assertEqual(evidence.read_text(), '{"accepted":true}')

    def test_nested_tool_logs_do_not_collide(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = Path(folder)
            evidence = logs / 'test.json'
            code = ('import sys;from pathlib import Path;p=Path(sys.argv[1]);'
                    'p.with_suffix(".stderr.log").write_text("child log");'
                    'p.write_text(\'{"accepted":true}\')')
            result = run_step([sys.executable, '-c', code, str(evidence)],
                              evidence, 'accepted', logs, 'test')
            self.assertEqual(result['status'], 'passed')
            self.assertEqual((logs / 'test.stderr.log').read_text(), 'child log')
            self.assertTrue((logs / 'test.process.stderr.log').exists())


if __name__ == '__main__':
    unittest.main()

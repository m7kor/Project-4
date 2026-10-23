import struct
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tools.diagnostics.snr2_body_cfg import audit_body


class BodyBoundaryTests(unittest.TestCase):
    def image(self, words):
        return struct.pack('<' + 'I' * len(words), *words)

    def test_return_excludes_unrelated_next_prologue(self):
        data = self.image([0x03e00008, 0, 0x27bdfff0, 0xffbf0000])
        report = audit_body(data, 0, len(data))
        self.assertEqual(report['unreachable_nonzero_words'], [8, 12])

    def test_conditional_paths_and_both_delay_slots_are_reachable(self):
        data = self.image([0x10800003, 0, 0x03e00008, 0, 0x03e00008, 0])
        report = audit_body(data, 0, len(data))
        self.assertEqual(report['reachable_words'], 6)
        self.assertEqual(report['unreachable_nonzero_words'], [])
        self.assertEqual(report['boundary_exits'], [])

    def test_missing_delay_and_indirect_jumps_require_review(self):
        self.assertTrue(audit_body(self.image([0x03e00008]), 0, 4)['invalid_delay_slots'])
        report = audit_body(self.image([0x00400008, 0]), 0, 8)
        self.assertEqual(report['unresolved_indirect_jumps'], [0])

    def test_cli_rejects_plan_for_different_image_without_replacing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module, plan, report = root/'module.snr2', root/'plan.json', root/'report.json'
            module.write_bytes(self.image([0x03e00008, 0]))
            plan.write_text(json.dumps({'schema': 1, 'identity': '0'*64,
                                       'bodies': [{'start': 0, 'end': 8}]}))
            report.write_bytes(b'keep previous report')
            result = subprocess.run([sys.executable, '-m', 'tools.diagnostics.snr2_body_cfg',
                                     str(module), '--plan', str(plan), '--out', str(report)],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b'Plan does not match', result.stderr)
            self.assertEqual(report.read_bytes(), b'keep previous report')


if __name__ == '__main__':
    unittest.main()

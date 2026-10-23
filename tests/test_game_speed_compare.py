"""Performance comparisons must expose known background measurement work."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.diagnostics.game_speed_compare import measure, validate_workload


class GameSpeedCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'diagnostics').mkdir()
        rows = [{'tick': i * 600, 'elapsed_seconds': i * 10,
                 'ee_vsync_tick': i * 600} for i in range(4)]
        (self.root / 'diagnostics/state.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        (self.root / 'report.json').write_text(json.dumps({
            'runner_sha256': 'a' * 64, 'elf_sha256': 'b' * 64}), encoding='utf-8')
        (self.root / 'stderr.txt').write_text('(super-sampling x1)', encoding='utf-8')
        self.identity = {'run': str(self.root), 'user_card_before': 'unchanged',
                         'user_card_after': 'unchanged', 'pad_sha256': 'c' * 64,
                         'capture_every_host_ticks': 300}

    def measured(self, **updates):
        path = self.root / 'identity.json'
        path.write_text(json.dumps(dict(self.identity, **updates)), encoding='utf-8')
        return measure(path, 100, 1700)

    def test_legacy_identity_explicitly_has_no_reported_external_activity(self):
        result = self.measured()
        self.assertEqual(result['instrumentation']['external_activity'], [])
        validate_workload(result, result)

    def test_sampling_or_build_activity_rejects_unqualified_comparison(self):
        baseline = self.measured(external_activity=['sampling', 'incremental build'])
        candidate = self.measured()
        with self.assertRaisesRegex(ValueError, 'Instrumentation differs'):
            validate_workload(baseline, candidate)

    def test_explicit_diagnostic_override_keeps_activity_visible(self):
        baseline = self.measured(external_activity=['sampling'])
        candidate = self.measured()
        validate_workload(baseline, candidate, allow_instrumentation_differences=True)
        self.assertEqual(baseline['instrumentation']['external_activity'], ['sampling'])
        self.assertNotEqual(baseline['instrumentation'], candidate['instrumentation'])

    def test_malformed_external_activity_is_rejected(self):
        for value in ('sampling', None, [False], ['']):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'External activity'):
                self.measured(external_activity=value)


if __name__ == '__main__':
    unittest.main()

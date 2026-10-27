import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.diagnostics.vu1_call_profile import summarize


META = {'kind': 'meta', 'schema': 1, 'clock': 'steady_clock_ns', 'from_ee': 10, 'interval_ee': 30}
WINDOW = {'kind': 'window', 'index': 0, 'first_ee': 10, 'last_ee': 20,
          'groups': 2, 'calls': 5, 'cycles': 100, 'nanoseconds': 1000}
GROUP = {'kind': 'group', 'window': 0, 'code_fnv1a64': '0123456789abcdef', 'start_pc': 8,
         'resume': False, 'calls': 2, 'cycles': 40, 'nanoseconds': 400,
         'max_nanoseconds': 300, 'compiled_calls': 2}
OTHER = dict(GROUP, code_fnv1a64='fedcba9876543210', calls=3, cycles=60, nanoseconds=600,
             compiled_calls=0, resume=True)
END = {'kind': 'end', 'index': 0}


class Vu1CallProfileTests(unittest.TestCase):
    def analyze(self, records, tail='', **options):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.jsonl'
            path.write_text(''.join(json.dumps(row) + '\n' for row in records) + tail, encoding='utf-8')
            return summarize(path, **options)

    def valid(self):
        return copy.deepcopy([META, WINDOW, GROUP, OTHER, END])

    def test_reconciles_costs_and_compiled_coverage(self):
        report = self.analyze(self.valid())
        self.assertEqual(report['totals'], dict(calls=5, cycles=100, nanoseconds=1000, compiled_calls=2))
        self.assertEqual([g['time_percent'] for g in report['groups']], [60, 40])
        self.assertTrue(report['groups'][0]['resume'])

    def test_missing_end_marker_is_not_accepted_as_complete(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            self.analyze(self.valid()[:-1])

    def test_explicitly_discards_only_incomplete_final_window(self):
        records = self.valid() + [dict(WINDOW, index=1), dict(GROUP, window=1)]
        report = self.analyze(records, tail='{"kind":', allow_incomplete_tail=True)
        self.assertEqual(report['complete_windows'], 1)
        self.assertEqual(report['totals']['calls'], 5)
        self.assertTrue(report['incomplete_tail_discarded'])

    def test_complete_malformed_line_is_not_treated_as_forced_stop(self):
        with self.assertRaisesRegex(ValueError, 'Malformed'):
            self.analyze(self.valid(), tail='broken\n', allow_incomplete_tail=True)

    def test_mismatched_totals_and_duplicate_groups_are_rejected(self):
        for update in (dict(calls=9), dict(cycles=99), dict(nanoseconds=1001), dict(groups=3)):
            records = self.valid()
            records[1].update(update)
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, 'reconcile'):
                self.analyze(records)
        records = self.valid()
        records[3] = dict(GROUP)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.analyze(records)

    def test_invalid_identity_numbers_and_coverage_are_rejected(self):
        for update in (dict(start_pc=7), dict(start_pc=16384), dict(calls=True), dict(cycles=-1),
                       dict(compiled_calls=3), dict(max_nanoseconds=401), dict(code_fnv1a64='bad'),
                       dict(resume=1)):
            records = self.valid()
            records[2].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.analyze(records)

    def test_empty_or_unsupported_or_unclosed_profiles_are_not_evidence(self):
        for records in ([], [META], [dict(META, schema=2)], [META, WINDOW],
                        [META, dict(WINDOW, index=1)], [META, dict(WINDOW, last_ee=40)]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                self.analyze(records, allow_incomplete_tail=True)


if __name__ == '__main__':
    unittest.main()

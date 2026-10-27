import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('game_speed_report', Path(__file__).resolve().parents[1] / 'tools/diagnostics/game_speed_report.py')
speed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speed)


class GameSpeedTests(unittest.TestCase):
    def test_unused_gpu_display_counter_does_not_report_zero_fps(self):
        report = self.report([{'tick': 1, 'ee_vsync_tick': 0, 'elapsed_seconds': 0, 'display_flips': 0},
                              {'tick': 601, 'ee_vsync_tick': 600, 'elapsed_seconds': 20, 'display_flips': 0}])
        self.assertNotIn('display_fps', report['overall'])
        self.assertGreater(report['overall']['wall_speed'], 0)

    def report(self, rows, seconds=None, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'diagnostics').mkdir()
            (root / 'diagnostics/state.jsonl').write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
            if seconds is not None:
                (root / 'report.json').write_text(json.dumps({'seconds': seconds}), encoding='utf-8')
            return speed.summarize(root, **kwargs)

    def test_slow_presentation_does_not_hide_slow_emulation(self):
        report = self.report([{'tick': 1, 'ee_vsync_tick': 0, 'elapsed_seconds': 0, 'display_flips': 0},
                              {'tick': 601, 'ee_vsync_tick': 600, 'elapsed_seconds': 20, 'display_flips': 300}], vsync_hz=60)
        self.assertEqual(report['overall']['host_ratio'], 1)
        self.assertEqual(report['overall']['wall_speed'], .5)
        self.assertEqual(report['windows'][0]['display_fps'], 15)

    def test_old_capture_only_has_lower_bound(self):
        report = self.report([{'tick': 1, 'ee_vsync_tick': 0}, {'tick': 601, 'ee_vsync_tick': 600}], seconds=20, vsync_hz=60)
        self.assertNotIn('wall_speed', report['overall'])
        self.assertEqual(report['whole_run_wall_speed_lower_bound'], .5)

    def test_partial_timestamps_do_not_invent_window_times(self):
        report = self.report([{'tick': 1, 'ee_vsync_tick': 0, 'elapsed_seconds': 0}, {'tick': 601, 'ee_vsync_tick': 600}])
        self.assertEqual(report['clock'], 'host_ticks')

    def test_pal_rate(self):
        report = self.report([{'tick': 1, 'ee_vsync_tick': 0, 'elapsed_seconds': 0},
                              {'tick': 601, 'ee_vsync_tick': 500, 'elapsed_seconds': 10}], vsync_hz=50)
        self.assertEqual(report['overall']['wall_speed'], 1)

    def test_counter_and_time_regressions_are_rejected(self):
        for row in ({'tick': 1, 'ee_vsync_tick': 0, 'elapsed_seconds': 1},
                    {'tick': 601, 'ee_vsync_tick': 1, 'elapsed_seconds': 0},
                    {'tick': 601, 'ee_vsync_tick': 0, 'elapsed_seconds': 2}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.report([{'tick': 1, 'ee_vsync_tick': 1, 'elapsed_seconds': 1}, row])

    def test_invalid_options(self):
        for kwargs in ({'window': 0}, {'vsync_hz': 0}, {'vsync_hz': float('nan')}):
            with self.assertRaises(ValueError):
                self.report([], **kwargs)

    def test_invalid_rows_are_counted(self):
        report = self.report([None, {'tick': True, 'ee_vsync_tick': 0}, {'tick': 1, 'ee_vsync_tick': 0},
                              {'tick': 601, 'ee_vsync_tick': 600}])
        self.assertEqual(report['malformed_rows'], 2)

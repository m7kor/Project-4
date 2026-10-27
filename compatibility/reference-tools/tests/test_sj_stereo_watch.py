import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('sj_stereo_watch', Path(__file__).resolve().parents[1] / 'tools/audio/sj_stereo_watch.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class StereoWatchTests(unittest.TestCase):
    def row(self, left, right, source=0x189a04, partial=False):
        words = [0] * 32
        words[8] = words[24] = 0x4000
        words[5], words[21] = left, right
        if partial:
            words = words[:16]
        return f'[watch] v=3000 source=0x{source:x} target=0x189850 kind=4 ra=0x189850 words=' + ','.join(f'{w:x}' for w in words) + ','

    def test_left_only_transient_is_not_a_divergence(self):
        result = watch.inspect([self.row(0, 0), self.row(0x800, 0), self.row(0x800, 0x800)])
        self.assertEqual(result['right_reservations'], 1)
        self.assertEqual(result['divergent_right_reservations'], 0)

    def test_reports_right_reservation_difference(self):
        result = watch.inspect([self.row(0, 0), self.row(0x800, 0), self.row(0x800, 0x8c0)])
        self.assertEqual(result['first_divergence']['difference_mod_capacity_bytes'], 0xc0)
        self.assertEqual(result['first_divergence']['vsync'], 3000)

    def test_partial_capture_resets_comparison_and_non_get_updates_are_excluded(self):
        result = watch.inspect([self.row(0, 0), self.row(0, 0, partial=True),
                                self.row(0x800, 0x8c0), self.row(0x800, 0x1000, source=0x189e04)])
        self.assertEqual(result['ignored_watch_rows'], 1)
        self.assertEqual(result['right_reservations'], 0)


if __name__ == '__main__':
    unittest.main()

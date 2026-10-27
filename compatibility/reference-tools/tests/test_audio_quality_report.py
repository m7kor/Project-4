import unittest
import numpy as np
from tools.diagnostics.audio_quality_report import analyse, measured_seconds


class AudioQualityTests(unittest.TestCase):
    def test_antiphase_is_not_silence(self):
        data = np.tile(np.array([1000, -1000], dtype=np.float32), (1000, 1))
        rows = analyse(1000, data, 1)
        self.assertEqual(rows[0][1], 1000)
        self.assertEqual(rows[0][4], 0)

    def test_partial_window_uses_real_duration(self):
        data = np.full((1500, 2), 1000, dtype=np.float32)
        rows = analyse(1000, data, 1)
        self.assertEqual(measured_seconds(rows, len(data), 1000, 1), 1.5)
        short = analyse(1000, data[:100], 0.1)
        self.assertEqual(short[0][6], 0)

    def test_invalid_windows_rejected(self):
        for window in (0, -1, float('inf'), float('nan'), 0.0001):
            with self.assertRaises(ValueError):
                analyse(1000, np.zeros((1000, 2), dtype=np.float32), window)

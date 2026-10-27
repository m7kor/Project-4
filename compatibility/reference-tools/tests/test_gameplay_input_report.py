import tempfile
import unittest
from pathlib import Path
from tools.diagnostics.gameplay_input_report import nearest_frame


class GameplayInputReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.states = []
        for host, guest in [(500, 20980), (600, 21010), (700, 21100)]:
            (self.directory / f'frame-{host}.png').touch()
            self.states.append(dict(tick=host, ee_vsync_tick=guest, host_frame=True,
                                    elapsed_seconds=host / 60))

    def test_uses_guest_clock_to_select_host_filename(self):
        frame = nearest_frame(self.states, self.directory, 21005)
        self.assertEqual(frame['snapshot_host_tick'], 600)
        self.assertTrue(frame['frame'].endswith('frame-600.png'))
        self.assertEqual(frame['guest_tick_difference'], 5)

    def test_before_cannot_select_a_closer_post_input_image(self):
        frame = nearest_frame(self.states, self.directory, 21000, maximum=21000)
        self.assertEqual(frame['snapshot_guest_tick'], 20980)
        self.assertIsNone(nearest_frame(self.states, self.directory, 21050,
                                       minimum=21040, maximum=21059))

    def test_unreached_or_missing_frames_remain_unknown(self):
        self.assertIsNone(nearest_frame(self.states, self.directory, 24200))
        (self.directory / 'frame-600.png').unlink()
        frame = nearest_frame(self.states, self.directory, 21005)
        self.assertEqual(frame['snapshot_guest_tick'], 20980)


if __name__ == '__main__':
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest
import wave

from tools.diagnostics.audio_process_timeline import summarize


class TimelineTests(unittest.TestCase):
    def fixture(self, root, overflow=0, truncate=False):
        report, log, wav = root / 'report.json', root / 'capture.log', root / 'heard.wav'
        report.write_text(json.dumps({
            'process_spawn_requested_unix_ns': 1001000000000,
            'process_start_observed_unix_ns': 1001100000000,
            'process_exit_observed_unix_ns': 1001500000000,
            'process_exit_forced': True,
        }))
        log.write_text(f'Saved 48000 frames (1.000 seconds). Queue overflow={overflow}, null input=0 frames.\n'
                       'Delivery timing: first_unix_ns=1000000000000 last_unix_ns=1001000000000 last_start_frame=47520 last_frames=480.\n')
        with wave.open(str(wav), 'wb') as stream:
            stream.setparams((2, 2, 48000, 0, 'NONE', ''))
            stream.writeframes(b'\0' * 192000)
        if truncate:
            data = wav.read_bytes()
            wav.write_bytes(data[:-4])
        return report, log, wav

    def test_packet_delivery_is_reported_as_approximate(self):
        with tempfile.TemporaryDirectory() as directory:
            result = summarize(*self.fixture(Path(directory)))
        self.assertAlmostEqual(result['nominal_process_exit_seconds_in_recording'], 1.5)
        self.assertAlmostEqual(result['endpoint_delivery_drift_seconds'], .01)
        self.assertTrue(result['process_exit_forced'])
        self.assertIn('not exact', result['scope'])

    def test_overflow_cannot_supply_continuous_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                summarize(*self.fixture(Path(directory), overflow=480))

    def test_declared_frames_do_not_hide_truncated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'truncated'):
                summarize(*self.fixture(Path(directory), truncate=True))


if __name__ == '__main__':
    unittest.main()

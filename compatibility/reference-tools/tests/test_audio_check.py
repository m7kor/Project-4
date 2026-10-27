import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
import wave

import numpy as np

spec = importlib.util.spec_from_file_location('audio_check', Path(__file__).resolve().parents[1] / 'tools/diagnostics/audio_check.py')
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


class AudioCheckTests(unittest.TestCase):
    def test_module_and_script_cli_with_run_context(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'diagnostics').mkdir()
            (run / 'diagnostics/state.jsonl').write_text('\n'.join(json.dumps(row) for row in (
                {'tick': 0, 'ee_vsync_tick': 0, 'elapsed_seconds': 0},
                {'tick': 120, 'ee_vsync_tick': 60, 'elapsed_seconds': 2})), encoding='utf-8')
            (run / 'stderr.txt').write_text(
                '[audio] requested=48000 delivered=47000 underrun=1000 tempo=0.5\n'
                '[audio] requested=96000 delivered=94997 underrun=1003 tempo=0.5\n', encoding='utf-8')
            recording = run / 'tone.wav'
            with wave.open(str(recording), 'wb') as stream:
                stream.setnchannels(2)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                stream.writeframes(self.tone(.125).astype('<i2').tobytes())
            for name, entry in (
                    ('module', ['-m', 'tools.diagnostics.audio_check']),
                    ('script', [str(root / 'tools/diagnostics/audio_check.py')])):
                destination = run / f'{name}.json'
                result = subprocess.run([sys.executable, *entry, str(recording), '--run', str(run),
                                         '--out', str(destination)], cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(destination.read_text(encoding='utf-8'))
                self.assertEqual(report['emulation_speed']['clock'], 'monotonic')
                self.assertAlmostEqual(report['emulation_speed']['overall']['wall_speed'], .5005)
                self.assertEqual(report['host_audio']['underrun_growth_after_first_sample'], 3)
                self.assertEqual(report['recordings']['single']['duration_seconds'], .125)
                self.assertTrue(destination.with_suffix('.html').is_file())

    def inspect(self, data, window=1, channels=2):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.wav'
            with wave.open(str(path), 'wb') as stream:
                stream.setnchannels(channels)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                stream.writeframes(np.asarray(data, dtype='<i2').tobytes())
            return audio.inspect(path, window)

    def tone(self, seconds=1):
        signal = (10000 * np.sin(np.arange(round(48000 * seconds)) * 2 * np.pi * 440 / 48000)).astype(np.int16)
        return np.column_stack((signal, signal))

    def test_clean_tone_has_no_clicks_or_gaps(self):
        report = self.inspect(self.tone())
        self.assertEqual(report['click_candidates'], 0)
        self.assertEqual(report['silence_percent_in_audible_windows'], 0)
        self.assertEqual(report['clipped_samples'], 0)
        self.assertAlmostEqual(report['stereo']['channel_correlation'], 1)
        self.assertEqual(report['stereo']['identical_channels_percent_of_audible_frames'], 100)

    def test_antiphase_stereo_is_not_silence(self):
        x = self.tone()
        x[:, 1] *= -1
        report = self.inspect(x)
        self.assertEqual(report['audible_window_seconds'], 1)
        self.assertEqual(report['silence_percent_in_audible_windows'], 0)
        self.assertAlmostEqual(report['stereo']['channel_correlation'], -1)
        self.assertEqual(report['stereo']['identical_channels_percent_of_audible_frames'], 0)

    def test_dropout_timestamps(self):
        x = self.tone()
        x[12000:14400] = 0
        report = self.inspect(x)
        event = next(e for e in report['events'] if e['kind'] == 'silence_candidate')
        self.assertAlmostEqual(event['start_seconds'], .25, places=3)
        self.assertAlmostEqual(event['duration_ms'], 50, delta=.1)

    def test_one_channel_impulse_is_detected(self):
        x = self.tone()
        x[24000, 1] = 32000
        self.assertGreater(self.inspect(x)['click_candidates'], 0)

    def test_low_volume_impulse_is_still_detected(self):
        x = self.tone()
        x[24000, 1] = 32000
        quiet = (x.astype(np.float64) * .03).astype(np.int16)
        report = self.inspect(quiet)
        self.assertGreater(report['click_candidates'], 0)
        self.assertGreater(report['click_analysis_gain'], 1)

    def test_low_volume_clean_tone_is_not_a_click(self):
        quiet = (self.tone().astype(np.float64) * .03).astype(np.int16)
        self.assertEqual(self.inspect(quiet)['click_candidates'], 0)

    def test_partial_window_duration_and_clipping(self):
        x = self.tone(.125)
        x[:10] = -32768
        report = self.inspect(x)
        self.assertEqual(report['duration_seconds'], .125)
        self.assertEqual(report['windows'][0]['duration_seconds'], .125)
        self.assertEqual(report['clipped_samples'], 20)

    def test_periodic_block_impulses_have_fixed_phase(self):
        x = self.tone()
        x[128::256, 1] = 32000
        report = self.inspect(x)
        self.assertGreater(report['click_candidates'], 100)
        self.assertGreater(report['click_phase_256']['top_two_percent'], 95)

    def test_silent_recording_has_no_audible_percentage(self):
        report = self.inspect(np.zeros((100, 2)))
        self.assertIsNone(report['silence_percent_in_audible_windows'])
        self.assertEqual(report['leading_quiet_seconds'], 100 / 48000)
        self.assertTrue(report['digital_silence'])
        self.assertEqual(report['audible_frames'], 0)
        rendered = audio.render_html({'recordings': {'single': report}}, Path(report['path']).parent / 'report.html')
        self.assertIn('التسجيل صامت بالكامل', rendered)

    def test_quiet_nonzero_signal_is_distinguished_from_digital_silence(self):
        report = self.inspect(np.ones((100, 2)))
        self.assertFalse(report['digital_silence'])
        self.assertEqual(report['audible_frames'], 0)

    def test_audible_tone_is_distinguished_from_zero_recording(self):
        report = self.inspect(self.tone())
        self.assertFalse(report['digital_silence'])
        self.assertGreater(report['audible_frames'], 0)

    def test_reject_empty_mono_and_invalid_window(self):
        for data, window, channels in [(np.zeros((0, 2)), 1, 2),
                                        (np.zeros(100), 1, 1),
                                        (self.tone(), float('nan'), 2),
                                        (self.tone(), 0, 2)]:
            with self.subTest(window=window, channels=channels), self.assertRaises(ValueError):
                self.inspect(data, window, channels)

    def test_underrun_delta_excludes_initial_fill(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stderr.txt'
            path.write_text('[audio] requested=240000 delivered=236000 underrun=4000 tempo=1\n'
                            '[audio] requested=480000 delivered=475000 underrun=5000 tempo=.5\n')
            report = audio.audio_log(path)
            self.assertEqual(report['underrun_growth_after_first_sample'], 1000)
            self.assertEqual(report['samples'][-1]['tempo'], .5)

    def test_listening_report_uses_local_event_clock(self):
        report = self.inspect(self.tone())
        report['events'] = [{'kind': 'click_candidate', 'start_seconds': 12, 'peak_step': 9000}]
        rendered = audio.render_html({'recordings': {'output': report}}, Path(report['path']).parent / 'report.html')
        self.assertIn("data-time='11.500'", rendered)
        self.assertIn("src='test.wav'", rendered)
        self.assertIn('12.000', rendered)

    def test_bad_output_extension_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.html'
            path.write_text('keep')
            with self.assertRaises(SystemExit) as exit_result:
                audio.main(['missing.wav', '--out', str(path)])
            self.assertEqual(exit_result.exception.code, 2)
            self.assertEqual(path.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()

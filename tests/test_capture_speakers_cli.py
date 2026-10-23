import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'artifacts/tools/capture_speakers.exe'


@unittest.skipUnless(os.name == 'nt' and TOOL.is_file(), 'optional Windows loopback tool is not built')
class CaptureSpeakersCliTests(unittest.TestCase):
    def test_invalid_arguments_do_not_open_audio(self):
        for args in (['--seconds', 'nan'], ['--seconds', '-1'], ['--seconds', '0'],
                     ['--seconds', '3601'], ['--device', '-1'], ['--device', '10001'], ['--wat']):
            with self.subTest(args=args):
                result = subprocess.run([str(TOOL), *args], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(b'Recording speaker endpoint', result.stdout)

    def test_existing_recording_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'keep.wav'
            path.write_bytes(b'original recording')
            result = subprocess.run([str(TOOL), '--out', str(path), '--seconds', '1'], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_bytes(), b'original recording')


if __name__ == '__main__':
    unittest.main()

"""A freshly created diagnostics file must be retried, not crash the A/B driver."""
from pathlib import Path
import tempfile
import unittest
from tools.measure_phase5_game import last_state
ROOT=Path(__file__).resolve().parents[1]

class ObserverReadTests(unittest.TestCase):
    def test_empty_new_file_is_a_transient_value_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as folder:
            path=Path(folder)/'state.jsonl';path.write_bytes(b'')
            with self.assertRaises(ValueError):last_state(path)

    def test_latest_complete_record_retains_real_guest_timestamp(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as folder:
            path=Path(folder)/'state.jsonl'
            path.write_text('{"ee_vsync_tick":3300,"elapsed_seconds":70.1}\n{"ee_vsync_tick":3312,"elapsed_seconds":71.1}\n')
            self.assertEqual(last_state(path),{'ee_vsync_tick':3312,'elapsed_seconds':71.1})

if __name__=='__main__':unittest.main()

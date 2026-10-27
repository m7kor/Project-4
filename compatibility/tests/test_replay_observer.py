"""Regression: native replay logging must trigger the existing bounded observer."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reference-tools'))
from tools.diagnostics.re4_live_memory import wait_for_replay

class ObserverTriggerTests(unittest.TestCase):
    def check_log(self,line):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            (run/'stderr.txt').write_text(line)
            self.assertIn('8400',wait_for_replay(run,8400,.1))
    def test_existing_pad_trace(self):
        self.check_log('[pad trace] stage=replay ordinal=1 ee_tick=8400 buttons=0xffff\n')
    def test_native_pad_replay(self):
        self.check_log('[native pad replay] tick=8400 buttons=0xffff\n')
    def test_wrong_tick_does_not_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            (run/'stderr.txt').write_text('[native pad replay] tick=8401 buttons=0xffff\n')
            (run/'report.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'ended before replay trigger'):
                wait_for_replay(run,8400,.1)
if __name__=='__main__':unittest.main()

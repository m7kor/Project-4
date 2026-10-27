import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reference-tools'))
from tools.diagnostics.lab_layout import owned_layout

class LabLayoutTests(unittest.TestCase):
    def fixture(self,base):
        root=Path(base);tools=root/'reference-tools';tools.mkdir()
        run=root/'artifacts/runs/owned';run.mkdir(parents=True);(run/'identity.json').write_text('{}')
        return tools,run
    def test_explicit_flat_owned_run(self):
        with tempfile.TemporaryDirectory() as d:
            tools,run=self.fixture(d);self.assertEqual(owned_layout(run,tools,run),run)
    def test_terminal_run_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            tools,run=self.fixture(d);(run/'report.json').write_text('{}')
            with self.assertRaises(ValueError):owned_layout(run,tools,run)
    def test_outside_owner_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            tools,run=self.fixture(d);other=Path(d)/'elsewhere';other.mkdir()
            with self.assertRaises(ValueError):owned_layout(other,tools,other)
    def test_original_capture_layout_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            tools=Path(d);run=tools/'artifacts/runs/owner/captures/session';run.mkdir(parents=True)
            self.assertEqual(owned_layout(run,tools),run.parents[1])
if __name__=='__main__':unittest.main()

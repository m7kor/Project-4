import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("replay_progress", Path(__file__).resolve().parents[1] / "tools/diagnostics/replay_progress.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReplayProgressTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fixture = self.root / "replay.csv"
        self.fixture.write_text("begin,end,buttons,lx,ly,rx,ry\n2100,2132,49151,128,128,128,128\n")
        (self.root / "report.json").write_text(json.dumps({"diagnostics": {"last_state": {"tick": 16000, "ee_vsync_tick": 2000}}}))
        (self.root / "stderr.txt").write_text("")

    def test_host_frames_do_not_advance_replay(self):
        result = module.audit(self.root, self.fixture)
        self.assertEqual(result["last_observed_ee_tick"], 2000)
        self.assertFalse(result["all_interval_ends_reached"])

    def test_reaching_end_does_not_prove_button_sample(self):
        (self.root / "report.json").write_text(json.dumps({"diagnostics": {"last_state": {"ee_vsync_tick": 3000}}}))
        result = module.audit(self.root, self.fixture)
        self.assertTrue(result["all_interval_ends_reached"])
        self.assertFalse(result["events"][0]["button_transition_seen"])

    def test_logged_transition_can_follow_last_snapshot(self):
        (self.root / "stderr.txt").write_text("[native pad replay] tick=2101 buttons=0xbfff\n[native pad replay] tick=2133 buttons=0xffff\n")
        result = module.audit(self.root, self.fixture)
        self.assertEqual(result["last_observed_ee_tick"], 2133)
        self.assertTrue(result["events"][0]["button_transition_seen"])
        self.assertTrue(result["all_interval_ends_reached"])

    def test_invalid_fixture_and_existing_output_are_preserved(self):
        output = self.root / "out.json"
        output.write_text("keep")
        with self.assertRaises(FileExistsError):
            module.main([str(self.root), str(self.fixture), "--out", str(output)])
        self.assertEqual(output.read_text(), "keep")
        self.fixture.write_text(self.fixture.read_text() + "2110,2140,49151,128,128,128,128\n")
        with self.assertRaises(ValueError):
            module.audit(self.root, self.fixture)

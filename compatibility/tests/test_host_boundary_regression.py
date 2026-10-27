"""Regression for the real relative-canary-tool failure observed in full testing."""
from pathlib import Path
import importlib.util
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('host_boundary_lab',ROOT/'tools/lab_regression.py')
lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)

class CanaryPathTests(unittest.TestCase):
    def test_relative_recompiler_is_bound_before_child_working_directory_changes(self):
        suite=mock.Mock();suite.report={'requested_gate_exit_code':0};suite.out=ROOT/'artifacts'
        captured=[]
        def factory(args):captured.append(args);return suite
        with mock.patch.object(lab,'Suite',side_effect=factory):
            self.assertEqual(lab.main(['ee','--project4-recompiler','lab/phase4-fixed-01/ps2_recomp.exe']),0)
        self.assertEqual(captured[0].project4_recompiler,ROOT/'lab/phase4-fixed-01/ps2_recomp.exe')

    def test_real_route_failure_class_analog_changes_within_one_field(self):
        from tools.replay_input_quality import field_replay
        events=[{'tick':10,'host_ms':100,'state':(65535,128,128,128,128)},
                {'tick':11,'host_ms':101,'state':(65535,127,0,128,128)},
                {'tick':11,'host_ms':102,'state':(65535,129,0,128,128)},
                {'tick':12,'host_ms':103,'state':(65535,128,128,128,128)}]
        with self.assertRaisesRegex(ValueError,'finer replay contract'):
            field_replay(events)

if __name__=='__main__':unittest.main()

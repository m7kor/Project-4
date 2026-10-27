"""Prevent experimental-mode leakage and silently testing reference instead."""
from pathlib import Path
import argparse,importlib.util,os,tempfile,unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
lab=module('architecture_lab_test',ROOT/'tools/lab_regression.py');runner=module('architecture_runner_test',ROOT/'tools/run_lab.py')
class ArchitectureModeTests(unittest.TestCase):
 def suite(self,root,**kwargs):
  with mock.patch.object(lab,'ROOT',root),mock.patch.object(lab,'revision',return_value={}),mock.patch.object(lab,'discover_changes',return_value=[]):return lab.Suite(argparse.Namespace(changed=[],**kwargs))
 def test_explicit_mode_reaches_actual_test_environment(self):
  with tempfile.TemporaryDirectory(prefix='test-architecture-',dir=ROOT/'artifacts') as d:
   suite=self.suite(Path(d),vu_aot_coverage='1');self.assertEqual(suite.env['PS2X_VU1_AOT_COVERAGE'],'1');self.assertEqual(suite.report['vu_aot_coverage'],'1')
 def test_inherited_environment_cannot_enable_candidate(self):
  with tempfile.TemporaryDirectory(prefix='test-architecture-',dir=ROOT/'artifacts') as d,mock.patch.dict(os.environ,{'PS2X_VU1_AOT_COVERAGE':'1'}):
   suite=self.suite(Path(d));self.assertNotIn('PS2X_VU1_AOT_COVERAGE',suite.env);self.assertIsNone(suite.report['vu_aot_coverage'])
 def test_invalid_or_duplicate_live_mode_is_rejected(self):
  for options in [['--vu-aot-coverage=yes'],['--vu-aot-coverage=1','--vu-aot-coverage=0']]:
   with self.assertRaises(ValueError):runner.binary_mode_option(options,'--vu-aot-coverage')
 def test_omitted_live_option_keeps_reference_default(self):
  self.assertIsNone(runner.binary_mode_option([],'--vu-aot-coverage'))
if __name__=='__main__':unittest.main()

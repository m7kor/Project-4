import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('phase5_run_lab',Path(__file__).resolve().parents[1]/'tools/run_lab.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
class PipelineConfigurationTests(unittest.TestCase):
    def test_default_does_not_enable_experiment(self):self.assertIsNone(runner.pipeline_index_option([]))
    def test_explicit_modes(self):
        for mode in ('0','1'):self.assertEqual(runner.pipeline_index_option(['--vu-pipeline-index='+mode]),mode)
    def test_invalid_mode_is_refused_before_launch(self):
        with self.assertRaises(ValueError):runner.pipeline_index_option(['--vu-pipeline-index=wrong'])
    def test_conflicting_configuration_is_refused(self):
        with self.assertRaises(ValueError):runner.pipeline_index_option(['--vu-pipeline-index=0','--vu-pipeline-index=1'])
    def test_vector_retirement_is_explicit(self):
        self.assertIsNone(runner.binary_mode_option([],'--vu-vector-retire'))
        self.assertEqual(runner.binary_mode_option(['--vu-vector-retire=1'],'--vu-vector-retire'),'1')
if __name__=='__main__':unittest.main()

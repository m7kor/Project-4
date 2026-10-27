"""Procedural failure controls for the new source/binary identity gate."""
from pathlib import Path
from unittest import mock
import argparse,importlib.util,json,tempfile,unittest
spec=importlib.util.spec_from_file_location('phase5_gate_lab',Path(__file__).resolve().parents[1]/'tools/lab_regression.py')
lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)
class FmacGateTests(unittest.TestCase):
    def fixture(self,root,stale_source=False):
        source=root/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp';source.parent.mkdir(parents=True);source.write_text('procedural test source')
        directory=root/'artifacts/phase5';directory.mkdir(parents=True)
        record={'source_sha256':'0'*64 if stale_source else lab.sha(source),'rows':[{'mode':name,'sha256':'0'*64} for name in ('simd','scalar','mutant')]}
        (directory/'fmac-helper-report.json').write_text(json.dumps(record));(directory/'fmac-helper-inputs.json').write_text(json.dumps({'files':{}}))
        candidate=root/'candidate';candidate.mkdir();(candidate/'engineering-inputs.json').write_text(json.dumps({'files':{str(source):lab.sha(source)}}))
        witness=root/'lab/phase5-fmac-witness-01';witness.mkdir(parents=True);(witness/'simd.exe').write_bytes(b'never execute this synthetic identity fixture')
        suite=lab.Suite.__new__(lab.Suite);suite.args=argparse.Namespace(vu_fmac_classify='1',candidate_dir=candidate);suite.done=set();suite.report={'hashes':{}}
        suite.run=lambda *a,**kw:self.fail('Unverified executable must never run')
        return suite
    def test_stale_classifier_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);suite=self.fixture(root,True)
            with mock.patch.object(lab,'ROOT',root),self.assertRaisesRegex(ValueError,'production source changed'):suite.fmac_regressions()
    def test_changed_witness_binary_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);suite=self.fixture(root)
            with mock.patch.object(lab,'ROOT',root),self.assertRaisesRegex(ValueError,'executable identity mismatch'):suite.fmac_regressions()
    def test_legacy_reference_does_not_silently_enable_experiment(self):
        suite=lab.Suite.__new__(lab.Suite);suite.args=argparse.Namespace()
        self.assertIsNone(suite.fmac_regressions())
if __name__=='__main__':unittest.main()

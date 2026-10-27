"""Safety and oracle-contract tests for the offline-first orchestrator."""
import importlib.util,json,sys,unittest,tempfile,argparse
from pathlib import Path
spec=importlib.util.spec_from_file_location('lab_regression',Path(__file__).resolve().parents[1]/'tools/lab_regression.py')
lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)
spec2=importlib.util.spec_from_file_location('lab_game_acceptance',Path(__file__).resolve().parents[1]/'tools/lab_game_acceptance.py')
game=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(game)
class SelectionTests(unittest.TestCase):
    def test_vu_selects_oracle(self):self.assertEqual(lab.impact(['ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp']),(['vu'],[]))
    def test_vif_selects_interactions(self):self.assertEqual(set(lab.impact(['ps2_vif1_interpreter.cpp'])[0]),{'vu','graphics','ee','dma'})
    def test_unknown_fails_broad(self):
        groups,unknown=lab.impact(['mystery.cpp']);self.assertIn('hardware',groups);self.assertIn('vu',groups);self.assertEqual(unknown,['mystery.cpp'])
    def test_no_changes_does_not_assume_no_work(self):self.assertIn('ee',lab.impact([])[0])
    def test_auto_never_selects_game(self):self.assertNotIn('integration',lab.impact(['unknown'])[0])
    def test_signature_preserves_cycles(self):
        row={'state_result':'abc','cycles':9,'gif_packets':2,'gif_verified_passes':1}
        self.assertEqual(lab.signature(json.dumps(row))['cycles'],9)
    def test_unverified_gif_is_rejected(self):
        with self.assertRaises(ValueError):lab.signature(json.dumps({'state_result':'abc','cycles':9,'gif_packets':2}))
    def test_first_divergence_identifies_field(self):
        self.assertEqual(lab.compare_signatures({'cycles':1},{'cycles':2}),{'field':'cycles','reference':1,'candidate':2})
    def test_identity_is_not_liveness(self):
        with self.assertRaises(ValueError):lab.signature('process still running')
    def test_snapshot_requires_gif_bytes(self):
        with self.assertRaises(ValueError):lab.signature(' result=0123456789abcdef vu1_cycles=100 gif_packets=1')
    def test_stale_source_stops_candidate_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'core.cpp';source.write_text('modified')
            files={'ps2x_tests.exe':b'unit','ps2x_vu1_bench.exe':b'bench'}
            for name,data in files.items():(folder/name).write_bytes(data)
            (folder/'identity.json').write_text(json.dumps({k:lab.sha(folder/k) for k in files}))
            (folder/'compile-inputs.json').write_text(json.dumps({'inputs':{'ps2_vu1_core.cpp':'0'*64}}))
            suite=lab.Suite.__new__(lab.Suite);suite.args=argparse.Namespace(vu_source=source,changed=[],benchmark=False)
            suite.report={'hashes':{},'selected_groups':['vu']}
            with self.assertRaisesRegex(ValueError,'Stale VU binary'):suite.bind(folder)
    def test_game_liveness_is_not_a_success_criterion(self):
        with self.assertRaisesRegex(ValueError,'measured EE progress'):
            game.validate_spec({'reason':'release-smoke','hypothesis':'A concrete acceptance hypothesis','seconds':60,'success':{}})
    def test_engineering_binding_rejects_stale_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'memory.cpp';source.write_text('before')
            for name in ('ps2x_tests.exe','ps2x_vu1_bench.exe'):(folder/name).write_bytes(b'procedural')
            (folder/'identity.json').write_text(json.dumps({p.name:lab.sha(p) for p in folder.glob('*.exe')}))
            stamp={'files':{str(source):lab.sha(source)},'covered_source_files':[str(source)],'scope':'test fixture'}
            (folder/'engineering-inputs.json').write_text(json.dumps(stamp));source.write_text('mutated')
            suite=lab.Suite.__new__(lab.Suite);suite.args=argparse.Namespace(changed=[],benchmark=False)
            suite.report={'hashes':{},'selected_groups':['fast']}
            with self.assertRaisesRegex(ValueError,'Stale engineering compiler input'):suite.bind(folder)
    def test_engineering_coverage_does_not_confuse_same_basename(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'memory.cpp';source.write_text('before')
            for name in ('ps2x_tests.exe','ps2x_vu1_bench.exe'):(folder/name).write_bytes(b'procedural')
            (folder/'identity.json').write_text(json.dumps({p.name:lab.sha(p) for p in folder.glob('*.exe')}))
            stamp={'files':{str(source):lab.sha(source)},'covered_source_files':[str(source)],'scope':'test fixture'}
            (folder/'engineering-inputs.json').write_text(json.dumps(stamp))
            suite=lab.Suite.__new__(lab.Suite);suite.args=argparse.Namespace(changed=[str(folder/'different/memory.cpp')],benchmark=False)
            suite.report={'hashes':{},'tests':[],'selected_groups':['fast']};suite.bind(folder)
            self.assertEqual(suite.report['tests'][0]['status'],'blocked')
    def test_game_requires_reason_and_bound(self):
        with self.assertRaises(ValueError):game.validate_spec({'reason':'just-launch','hypothesis':'anything','seconds':3600})
    def test_optimization_requires_offline_gate(self):
        with self.assertRaisesRegex(ValueError,'offline'):
            game.validate_spec({'reason':'optimization-after-offline-gates','hypothesis':'A concrete acceptance hypothesis','seconds':60,'success':{'minimum_ee_vsync':3000}})
    def test_input_consumption_must_match_tape(self):
        text='[pad trace] stage=replay ms=2 buttons=49151 lx=128 ly=128 rx=128 ry=128 ee_tick=100'
        self.assertEqual(game.consumption(text,[[100,120,49151,128,128,128,128]])['non_neutral_changes'],1)
        with self.assertRaisesRegex(ValueError,'divergence'):game.consumption(text,[])
    def test_no_observed_input_is_not_a_pass(self):
        with self.assertRaises(ValueError):game.consumption('process alive',[])
    def test_mixed_benchmark_cannot_pass_promotion(self):
        decision=lab.performance_decision([2.36,-.40,2.11,-.75,-.65,2.35,-.75])
        self.assertEqual(decision,'mixed-inconclusive');self.assertEqual(lab.gate_exit(True,True,decision),2)
    def test_slower_candidate_rejected_without_game(self):
        decision=lab.performance_decision([-1]*7)
        self.assertEqual(decision,'reject-consistently-slower');self.assertEqual(lab.gate_exit(True,True,decision),2)
    def test_correctness_failure_always_blocks(self):self.assertEqual(lab.gate_exit(False,True,'isolated-gain-needs-game-acceptance'),1)
if __name__=='__main__':unittest.main()

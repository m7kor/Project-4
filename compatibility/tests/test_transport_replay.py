import copy,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
t=load('transport_replay');lab=load('lab_regression')
class TransportContracts(unittest.TestCase):
    def fixture(self,folder):
        f={'schema':1,'kind':'dma','initial':[],'events':[{'seq':0,'op':'irq','expect':{}}]}
        p=folder/'input.json';p.write_text(json.dumps(f));return p,f,{'kind':'dma','sha256':t.sha(p),'initial_sha256':hashlib.sha256(b'[]').hexdigest()}
    def test_complete_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            p,f,e=self.fixture(Path(d));self.assertEqual(t.validate_fixture(p,e),f)
    def test_fixture_hash_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p,f,e=self.fixture(Path(d));p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'identity'):t.validate_fixture(p,e)
    def test_initial_hash_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p,f,e=self.fixture(Path(d));e['initial_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'Initial-state'):t.validate_fixture(p,e)
    def test_reordered_commands(self):
        with tempfile.TemporaryDirectory() as d:
            p,f,e=self.fixture(Path(d));f['events'][0]['seq']=5;p.write_text(json.dumps(f));e['sha256']=t.sha(p)
            with self.assertRaisesRegex(ValueError,'order'):t.validate_fixture(p,e)
    def test_empty_capture(self):self.assertEqual(t.difference([{'event':0}],[])['field'],'observation_count')
    def test_memory_effect(self):self.assertEqual(t.difference([{'ram':'a'}],[{'ram':'b'}])['field'],'ram')
    def test_interrupt_effect(self):self.assertEqual(t.difference([{'causes':[1]}],[{'causes':[]}])['event'],-1)
    def test_complete_observations(self):self.assertIsNone(t.difference([{'a':1}],[{'a':1}]))
    def test_executable_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fake.exe';p.write_bytes(b'MZ-mutated')
            with self.assertRaisesRegex(ValueError,'executable identity'):t.validate_identity(p,{'binary_sha256':'0'*64})
    def test_changed_source_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'native.exe';p.write_bytes(b'pinned executable');src=Path(d)/'runtime.cpp';src.write_text('old source')
            identity={'binary_sha256':t.sha(p),'harness_path':str(src),'harness_sha256':t.sha(src),'included_harness_sha256':t.sha(ROOT/'tests/vif_direct_replay.cpp'),'production_sources':{str(src):t.sha(src)},'headers':{str(src):t.sha(src)},'linked_objects':{str(src):t.sha(src)}}
            t.validate_identity(p,identity);src.write_text('changed source')
            with self.assertRaisesRegex(ValueError,'source changed'):t.validate_identity(p,identity)
    def test_output_packet_mutation(self):self.assertEqual(t.difference([{'packet_hash':'a'}],[{'packet_hash':'b'}])['field'],'packet_hash')
    def test_completion_mutation(self):self.assertEqual(t.difference([{'completion':-1}],[{'completion':0}])['field'],'completion')
    def test_iop_selection(self):self.assertIn('iop',lab.impact(['ps2xIOP/src/emulator/services/iop_rpc.cpp'])[0])
    def test_dma_selection(self):self.assertIn('dma',lab.impact(['dma_chain_cycle_guard.h'])[0])
    def test_shared_consumer_selection(self):self.assertTrue({'dma','iop'}.issubset(lab.impact(['tests/dma_iop_replay.cpp'])[0]))
    def test_transport_tool_selection(self):self.assertTrue({'dma','iop'}.issubset(lab.impact(['tools/transport_replay.py'])[0]))
    def test_unknown_selection(self):self.assertTrue({'dma','iop'}.issubset(lab.impact(['unknown.cpp'])[0]))
    def test_no_automatic_game(self):self.assertNotIn('integration',lab.impact(['tools/transport_replay.py'])[0])
    def test_missing_entire_fixture_set(self):
        with self.assertRaisesRegex(ValueError,'Incomplete'):t.select_entries({'schema':1,'fixtures':{}},'dma')
    def test_missing_named_fixture(self):
        with self.assertRaisesRegex(ValueError,'Incomplete'):t.select_entries({'schema':1,'fixtures':{'dma-chain':{'kind':'dma'}}},'dma')
if __name__=='__main__':unittest.main()

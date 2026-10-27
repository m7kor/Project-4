import importlib.util,json,struct,tempfile,unittest
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
game=load('lab_game_acceptance');lab=load('lab_regression');vif=load('vif_replay')
class CaptureContracts(unittest.TestCase):
    def make(self,path):
        d=path/'diagnostics';d.mkdir();rows=[]
        for i in range(4):
            tick=(i+1)*60;Image.new('RGB',(3,3),(20,30,40)).save(d/f'frame-{tick}.png')
            rows.append({'tick':tick,'elapsed_seconds':i+1,'ee_vsync_tick':100+i,'host_frame':True})
        self.write(d,rows);return d,rows
    def write(self,d,rows):(d/'state.jsonl').write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
    def test_complete_capture(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.make(p);self.assertEqual(len(game.validate_capture_files(p)[1]),4)
    def test_missing_middle_with_three_images_remaining(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);d,_=self.make(p);(d/'frame-120.png').unlink()
            with self.assertRaisesRegex(ValueError,'Missing or unexpected'):game.validate_capture_files(p)
    def test_truncated_middle_not_only_last(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);d,_=self.make(p);(d/'frame-120.png').write_bytes(b'\x89PNG')
            with self.assertRaises(Exception):game.validate_capture_files(p)
    def test_truncated_json(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);d,_=self.make(p);(d/'state.jsonl').write_text('{')
            with self.assertRaises(json.JSONDecodeError):game.validate_capture_files(p)
    def test_regressed_guest_progress(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);d,rows=self.make(p);rows[2]['ee_vsync_tick']=1;self.write(d,rows)
            with self.assertRaisesRegex(ValueError,'regress'):game.validate_capture_files(p)
    def test_duplicate_capture_identity(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);d,rows=self.make(p);rows[2]['tick']=rows[1]['tick'];self.write(d,rows)
            with self.assertRaises(ValueError):game.validate_capture_files(p)
    def test_final_black_frame(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);d,_=self.make(p);Image.new('RGB',(3,3)).save(d/'frame-240.png')
            with self.assertRaisesRegex(ValueError,'black'):game.validate_capture_files(p)
class HardwareContracts(unittest.TestCase):
    def test_known_mismatch_requires_full_identical_output(self):
        b={'classification':'known-mismatch','tty_sha256':'abc'}
        self.assertEqual(lab.hardware_status({'status':'MISMATCH'},b,'abc'),'known-mismatch')
        self.assertEqual(lab.hardware_status({'status':'MISMATCH'},b,'changed'),'failed')
    def test_new_regression_never_blessed(self):
        self.assertEqual(lab.hardware_status({'status':'MISMATCH'},{'classification':'new-regression','tty_sha256':'abc'},'abc'),'failed')
    def test_crash_is_not_known_difference(self):
        self.assertEqual(lab.hardware_status({'status':'CRASH'},{'classification':'known-mismatch','tty_sha256':'abc'},'abc'),'failed')
class VifContracts(unittest.TestCase):
    def data(self):
        return struct.pack('<4Q',0x31594c5052464956,1,4,0)+b''.join(struct.pack('<6Q',i,0x50000001,16,i,0,0)+bytes(16) for i in range(4))
    def read(self,data):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'fixture.bin';p.write_bytes(data);return vif.read_events(p)
    def test_ordered_complete_fixture(self):self.assertEqual(len(self.read(self.data())),4)
    def test_truncation(self):
        with self.assertRaises(ValueError):self.read(self.data()[:-1])
    def test_tail(self):
        with self.assertRaises(ValueError):self.read(self.data()+b'x')
    def test_time_regression(self):
        data=bytearray(self.data());struct.pack_into('<Q',data,32+3*64+24,0)
        with self.assertRaisesRegex(ValueError,'timestamps'):self.read(data)
    def test_wrong_direct_length(self):
        data=bytearray(self.data());struct.pack_into('<Q',data,40,0x50000002)
        with self.assertRaisesRegex(ValueError,'opcode or length'):self.read(data)
    def test_memory_divergence_names_event(self):
        self.assertEqual(vif.first_divergence([{'vram':'a'}],[{'vram':'b'}])['field'],'vram')
class PairContracts(unittest.TestCase):
    def test_incomplete_pair_cannot_be_a_gain(self):
        with self.assertRaises(ValueError):lab.analyze_pairs([{'pair':0,'label':'reference','ns_per_cycle':1}],1)
    def test_nan_cannot_be_a_gain(self):
        with self.assertRaises(ValueError):lab.analyze_pairs([{'pair':0,'label':'reference','ns_per_cycle':1},{'pair':0,'label':'candidate','ns_per_cycle':float('nan')}],1)
if __name__=='__main__':unittest.main()

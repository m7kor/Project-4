from pathlib import Path
import importlib.util,unittest
spec=importlib.util.spec_from_file_location('input_quality',Path(__file__).resolve().parents[1]/'tools/replay_input_quality.py')
quality=importlib.util.module_from_spec(spec);spec.loader.exec_module(quality)
class ReplayQualityTests(unittest.TestCase):
    def event(self,tick,state=None,host=None):return {'tick':tick,'host_ms':tick if host is None else host,'state':quality.NEUTRAL if state is None else state}
    def test_exact_half_open_interval_and_lossless_merge(self):
        pressed=(49151,128,128,128,128)
        self.assertEqual(quality.field_replay([self.event(0),self.event(10,pressed),self.event(12,pressed),self.event(20)]),[[10,20,*pressed]])
    def test_zero_clock_is_not_exact_replay(self):
        with self.assertRaisesRegex(ValueError,'every ee_tick is zero'):quality.field_replay([self.event(0),self.event(0)])
    def test_multiple_changes_inside_field_are_not_dropped(self):
        with self.assertRaisesRegex(ValueError,'finer replay contract'):quality.field_replay([self.event(0),self.event(10,(49151,128,128,128,128)),self.event(10),self.event(20)])
    def test_final_release_is_required(self):
        with self.assertRaisesRegex(ValueError,'release was not captured'):quality.field_replay([self.event(0),self.event(10,(49151,128,128,128,128))])
    def test_nonmonotonic_trace_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Nonmonotonic'):quality.field_replay([self.event(0),self.event(10,(49151,128,128,128,128)),self.event(9)])
    def test_oversized_replay_is_not_lossily_compressed(self):
        events=[self.event(0)]
        for i in range(1025):events += [self.event(i*4+1,(49151,128,128,128,128)),self.event(i*4+2)]
        with self.assertRaisesRegex(ValueError,'1024-row limit'):quality.field_replay(events)
    def test_truncated_event_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Incomplete'):quality.parse_guest_trace('[pad trace] stage=guest buttons=49151')
if __name__=='__main__':unittest.main()

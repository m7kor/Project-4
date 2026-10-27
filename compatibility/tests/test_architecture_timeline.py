from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from architecture_timeline import native_events
from replay_input_quality import field_replay
def event(stage,tick,buttons=65535):return f'[pad trace] stage={stage} ms=1 focused=-1 host=0 buttons={buttons} lx=128 ly=128 rx=128 ry=128 host_ms={100+tick} ee_tick={tick}'
class NativeTimelineTests(unittest.TestCase):
 def test_native_source_stages_preserve_recorded_clock(self):
  values=native_events('\n'.join([event('replay',10),event('live',20,49151),event('live',30)]));self.assertEqual(field_replay(values),[[20,30,49151,128,128,128,128]])
 def test_host_publication_is_not_native_sampling(self):
  with self.assertRaisesRegex(ValueError,'No native'):native_events(event('host',0))
 def test_zero_guest_clock_is_still_rejected(self):
  with self.assertRaisesRegex(ValueError,'every ee_tick is zero'):field_replay(native_events('\n'.join([event('guest',0),event('guest',0,49151),event('guest',0)])))
 def test_conflicting_states_in_one_field_are_not_silently_ordered(self):
  with self.assertRaisesRegex(ValueError,'finer replay'):field_replay(native_events('\n'.join([event('guest',1),event('guest',2,49151),event('guest',2)])))
 def test_incomplete_native_line_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'Incomplete'):native_events('[pad trace] stage=live buttons=49151 ee_tick=10')
if __name__=='__main__':unittest.main()

"""Observed guest-field timeline and lossless input fixture; no invented clocks."""
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from replay_input_quality import field_replay
PATTERN=re.compile(r'\[pad trace\] stage=(guest|replay|live)\b.*?buttons=(\d+) lx=(\d+) ly=(\d+) rx=(\d+) ry=(\d+).*?host_ms=(\d+) ee_tick=(\d+)')
def native_events(text):
 events=[]
 for line in text.splitlines():
  if not re.search(r'\[pad trace\] stage=(guest|replay|live)\b',line):continue
  m=PATTERN.search(line)
  if not m:raise ValueError('Incomplete native sampling event')
  stage,*values=m.groups();b,lx,ly,rx,ry,host,tick=map(int,values)
  events.append({'stage':stage,'state':(b,lx,ly,rx,ry),'host_ms':host,'tick':tick,'stream_order':len(events)})
 if not events:raise ValueError('No native sampling events')
 return events
def main():
 run=ROOT/'artifacts/runs/architecture-input-clock-01';out=ROOT/'artifacts/architecture/timeline-01';out.mkdir(exist_ok=False)
 report=json.loads((run/'report.json').read_text());assert report['test_saves_unchanged']
 events=native_events((run/'stderr.txt').read_text(errors='replace'));rows=field_replay(events)
 fixture=out/'input.csv';fixture.write_text('begin,end,buttons,lx,ly,rx,ry\n'+''.join(','.join(map(str,r))+'\n' for r in rows))
 samples=[json.loads(x) for x in (run/'diagnostics/state.jsonl').read_text().splitlines()]
 timeline=[]
 for e in events:timeline.append({'kind':'native-pad-sample','clock':'ee-vsync-field','ee_tick':e['tick'],'ee_cycle':None,'iop_tick':None,'host_ms':e['host_ms'],'source_stream':'pad','stream_order':e['stream_order'],'stage':e['stage'],'state':e['state']})
 for i,s in enumerate(samples):timeline.append({'kind':'diagnostic-frame','clock':'ee-vsync-field','ee_tick':s['ee_vsync_tick'],'ee_cycle':s['cycle'],'iop_tick':None,'host_elapsed_seconds':s['elapsed_seconds'],'source_stream':'diagnostics','stream_order':i,'host_present_tick':s['tick'],'presentation':s.get('presentation_vsync_tick')})
 # Ordering is partial: stream order is known; events in different streams in
 # one field are not assigned a fabricated causal order or interpolated cycles.
 (out/'events.json').write_text(json.dumps(timeline,indent=2))
 sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 manifest={'elf_sha256':report['elf_sha256'],'recording_runner_sha256':report['runner_sha256'],'starting_cards':report['saves_before'],'source_input_sha256':report['input_sha256'],'fixture_sha256':sha(fixture),'source_log_sha256':sha(run/'stderr.txt'),'timeline_sha256':sha(out/'events.json'),'native_events':len(events),'active_intervals':len(rows),'clock_policy':'Absolute EE VSync fields, half-open [begin,end); no interpolation, no analog quantization. Same-field cross-stream causal order and sub-field changes are not represented.',
 'controller_contract':'Buttons and four exact byte axes. Physical analog pressure is not captured by existing logger; do not claim pressure-equivalent replay.',
 'starting_state':'Copied private Saves001 card; room identity must be established independently, not inferred from input replay',
 'unavailable':['Pad-event EE cycles','IOP ticks','Per-event DMA/SIF/audio guest timing','Full pressure payload','Fresh manual route to room101'],
 'expected_checkpoints':[{'ee':s['ee_vsync_tick'],'host_elapsed':s['elapsed_seconds'],'frame':s['tick'],'presentation':s.get('presentation_vsync_tick')} for s in samples if 4780<=s['ee_vsync_tick']<=5520]}
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2));print('Captured genuine nonzero native ticks; built',len(rows),'lossless input intervals')
if __name__=='__main__':main()

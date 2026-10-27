"""Finalize the ended human session, retaining raw input and replay limitations."""
from pathlib import Path
import hashlib,json,sys,struct,collections
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from architecture_timeline import native_events
from replay_input_quality import field_replay
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
run=ROOT/'artifacts/runs/host-boundary-manual-01';out=run/'final-evidence';out.mkdir(exist_ok=False)
report=json.loads((run/'report.json').read_text());assert report['terminated_at_requested_stop'] and report['process_exit_observed'] and report['test_saves_unchanged']
observations=[json.loads(x) for x in (run/'host-watch/observations.jsonl').read_text().splitlines()]
transitions=[];prior=None;matching=[]
for i,row in enumerate(observations):
    room=row['room']['room_dispatch_argument_u16'];object_room=struct.unpack_from('<H',bytes.fromhex(row['room']['room_data_bytes_hex']),14)[0]
    if room!=prior:transitions.append({'index':i,'from':prior,'to':room,'host_qpc':row['host_qpc'],'diagnostic':row.get('diagnostic')});prior=room
    if room==257 and object_room==257 and row['room']['game_pointer_stable']:matching.append(i)
assert any(x['from']==256 and x['to']==257 for x in transitions)
assert len(matching)>=30 and matching==list(range(matching[0],matching[-1]+1))
events=native_events((run/'stderr.txt').read_text(errors='replace'));(out/'native-input-events.json').write_text(json.dumps(events,indent=2))
conflicts=[];last={}
for event in events:
    tick=event['tick']
    if tick in last and event['state']!=last[tick]['state']:conflicts.append([last[tick],event])
    last[tick]=event
(out/'same-field-conflicts.json').write_text(json.dumps(conflicts,indent=2))
try:field_replay(events);replay_error=None
except ValueError as error:replay_error=str(error)
frames=[{'file':p.name,'sha256':sha(p)} for p in sorted((run/'diagnostics').glob('frame-*.png'),key=lambda p:int(p.stem.split('-')[-1]))]
(out/'frames.json').write_text(json.dumps(frames,indent=2))
sources=[run/'identity.json',run/'report.json',run/'diagnostics/state.jsonl',run/'stdout.txt',run/'stderr.txt',run/'host-watch/observations.jsonl']
result={'runner_sha256':report['runner_sha256'],'elf_sha256':report['elf_sha256'],'transitions':transitions,'matching_room101_observations':len(matching),'first_matching_observation':matching[0],'last_matching_observation':matching[-1],'room_contract':'Stable pG pointer, dispatch argument and RoomData u16 at offset0xE both0x101; raw non-atomic observations retained',
        'native_input_events':len(events),'native_guest_ticks_nonzero':any(e['tick'] for e in events),'same_field_conflicts':len(conflicts),'field_replay_valid':replay_error is None,'field_replay_error':replay_error,'frames':len(frames),'files':{str(p.relative_to(run)):sha(p) for p in sources},'private_card_unchanged':True,
        'limitations':['Human reported village enemies; monitored final images remained outer forest, so no independently verified village/combat acceptance','No new campaign save/restart/reload in this run','No persistent arbitrary-location quicksave exists','Host playback and AV synchronization are not proven'],'scope':'Actual new human gameplay evidence, not candidate performance acceptance. No RAM writes or fabricated navigation.'}
(out/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='files'},indent=2))

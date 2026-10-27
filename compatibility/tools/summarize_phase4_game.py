"""Validate bounded runs and matching guest-field speed; retain private evidence."""
from pathlib import Path
import hashlib,json,struct,sys,wave
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reference-tools/tools/diagnostics'))
from game_speed_compare import endpoint,HZ

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def summarize(name):
    run=ROOT/'artifacts/runs'/name
    report=json.loads((run/'report.json').read_text())
    assert report['terminated_at_planned_timeout'] and report['test_saves_unchanged']
    assert sha(run/'guest/ps2EntryRunner.exe')==report['runner_sha256']
    assert sha(run/'guest/SLUS_211.34')==report['elf_sha256']
    assert sha(run/'input.csv')==report['input_sha256']
    rows=[json.loads(line) for line in (run/'diagnostics/state.jsonl').read_text().splitlines()]
    assert all(a['elapsed_seconds']<b['elapsed_seconds'] and a['ee_vsync_tick']<=b['ee_vsync_tick'] for a,b in zip(rows,rows[1:]))
    start,sb=endpoint(rows,3300);end,eb=endpoint(rows,3900)
    seconds=600/HZ
    result={'runner_sha256':report['runner_sha256'],'elf_sha256':report['elf_sha256'],
        'input_sha256':report['input_sha256'],'saves_before':report['saves_before'],
        'settings':report['settings'],'speed':seconds/(end-start),'wall_seconds':end-start,
        'endpoint_bounds':[sb,eb],'speed_bounds':[seconds/(eb[1]-sb[0]),seconds/(eb[0]-sb[1])],
        'peak_rss_bytes':report['peak_rss_bytes'],'host_cpu_last_sample':report['host_cpu_last_sample'],
        'last_guest_field':rows[-1]['ee_vsync_tick'],'frame_manifest':[]}
    for frame in sorted((run/'diagnostics').glob('frame-*.png')):
        tick=int(frame.stem.split('-')[1]);state=next((r for r in rows if r['tick']==tick),None)
        result['frame_manifest'].append({'name':frame.name,'sha256':sha(frame),'ee_vsync_tick':state['ee_vsync_tick'] if state else None})
    observation=run/'phase4-controls-observations.json'
    if observation.exists():
        o=json.loads(observation.read_text());assert o['completed'] and not o['error']
        assert o['runner_sha256']==report['runner_sha256'] and o['elf_sha256']==report['elf_sha256']
        positions=[struct.unpack_from('<3f',bytes.fromhex(r['player_bytes_hex']),192) for r in o['observations']]
        result['observer']={'samples':len(positions),'unique_positions':len(set(positions)),
            'first_position':positions[0],'last_position':positions[-1],
            'rooms':sorted({r['room_state']['room_dispatch_argument_u16'] for r in o['observations']}),
            'scope':'Read-only position interpretation; no atomic full-state snapshot or new transition proof'}
    witness=run/'diagnostics/vif-fast-witness.json';assert json.loads(witness.read_text())['entered']
    result['vif_fast_entered']=True
    return result

def main():
    base=summarize('phase4-clean-base-01');candidate=summarize('phase4-candidate-01')
    for key in ('elf_sha256','input_sha256','saves_before'):assert base[key]==candidate[key],key
    paths={'PS2X_NATIVE_PAD_REPLAY','PS2X_CAPTURE_DIR','PS2X_AUDIO_WAV','PS2X_VIF1_FAST_WITNESS'}
    assert {k:v for k,v in base['settings'].items() if k not in paths}=={k:v for k,v in candidate['settings'].items() if k not in paths}
    assert paths<=base['settings'].keys() and paths<=candidate['settings'].keys()
    result={'baseline':base,'candidate':candidate,'from_ee':3300,'to_ee':3900,'guest_vsync_hz':HZ,
        'relative_change_percent':(candidate['speed']/base['speed']-1)*100,
        'relative_change_bounds_percent':[(candidate['speed_bounds'][0]/base['speed_bounds'][1]-1)*100,
            (candidate['speed_bounds'][1]/base['speed_bounds'][0]-1)*100],
        'controlled_gain_proven':False,'scope':'One cold pair, sampled guest progress, not per-frame GPU timing. No new controls/profiler/RAM reader in the comparison interval.'}
    extra=ROOT/'artifacts/runs/phase4-controls-reference-02/report.json'
    if extra.exists():
        reference=summarize('phase4-controls-reference-02');result['control_reference']=reference
        for key in ('elf_sha256','input_sha256','saves_before'):assert reference[key]==candidate[key]
        a={f['ee_vsync_tick']:f for f in reference['frame_manifest']}
        b={f['ee_vsync_tick']:f for f in candidate['frame_manifest']}
        common=sorted(set(a)&set(b));same=[ee for ee in common if a[ee]['sha256']==b[ee]['sha256']]
        result['same_guest_field_images']={'matched':len(common),'identical_png_sha256':len(same),
            'after_control_inputs_identical':len([ee for ee in same if ee>=4800]),
            'scope':'Sparse exact-EE screenshot agreement only; not every-frame or full GS correctness'}
        audio={}
        for name in ('phase4-controls-reference-02','phase4-candidate-01'):
            path=ROOT/'artifacts/runs'/name/'diagnostics/audio-spu2.wav'
            with wave.open(str(path)) as stream:
                pcm=stream.readframes(stream.getnframes())
                audio[name]={'declared_frames':stream.getnframes(),'pcm_bytes':len(pcm),
                    'declared_pcm_sha256':hashlib.sha256(pcm).hexdigest(),
                    'file_sha256':sha(path),'file_bytes':path.stat().st_size}
            riff_end=struct.unpack_from('<I',path.read_bytes(),4)[0]+8
            audio[name]['bytes_after_declared_riff']=path.stat().st_size-riff_end
        result['audio_pcm_comparison']=audio
        result['audio_capture_limit']='Planned hard stop left trailing bytes beyond RIFF declarations; compare declared PCM only, not the unfinalized tails or host device loopback.'
    output=ROOT/'artifacts/phase4/game-acceptance/final-evidence.json'
    output.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('baseline','candidate','control_reference')},indent=2))
if __name__=='__main__':main()

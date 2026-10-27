"""Review all retained measurements; do not turn partial captures into full AV proof."""
from pathlib import Path
import collections,hashlib,json,random,re,statistics,struct,wave
from PIL import Image
from architecture_ammo import packed_counter
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/host-boundary/final-review-01';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())
parent=ROOT/'artifacts/host-boundary/game-performance-02/report.json';repair=ROOT/'artifacts/host-boundary/game-performance-03/report.json'
original=read(parent);replacement=read(repair);assert original['completed'] and replacement['completed']
rows=[r for r in original['runs'] if r['pair']!=4]+replacement['runs'];assert len(rows)==14
summary={'report_sources':{str(p):sha(p) for p in [parent,repair,ROOT/'artifacts/host-boundary/measurement-plan-02.json']},'excluded_original_pair4':{'reason':'Reference observer failed before its monitoring loop; replacement was preregistered regardless of speed','rows':[r for r in original['runs'] if r['pair']==4]},'primary_runs':rows}
pairs=[]
for pair in range(7):
    a=next(r for r in rows if r['pair']==pair and r['mode']=='0');b=next(r for r in rows if r['pair']==pair and r['mode']=='1')
    identities=[read(Path(x['run'])/'report.json') for x in (a,b)]
    for key in ('elf_sha256','input_sha256','saves_before'):assert identities[0][key]==identities[1][key],key
    for identity in identities:assert identity['process_exit_observed'] and identity['test_saves_unchanged']
    normalize=lambda s:{k:v for k,v in s.items() if k not in ('PS2X_CAPTURE_DIR','PS2X_NATIVE_PAD_REPLAY','PS2X_AUDIO_WAV','PS2X_VIF1_FAST_WITNESS')}
    assert normalize(identities[0]['settings'])==normalize(identities[1]['settings'])
    pairs.append({'pair':pair,'reference_speed':a['speed'],'candidate_speed':b['speed'],'gain_percent':100*(b['speed']/a['speed']-1),'conservative_gain_bounds':[100*(b['bounds'][0]/a['bounds'][1]-1),100*(b['bounds'][1]/a['bounds'][0]-1)]})
gains=[p['gain_percent'] for p in pairs];rng=random.Random(0xB0A7);boot=sorted(statistics.median(rng.choices(gains,k=7)) for _ in range(10000))
summary['performance']={'pairs':pairs,'positive_pairs':sum(x>0 for x in gains),'median_paired_gain_percent':statistics.median(gains),'bootstrap_median_95_percent':[boot[249],boot[9749]],'conservative_median_gain_bounds':[statistics.median(p['conservative_gain_bounds'][0] for p in pairs),statistics.median(p['conservative_gain_bounds'][1] for p in pairs)],'method':'Same3300..3900 guest interval; central endpoints interpolated between diagnostic samples with actual bracketing bounds retained. No controller-time interpolation. Bootstrap is descriptive with only7pairs.'}
for mode,name in [('0','reference'),('1','candidate')]:
    values=[r['speed'] for r in rows if r['mode']==mode];summary['performance'][name]={'median_speed':statistics.median(values),'sample_stddev':statistics.stdev(values),'variance':statistics.variance(values),'range':[min(values),max(values)],'median_peak_rss':statistics.median(r['peak_rss_bytes'] for r in rows if r['mode']==mode)}
(out/'performance.json').write_text(json.dumps(summary,indent=2));print('Performance',json.dumps(summary['performance'],indent=2),flush=True)

# Frame contracts are declared here, before comparing any image contents.
contracts={'guest-and-presentation-counters':['ee_vsync_tick','presentation_vsync_tick','presentation_source_fbp','presentation_pmode','presentation_smode2','display_flips','gif','gs_writes'],
           'presentation-only':['presentation_vsync_tick','presentation_source_fbp','presentation_pmode','presentation_smode2','display_flips']}
cache={};invalid=[]
def pixels(path):
    key=str(path)
    if key not in cache:
        try:
            with Image.open(path) as im:im.verify()
            with Image.open(path) as im:cache[key]={'size':im.size,'pixel_sha256':hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest(),'file_sha256':sha(path)}
        except Exception as error:invalid.append({'file':key,'error':str(error)});cache[key]=None
    return cache[key]
frame_results={name:[] for name in contracts}
for pair in range(7):
    runs=[Path(next(r['run'] for r in rows if r['pair']==pair and r['mode']==mode)) for mode in ('0','1')]
    all_states=[[json.loads(x) for x in (run/'diagnostics/state.jsonl').read_text().splitlines()] for run in runs]
    for name,fields in contracts.items():
        maps=[]
        for run,states in zip(runs,all_states):
            found=collections.defaultdict(list)
            for state in states:
                if not 3300<=state['ee_vsync_tick']<=5460 or not state.get('host_frame') or any(f not in state for f in fields):continue
                path=run/'diagnostics'/f"frame-{state['tick']}.png"
                if path.exists():found[tuple(state[f] for f in fields)].append(path)
            maps.append(found)
        result={'pair':pair,'fields':fields,'common_keys':0,'matches':0,'differences':[],'ambiguous_keys':[]}
        for key in sorted(set(maps[0])&set(maps[1])):
            result['common_keys']+=1;sets=[]
            for side in maps:
                values=[pixels(p) for p in side[key]];sets.append({(tuple(v['size']),v['pixel_sha256']) for v in values if v})
            if any(len(s)!=1 for s in sets):result['ambiguous_keys'].append(list(key));continue
            if sets[0]==sets[1]:result['matches']+=1
            else:result['differences'].append({'key':list(key),'files':[[str(p) for p in side[key]] for side in maps]})
        frame_results[name].append(result)
graphics={'contracts':frame_results,'invalid_compared_images':invalid,'scope':'Decoded RGBA equality at declared diagnostic/presentation tags; metadata/capture not atomic, not a complete live EE/IOP/VRAM state equivalence proof. Differences are retained, never removed to pass.'}
(out/'graphics.json').write_text(json.dumps(graphics,indent=2));print('Graphics',[(name,sum(r['matches'] for r in results),sum(len(r['differences']) for r in results)) for name,results in frame_results.items()],flush=True)

audio={};ammo={}
for mode in ('0','1'):
    run=ROOT/f'artifacts/runs/host-boundary-perf-6-{mode}';text=(run/'stderr.txt').read_text(errors='replace')
    counters=[dict(zip(('requested','delivered','underrun','tempo'),(int(a),int(b),int(c),float(d)))) for a,b,c,d in re.findall(r'\[audio\] requested=(\d+) delivered=(\d+) underrun=(\d+) tempo=([\d.]+)',text)]
    assert counters and all(r['requested']==r['delivered']+r['underrun'] for r in counters)
    wavs={}
    for name in ('audio-spu2.wav','audio-out.wav'):
        path=run/'diagnostics'/name;data=path.read_bytes()
        assert data[:4]==b'RIFF' and data[8:16]==b'WAVEfmt ' and data[36:40]==b'data'
        with wave.open(str(path),'rb') as wav:
            frames=wav.getnframes();body=wav.readframes(frames);fmt=[wav.getnchannels(),wav.getsampwidth(),wav.getframerate()]
        assert fmt==[2,2,48000] and len(body)==frames*4
        wavs[name]={'format':fmt,'committed_frames':frames,'file_sha256':sha(path),'committed_pcm_sha256':hashlib.sha256(body).hexdigest(),'bytes_beyond_declared_riff':len(data)-(struct.unpack_from('<I',data,4)[0]+8)}
    audio[mode]={'counters':counters,'last':counters[-1],'wavs':wavs}
    folder=run/'phase5-ammo';capture=read(folder/'report.json');assert capture['completed'];observed=[]
    for sample in capture['snapshots']:
        path=folder/(sample['label']+'.bin');memory=path.read_bytes();assert len(memory)==0x2000000 and sha(path)==sample['sha256']
        observed.append({'label':sample['label'],'diagnostic_ee_before':sample['before']['ee'],'diagnostic_ee_after':sample['after']['ee'],**packed_counter(memory,0x3ce154,0x23)})
    ammo[mode]=observed
paths=[ROOT/f'artifacts/runs/host-boundary-perf-6-{mode}/diagnostics/audio-spu2.wav' for mode in ('0','1')]
payloads=[]
for path in paths:
    with wave.open(str(path),'rb') as wav:payloads.append(wav.readframes(wav.getnframes()))
common=min(map(len,payloads));first=next((i for i,(a,b) in enumerate(zip(*payloads)) if a!=b),None)
audio['raw_pcm_comparison']={'common_bytes':common,'common_stereo_frames':common//4,'prefix_equal':first is None,'first_different_byte':first,'scope':'Committed WAV prefix only, sample origin not guest-event synchronized; not proof of speaker playback or AV synchronization. Periodic header updates may leave trailing data after hard process stop.'}
(out/'audio.json').write_text(json.dumps(audio,indent=2));(out/'ammo.json').write_text(json.dumps(ammo,indent=2));print('PCM prefix',audio['raw_pcm_comparison'],flush=True);print('Ammo',{mode:[r['counter'] for r in values] for mode,values in ammo.items()},flush=True)

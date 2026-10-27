"""Summarize existing controlled measurements without rerunning or selecting pairs."""
from pathlib import Path
import hashlib,json,random,statistics,wave
ROOT=Path(__file__).resolve().parents[1]
load=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def main():
 out=ROOT/'artifacts/phase5'/(__import__('sys').argv[1] if len(__import__('sys').argv)>1 else 'final-analysis-01');out.mkdir(exist_ok=False)
 perf=ROOT/'artifacts/phase5/game-performance-01';r=load(perf/'report.json')
 gains=r['paired_speed_gain_percent'];rng=random.Random(0x51f15eed)
 boot=sorted(statistics.median(rng.choices(gains,k=7)) for _ in range(20000))
 result={'scope':'All seven preselected pairs; descriptive bootstrap with only seven dependent scene pairs, not proof of an effect',
 'paired_gains_percent':gains,'median_paired_gain_percent':statistics.median(gains),
 'paired_gain_sample_sd_percent':statistics.stdev(gains),'bootstrap_median_95_percentile_interval_percent':[boot[500],boot[19499]],
 'baseline_median_speed':r['baseline_median_speed'],'candidate_median_speed':r['candidate_median_speed'],
 'decision':'Whole-game gain inconclusive; candidate stays opt-in and is not promoted','runs':[]}
 for row in r['runs']:
  mode=row['mode'];m=load(perf/(Path(row['run']).name+'.meters.json'));m=[x for x in m if 3300<=x['ee']<=3900]
  cpu=100*((m[-1]['user']+m[-1]['system'])-(m[0]['user']+m[0]['system']))/(m[-1]['host_elapsed']-m[0]['host_elapsed'])
  result['runs'].append(dict(row,process_cpu_percent_of_one_core=cpu,window_rss_median_bytes=statistics.median(x['rss'] for x in m),
    host_total_cpu_median_percent=statistics.median(x['host_total_cpu_percent'] for x in m)))
 result['groups']={}
 for mode in ('0','1'):
  rows=[x for x in result['runs'] if x['mode']==mode]
  gpu=load(ROOT/f'artifacts/phase5/gpu-observations-02/{mode}.json')
  gpu3d=[x['CookedValue'] for x in gpu['samples'] if x['InstanceName'].lower().endswith('engtype_3d')]
  result['groups'][mode]={'speed_sample_sd':statistics.stdev(x['speed'] for x in rows),
   'median_process_cpu_percent_of_one_core':statistics.median(x['process_cpu_percent_of_one_core'] for x in rows),
   'median_window_rss_bytes':statistics.median(x['window_rss_median_bytes'] for x in rows),
   'post_window_gpu_3d_mean_percent':statistics.mean(gpu3d),'post_window_gpu_3d_max_percent':max(gpu3d),
   'gpu_scope':gpu['scope']}
 # Join frames by BOTH guest and presentation fields; PNG equality is a separate observation.
 def frames(run):
  d={}
  for line in (run/'diagnostics/state.jsonl').read_text().splitlines():
   s=json.loads(line);p=run/f"diagnostics/frame-{s['tick']}.png"
   if p.exists():d[(s['ee_vsync_tick'],s.get('presentation_vsync_tick'))]=(p,s)
  return d
 base=frames(ROOT/'artifacts/runs/phase5-perf-6-0');cand=frames(ROOT/'artifacts/runs/phase5-perf-6-1')
 comparisons=[]
 for key in sorted(base.keys()&cand.keys()):
  a,sa=base[key];b,sb=cand[key];ah=sha(a);bh=sha(b)
  comparisons.append({'ee':key[0],'presentation':key[1],'baseline':str(a),'candidate':str(b),
   'baseline_sha256':ah,'candidate_sha256':bh,'identical':ah==bh,'baseline_elapsed':sa['elapsed_seconds'],'candidate_elapsed':sb['elapsed_seconds']})
 result['frames']={'contract':'Equal EE/presentation counters are necessary but do not prove all guest RAM is equal',
  'matched_counter_pairs':len(comparisons),'identical_pngs':sum(x['identical'] for x in comparisons),'pairs':comparisons}
 approved=frames(ROOT/'artifacts/runs/phase4-controls-reference-02');ap=[]
 for key in sorted(approved.keys()&cand.keys()):
  a,sa=approved[key];b,sb=cand[key];ah=sha(a);bh=sha(b)
  ap.append({'ee':key[0],'presentation':key[1],'approved':str(a),'candidate':str(b),'approved_sha256':ah,'candidate_sha256':bh,'identical':ah==bh})
 result['approved_runner_frames']={'scope':'Historical approved runner, same ELF/input/card; no claim of concurrent paired speed test',
  'matched_counter_pairs':len(ap),'identical_pngs':sum(x['identical'] for x in ap),'pairs':ap}
 # Audio payloads follow RIFF-declared PCM, excluding unfinalized tails after bounded termination.
 audio=[]
 for kind in ('spu2','out'):
  paths=[ROOT/f'artifacts/runs/phase5-perf-6-{mode}/diagnostics/audio-{kind}.wav' for mode in ('0','1')]
  payload=[];rows=[]
  for p in paths:
   with wave.open(str(p),'rb') as w:
    data=w.readframes(w.getnframes());payload.append(data);rows.append({'path':str(p),'file_sha256':sha(p),
     'declared_frames':w.getnframes(),'rate':w.getframerate(),'channels':w.getnchannels(),'width':w.getsampwidth(),
     'declared_pcm_sha256':hashlib.sha256(data).hexdigest(),'file_bytes':p.stat().st_size,'declared_pcm_bytes':len(data)})
  n=min(map(len,payload));prefix_equal=payload[0][:n]==payload[1][:n]
  audio.append({'kind':kind,'recordings':rows,'common_declared_pcm_bytes':n,'common_declared_pcm_equal':prefix_equal,
    'scope':'Guest PCM/output recording comparison; not host speaker loopback or audiovisual synchronization'})
 result['audio_payloads']=audio
 result['total_controlled_run_seconds']=sum(load(Path(x['run'])/'report.json')['seconds'] for x in r['runs'])
 (out/'report.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k not in ('runs','frames','audio_payloads')},indent=2))
 print('Frame pairs',len(comparisons),'identical',sum(x['identical'] for x in comparisons))
 print('PCM equal',[x['common_declared_pcm_equal'] for x in audio])
if __name__=='__main__':main()

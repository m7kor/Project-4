"""Seven alternating net-reference pairs on a newly captured real RE4 workload."""
from pathlib import Path
import hashlib,json,os,random,statistics,subprocess,sys,time
import psutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture/benchmark-01';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert json.loads((ROOT/'artifacts/architecture/equivalence-03/report.json').read_text())['passed']
gate=ROOT/'artifacts/architecture'/('full-gate-02' if len(sys.argv)==1 else sys.argv[1])/'report.json'
assert json.loads(gate.read_text())['passed']
run=ROOT/'artifacts/runs/architecture-input-clock-01';assert json.loads((run/'report.json').read_text())['test_saves_unchanged']
trace=run/'diagnostics/vu-commands';meta=[json.loads(x) for x in (trace/'manifest.jsonl').read_text().splitlines()]
assert any(x['kind']=='complete' for x in meta),'Incomplete actual game workload'
records=[x for x in meta if x['kind']=='command'];assert records
inputs={str(trace/x['file']):sha(trace/x['file']) for x in records};inputs[str(trace/'manifest.jsonl')]=sha(trace/'manifest.jsonl')
baseline=ROOT/'lab/phase4-suite-02/ps2x_vu1_bench.exe';candidate=ROOT/'lab/architecture-aot-02/ps2x_vu1_bench.exe';probe=ROOT/'lab/architecture-aot-state-02/state_probe.exe'
assert sha(candidate)==json.loads((candidate.parent/'identity.json').read_text())[candidate.name]
assert sha(baseline)=='75f8c403b362f87403714d4d1808b9549b767302f896e1d73de51cb50b49dfd5'
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
report={'passed':False,'rows':[],'inputs':inputs,'reference_sha256':sha(baseline),'candidate_sha256':sha(candidate),'scope':'Actual current RE4 command capture, net Phase4 reference comparison. Each process verifies once, then times one warm replay; five trials per side, seven alternating pairs. Not game FPS.'};start=time.monotonic()
try:
 # New current workload must independently pass golden and full-state comparison.
 logs=[]
 for mode in ('0','1'):
  log=out/(mode+'.current.states.txt');p=subprocess.run([str(probe),'--commands',str(trace),'--repeat','1'],cwd=out,env={**env,'PS2X_VU1_AOT_COVERAGE':mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=90)
  (out/(mode+'.current.stdout.txt')).write_text(p.stdout+p.stderr);assert p.returncode==0,p.stderr;logs.append(sha(log))
 assert logs[0]==logs[1],'New actual workload full state differs'
 report['current_workload_full_state_sha256']=logs[0]
 for pair in range(7):
  for mode in (('0','1') if pair%2==0 else ('1','0')):
   for proc in psutil.process_iter(['name']):
    if (proc.info['name'] or '').lower() in ('lld-link.exe','clang-cl.exe','cl.exe','link.exe','ps2entryrunner.exe'):raise RuntimeError('Heavy build/game active; measurement refused')
   trials=[]
   for trial in range(5):
    p=subprocess.run([str(candidate if mode=='1' else baseline),'--commands',str(trace),'--repeat','2','--timing-after-verify'],cwd=out,env={**env,'PS2X_VU1_AOT_COVERAGE':mode},capture_output=True,text=True,timeout=60)
    stem=f'{pair}-{mode}-{trial}';(out/(stem+'.stdout.txt')).write_text(p.stdout);(out/(stem+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,p.stderr
    row=json.loads(p.stdout.strip().splitlines()[-1]);assert row['commands']==len(records) and row['gif_verified_passes']==1 and row['timing_excludes_gif_hash'];trials.append(row)
   report['rows'].append({'pair':pair,'mode':mode,'median_ns_per_cycle':statistics.median(x['ns_per_cycle'] for x in trials),'trials':trials});print('Bench side completed',pair,mode,flush=True)
 gains=[]
 for pair in range(7):
  a,b=[next(x['median_ns_per_cycle'] for x in report['rows'] if x['pair']==pair and x['mode']==mode) for mode in ('0','1')];gains.append((a-b)/a*100)
 report.update(passed=True,paired_cost_reduction_percent=gains,median_cost_reduction_percent=statistics.median(gains),all_pairs_improved=all(x>0 for x in gains),reference_median_ns_per_cycle=statistics.median(x['median_ns_per_cycle'] for x in report['rows'] if x['mode']=='0'),candidate_median_ns_per_cycle=statistics.median(x['median_ns_per_cycle'] for x in report['rows'] if x['mode']=='1'))
finally:
 report['seconds']=time.monotonic()-start;(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ('rows','inputs')},indent=2))

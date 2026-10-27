"""Seven alternating net A/B pairs; refuse active gameplay/build/profiling."""
from pathlib import Path
import hashlib,json,os,statistics,subprocess,time,psutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/host-boundary/benchmark-01';out.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert json.loads((ROOT/'artifacts/host-boundary/equivalence-01/report.json').read_text())['passed']
assert json.loads((ROOT/'artifacts/runs/host-boundary-manual-01/report.json').read_text())['process_exit_observed']
reference=ROOT/'lab/phase4-suite-02/ps2x_vu1_bench.exe';candidate=ROOT/'lab/host-boundary-inline-01/ps2x_vu1_bench.exe';probe=ROOT/'lab/host-boundary-probe-01/ps2x_vu1_bench.exe'
assert sha(reference)=='75f8c403b362f87403714d4d1808b9549b767302f896e1d73de51cb50b49dfd5'
assert sha(candidate)=='ad1d9722779cc171366e8123f7339dc74151971a3694d0adea0d9fb5f50f9d7e'
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
def idle():
    for p in psutil.process_iter(['name']):
        assert p.info['name'].lower() not in ('clang-cl.exe','lld-link.exe','ps2entryrunner.exe','state_probe.exe','xperf.exe'),p.info
def run(label,exe,trace,extra):
    idle();begin=time.perf_counter();p=subprocess.run([str(exe),'--commands',str(trace),'--repeat','2','--timing-after-verify'],cwd=out,env={**env,**extra},capture_output=True,text=True,timeout=60)
    (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,p.stderr
    result=json.loads(p.stdout.strip().splitlines()[-1]);result['process_wall_seconds']=time.perf_counter()-begin;return result
report={'completed':False,'rows':[],'reference_sha256':sha(reference),'candidate_sha256':sha(candidate),'probe_sha256':sha(probe),'host':{'processor':os.environ.get('PROCESSOR_IDENTIFIER'),'logical_cores':psutil.cpu_count(),'memory_bytes':psutil.virtual_memory().total},'scope':'Net recorded-workload host wall-time per guest cycle, not game speed. Five processes per side, one verified then one warm timed replay per process; raw samples retained.'};start=time.perf_counter()
try:
    for workload,trace in [('commands1024',ROOT/'artifacts/runs/architecture-input-clock-01/diagnostics/vu-commands'),('commands964',Path('C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands'))]:
        for pair in range(7):
            for mode in (('reference','candidate') if pair%2==0 else ('candidate','reference')):
                values=[run(f'{workload}-{pair}-{mode}-{i}',reference if mode=='reference' else candidate,trace,{}) for i in range(5)]
                report['rows'].append({'workload':workload,'pair':pair,'mode':mode,'median_ns_per_cycle':statistics.median(x['ns_per_cycle'] for x in values),'samples':values})
            print('Completed net pair',workload,pair,flush=True)
    report['summary']={}
    for workload in ('commands1024','commands964'):
        rows=[r for r in report['rows'] if r['workload']==workload];gains=[]
        for pair in range(7):
            a=next(r for r in rows if r['pair']==pair and r['mode']=='reference');b=next(r for r in rows if r['pair']==pair and r['mode']=='candidate')
            assert {x['state_result'] for x in a['samples']}=={x['state_result'] for x in b['samples']}
            gains.append(100*(1-b['median_ns_per_cycle']/a['median_ns_per_cycle']))
        report['summary'][workload]={'paired_cost_reductions_percent':gains,'median_paired_cost_reduction_percent':statistics.median(gains),'positive_pairs':sum(x>0 for x in gains),'reference_median_ns_per_cycle':statistics.median(r['median_ns_per_cycle'] for r in rows if r['mode']=='reference'),'candidate_median_ns_per_cycle':statistics.median(r['median_ns_per_cycle'] for r in rows if r['mode']=='candidate')}
    report['completed']=True
finally:
    report['seconds']=time.perf_counter()-start;(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report.get('summary',{}),indent=2),flush=True)

"""Measure observer perturbation separately; never call instrumented shares truth."""
from pathlib import Path
import hashlib,json,os,re,statistics,subprocess,time,psutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/host-boundary/probe-overhead-01';out.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
reference=ROOT/'lab/phase4-suite-02/ps2x_vu1_bench.exe';probe=ROOT/'lab/host-boundary-probe-01/ps2x_vu1_bench.exe'
assert sha(probe)==json.loads((probe.parent/'identity.json').read_text())[probe.name]
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
trace=ROOT/'artifacts/runs/architecture-input-clock-01/diagnostics/vu-commands';rows=[];start=time.perf_counter()
for pair in range(7):
    modes=['reference','off','counts','sample64'];modes=modes if pair%2==0 else list(reversed(modes))
    for mode in modes:
        for process in psutil.process_iter(['name']):assert process.info['name'].lower() not in ['ps2entryrunner.exe','clang-cl.exe','lld-link.exe','state_probe.exe','xperf.exe'],process.info
        values=[]
        for trial in range(3):
            extra={} if mode=='reference' else {'PS2X_HOST_BOUNDARY_PROBE':{'off':'0','counts':'1','sample64':'2'}[mode],'PS2X_HOST_BOUNDARY_PERIOD':'64'}
            p=subprocess.run([str(reference if mode=='reference' else probe),'--commands',str(trace),'--repeat','2','--timing-after-verify'],cwd=out,env={**env,**extra},capture_output=True,text=True,timeout=60)
            label=f'{pair}-{mode}-{trial}';(out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,p.stderr
            result=json.loads(p.stdout.strip().splitlines()[-1]);assert result['state_result']=='b093a718587fde57' and result['gif_packets']==1511
            values.append(result['ns_per_cycle'])
        rows.append({'pair':pair,'mode':mode,'median_ns_per_cycle':statistics.median(values),'trials':values})
    print('Observer overhead pair',pair,flush=True)
summary={}
for mode in ['off','counts','sample64']:
    ratios=[]
    for pair in range(7):
        a=next(x['median_ns_per_cycle'] for x in rows if x['pair']==pair and x['mode']=='reference');b=next(x['median_ns_per_cycle'] for x in rows if x['pair']==pair and x['mode']==mode);ratios.append(100*(b/a-1))
    summary[mode]={'median_net_slowdown_percent':statistics.median(ratios),'paired_slowdowns_percent':ratios}
report={'completed':True,'reference_sha256':sha(reference),'probe_sha256':sha(probe),'rows':rows,'summary':summary,'seconds':time.perf_counter()-start,
        'scope':'Observer code-layout/branch overhead includes the disabled mode; selected TSC timings are host ticks, not guest cycles or retired CPU cycles. Do not assign unprofiled percentages from perturbed bucket shares.'}
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(summary,indent=2))

"""Seven alternating matched command-replay pairs after correctness succeeds."""
from pathlib import Path
import json,subprocess,os,statistics,hashlib
ROOT=Path(__file__).resolve().parents[1]
parent=ROOT/'artifacts/experiments/vu-flag-coalescing'
assert json.loads((parent/'validation/summary.json').read_text())['all_matched']
out=parent/'timing';out.mkdir(exist_ok=False)
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1')
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
bins={'base':ROOT/'lab/shared-link/ps2x_vu1_bench.exe','flags':ROOT/'lab/flag-link/ps2x_vu1_bench.exe'}
trace='C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands'
rows=[]
for pair in range(7):
    for label in (('base','flags') if pair%2==0 else ('flags','base')):
        result=subprocess.run([str(bins[label]),'--commands',trace,'--repeat','50','--timing-after-verify'],cwd=out,env=env,capture_output=True,text=True,timeout=120)
        (out/(str(pair)+'-'+label+'.stdout.txt')).write_text(result.stdout);(out/(str(pair)+'-'+label+'.stderr.txt')).write_text(result.stderr)
        assert result.returncode==0,(pair,label,result.returncode,result.stderr[-500:])
        record=json.loads(result.stdout.strip().splitlines()[-1])
        assert (record['state_result'],record['cycles'],record['gif_packets'])==('a7a8b884d6fdb986',2077288,1385)
        rows.append({'pair':pair,'label':label,**record})
    print('Completed flag timing pair',pair,flush=True)
changes=[]
for pair in range(7):
    a=next(r for r in rows if r['pair']==pair and r['label']=='base')['ns_per_cycle']
    b=next(r for r in rows if r['pair']==pair and r['label']=='flags')['ns_per_cycle']
    changes.append((a-b)/a*100)
record={'scope':'Isolated recorded VU commands; GIF verified before timing, not gameplay FPS',
    'paired_cost_reduction_percent':changes,'median_cost_reduction_percent':statistics.median(changes),
    'base_median_ns_per_cycle':statistics.median(r['ns_per_cycle'] for r in rows if r['label']=='base'),
    'flags_median_ns_per_cycle':statistics.median(r['ns_per_cycle'] for r in rows if r['label']=='flags'),
    'rows':rows,'binary_sha256':{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in bins.items()}}
(out/'summary.json').write_text(json.dumps(record,indent=2))
print(json.dumps({k:v for k,v in record.items() if k not in ('rows','binary_sha256')},indent=2))

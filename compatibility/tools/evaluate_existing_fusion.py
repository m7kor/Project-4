"""Evaluate the discovered, unmerged VU candidate on the existing real-game command trace."""
from pathlib import Path
import subprocess,json,os,statistics,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-fusion'
trace=Path('C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands')
env={k:v for k,v in os.environ.items() if not k.startswith('PS2X_')}
env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1')
rows=[]
for pair in range(7):
    for label in (('base','candidate') if pair%2==0 else ('candidate','base')):
        cmd=[str(out/(label+'.exe')),'--commands',str(trace),'--repeat','25','--timing-after-verify']
        p=subprocess.run(cmd,cwd=out,env=env,capture_output=True,text=True,timeout=60)
        (out/(str(pair)+'-'+label+'.stdout.txt')).write_text(p.stdout)
        (out/(str(pair)+'-'+label+'.stderr.txt')).write_text(p.stderr)
        assert p.returncode==0,(label,p.stderr[-600:])
        record=json.loads(p.stdout.strip().splitlines()[-1]);record.update(pair=pair,label=label)
        assert record['state_result']=='a7a8b884d6fdb986' and record['cycles']==2077288 and record['gif_packets']==1385
        rows.append(record)
    print('Completed pair',pair,flush=True)
changes=[]
for pair in range(7):
    a=next(r for r in rows if r['pair']==pair and r['label']=='base')['ns_per_cycle']
    b=next(r for r in rows if r['pair']==pair and r['label']=='candidate')['ns_per_cycle']
    changes.append((a-b)/a*100)
result=dict(scope='Existing unmerged experimental VU fusion candidate; isolated trace replay only, not integrated RE4 or gameplay FPS',
            paired_cost_reduction_percent=changes,median_cost_reduction_percent=statistics.median(changes),
            baseline_median_ns_per_cycle=statistics.median(r['ns_per_cycle'] for r in rows if r['label']=='base'),
            candidate_median_ns_per_cycle=statistics.median(r['ns_per_cycle'] for r in rows if r['label']=='candidate'),rows=rows)
(out/'evaluation.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))

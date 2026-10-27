"""Verify the integrated runtime against original traces and budget/resume edge snapshots."""
from pathlib import Path
import subprocess,os,re,json
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-fusion/integrated-v2';out.mkdir(exist_ok=True)
base=ROOT/'lab/native-link/ps2x_vu1_bench.exe'
candidate=ROOT/'lab/fusion-link/ps2x_vu1_bench.exe'
env={k:v for k,v in os.environ.items() if not k.startswith('PS2X_')}
env['PS2X_VU1_CLEAN_BLOCKS']='1'
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
trace='C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands'
snapshots='C:/Project/PS2redmption/artifacts/verification/vu-clean-blocks-v41/edge-replay-v2/snapshots'
assert Path(snapshots).is_dir()
rows=[]
def execute(label,exe,arguments,settings):
    p=subprocess.run([str(exe),*arguments],cwd=out,env={**env,**settings},capture_output=True,text=True,timeout=60)
    (out/(label+'.stdout.txt')).write_text(p.stdout)
    (out/(label+'.stderr.txt')).write_text(p.stderr)
    assert p.returncode==0,(label,p.returncode,p.stderr[-500:])
    return p.stdout
for mode in ('0','1'):
    text=execute('commands-fused'+mode,candidate,['--commands',trace,'--repeat','1'],{'PS2X_VU1_FUSED':mode})
    record=json.loads(text.strip().splitlines()[-1])
    assert (record['state_result'],record['cycles'],record['gif_packets'])==('a7a8b884d6fdb986',2077288,1385)
    rows.append(dict(scope='commands',fused=mode,result=record))
for budget in (1,2,3,4,7,31,63,64,127,128,160,4096,65536):
    records=[]
    for label,exe,mode in [('base',base,'0'),('fusion-off',candidate,'0'),('fusion-on',candidate,'1')]:
        text=execute(str(budget)+'-'+label,exe,[snapshots,'--budget',str(budget),'--resumes','64','--repeat','1'],{'PS2X_VU1_FUSED':mode})
        state=re.search(r'result=([a-f0-9]{16})',text);cycles=re.search(r'vu1_cycles=(\d+)',text)
        assert state and cycles
        records.append(dict(label=label,state=state[1],cycles=int(cycles[1])))
    assert len({(r['state'],r['cycles']) for r in records})==1,(budget,records)
    rows.append(dict(scope='budget-resume',budget=budget,resumes=64,results=records))
    print('Matched budget',budget,flush=True)
(out/'semantic-verification.json').write_text(json.dumps(dict(scope='Integrated IMAGE2+fusion; no timing claim while linking',all_matched=True,rows=rows),indent=2))

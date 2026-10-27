"""Differential tests for the allocation mask against its scan fallback and golden commands."""
from pathlib import Path
import json,subprocess,os,re,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-queue-allocation/validation';out.mkdir(exist_ok=False)
new=ROOT/'lab/queue-link';base=ROOT/'lab/shared-link/ps2x_vu1_bench.exe'
manifest=json.loads((new/'identity.json').read_text())
for name in ('ps2x_tests.exe','ps2x_vu1_bench.exe'):
    assert hashlib.sha256((new/name).read_bytes()).hexdigest()==manifest[name]
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1')
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
def execute(label,exe,args,extra):
    p=subprocess.run([str(exe),*map(str,args)],cwd=ROOT/'engines/project4',env={**env,**extra},capture_output=True,text=True,timeout=120)
    (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr)
    assert p.returncode==0,(label,p.returncode,p.stderr[-500:])
    return p.stdout
units=[]
for allocation in ('0','1'):
    for commit in ('0','1'):
        text=execute(f'unit-{allocation}-{commit}',new/'ps2x_tests.exe',[],{'PS2X_VU1_ALLOC_SCAN':allocation,'PS2X_VU1_SCAN_ALL':commit})
        assert re.search(r'Passed:\s+633',text) and re.search(r'Failed:\s+0',text)
        units.append({'allocation_scan':allocation,'commit_scan':commit,'passed':633})
print('Four unit configurations passed',flush=True)
trace=Path('C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands')
command_rows=[]
workloads=[('actual',trace)]+[(f'edge-{budget}',Path('C:/Project/PS2redmption/artifacts/verification/vu-clean-blocks-v41/edge-replay-v2')/f'budget-{budget}'/'commands') for budget in (1,2,4,31,256,4096,65536)]
for label,folder in workloads:
    signatures=[]
    for allocation in ('0','1'):
        text=execute(label+'-'+allocation,new/'ps2x_vu1_bench.exe',['--commands',folder,'--repeat','1'],{'PS2X_VU1_ALLOC_SCAN':allocation})
        row=json.loads(text.strip().splitlines()[-1]);signatures.append(tuple(row[k] for k in ('state_result','cycles','gif_packets')))
        command_rows.append({'label':label,'allocation_scan':allocation,**row})
    assert signatures[0]==signatures[1]
    print('Golden commands matched',label,flush=True)
snapshots=[]
for folder in sorted((ROOT/'artifacts/experiments/vu-shared-regions/snapshots').iterdir()):
    for budget in (1,2,3,4,7,31,63,64,127,128,160,4096,65536):
        results=[]
        for label,exe,extra in [('base',base,{}),('mask',new/'ps2x_vu1_bench.exe',{'PS2X_VU1_ALLOC_SCAN':'0'}),('scan',new/'ps2x_vu1_bench.exe',{'PS2X_VU1_ALLOC_SCAN':'1'})]:
            text=execute(folder.name+'-'+str(budget)+'-'+label,exe,[folder,'--budget',budget,'--resumes','64','--repeat','1','--gif-hash'],extra)
            result={key:re.search(pattern,text)[1] for key,pattern in (
                ('state',r' result=([a-f0-9]{16})'),('cycles',r'vu1_cycles=(\d+)'),
                ('gif_packets',r'gif_packets=(\d+)'),('gif_result',r'gif_result=([a-f0-9]{16})'))}
            results.append({'label':label,**result})
        assert len({tuple(r[k] for k in ('state','cycles','gif_packets','gif_result')) for r in results})==1
        snapshots.append({'image':folder.name,'budget':budget,'results':results})
    print('State/cycles/GIF budgets matched',folder.name,flush=True)
record={'scope':'Allocation choice only, original timing and state golden verification','all_matched':True,
    'units':units,'commands':command_rows,'snapshots':snapshots,'binary_sha256':manifest}
(out/'summary.json').write_text(json.dumps(record,indent=2));print('Queue allocation validation complete',flush=True)

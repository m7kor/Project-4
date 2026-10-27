"""Validate expanded VU coverage on real snapshots, budgets, GIF and unit tests."""
from pathlib import Path
import json,subprocess,os,re,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
label=sys.argv[1] if len(sys.argv)>1 else 'validation'
assert label.replace('-','').isalnum()
out=ROOT/'artifacts/experiments/vu-shared-regions'/label;out.mkdir(exist_ok=False)
new=ROOT/'lab/shared-link';baseline=ROOT/'lab/fusion-link/ps2x_vu1_bench.exe'
manifest=json.loads((new/'identity.json').read_text())
for name in ('ps2x_tests.exe','ps2x_vu1_bench.exe'):
    assert hashlib.sha256((new/name).read_bytes()).hexdigest()==manifest[name]
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_TRACE_BLOCKS='1')
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
def execute(label,exe,args,fused):
    p=subprocess.run([str(exe),*args],cwd=ROOT/'engines/project4',env={**env,'PS2X_VU1_FUSED':fused},capture_output=True,text=True,timeout=120)
    (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr)
    assert p.returncode==0,(label,p.returncode,p.stderr[-500:])
    return p.stdout
units=[]
for fused in ('0','1'):
    text=execute('unit-'+fused,new/'ps2x_tests.exe',[],fused)
    assert re.search(r'Passed:\s+633',text) and re.search(r'Failed:\s+0',text)
    units.append({'fused':fused,'passed':633,'failed':0})
    print('Unit tests passed',fused,flush=True)
rows=[]
for folder in sorted((out.parent/'snapshots').iterdir()):
    for budget in (1,2,3,4,7,31,63,64,127,128,160,4096,65536):
        results=[]
        for label,exe,mode in [('stable',baseline,'1'),('shared-clean',new/'ps2x_vu1_bench.exe','0'),('shared-fused',new/'ps2x_vu1_bench.exe','1')]:
            text=execute(folder.name+'-'+str(budget)+'-'+label,exe,[str(folder),'--budget',str(budget),'--resumes','64','--repeat','1','--gif-hash'],mode)
            result={name:re.search(pattern,text)[1] for name,pattern in (
                ('state',r' result=([a-f0-9]{16})'),('cycles',r'vu1_cycles=(\d+)'),
                ('gif_packets',r'gif_packets=(\d+)'),('gif_result',r'gif_result=([a-f0-9]{16})'))}
            blocks=int(re.search(r'compiled_block_entries=(\d+)',text)[1])
            results.append({'label':label,**result,'block_entries':blocks})
        fields=('state','cycles','gif_packets','gif_result')
        assert len({tuple(r[k] for k in fields) for r in results})==1,(folder.name,budget,results)
        if budget==65536:assert results[-1]['block_entries']>0,('New path was not exercised',folder.name)
        rows.append({'image':folder.name,'budget':budget,'resumes':64,'results':results})
    print('Matched all budgets and GIF for',folder.name,flush=True)
trace='C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands'
for fused in ('0','1'):
    text=execute('commands-'+fused,new/'ps2x_vu1_bench.exe',['--commands',trace,'--repeat','1'],fused)
    record=json.loads(text.strip().splitlines()[-1])
    assert (record['state_result'],record['cycles'],record['gif_packets'])==('a7a8b884d6fdb986',2077288,1385)
(out/'summary.json').write_text(json.dumps({'scope':'Real captured snapshots for both aliases; isolated correctness, not gameplay speed',
    'all_matched':True,'unit_tests':units,'rows':rows,'legacy_commands':964,'binary_sha256':manifest},indent=2))
print('All expanded-coverage checks passed',flush=True)

"""Alternating matched real-snapshot costs after all builds/game probes finish."""
from pathlib import Path
import os,subprocess,json,re,statistics,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-shared-regions/timing';out.mkdir(exist_ok=False)
manifest=json.loads((ROOT/'lab/shared-link/identity.json').read_text())
assert 'ps2EntryRunner.exe' in manifest,'Do not benchmark during the link'
assert all((ROOT/'artifacts/runs'/name/'report.json').exists()
           for name in ('saved-load-01','saved-load-02','saved-load-03')),'Game probe still active'
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1')
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
binaries={'base':ROOT/'lab/fusion-link/ps2x_vu1_bench.exe','shared':ROOT/'lab/shared-link/ps2x_vu1_bench.exe'}
rows=[]
for folder in sorted((out.parent/'snapshots').iterdir()):
    for pair in range(7):
        for name in (('base','shared') if pair%2==0 else ('shared','base')):
            p=subprocess.run([str(binaries[name]),str(folder),'--repeat','25','--gif-hash'],cwd=out,env=env,capture_output=True,text=True,timeout=120)
            label=folder.name+'-'+str(pair)+'-'+name
            (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr)
            assert p.returncode==0,(label,p.returncode,p.stderr[-500:])
            fields={key:re.search(pattern,p.stdout)[1] for key,pattern in (
                ('ns_per_cycle',r'ns/cycle=([0-9.]+)'),('state',r' result=([a-f0-9]{16})'),
                ('cycles',r'vu1_cycles=(\d+)'),('gif_packets',r'gif_packets=(\d+)'),('gif_result',r'gif_result=([a-f0-9]{16})'))}
            rows.append({'image':folder.name,'pair':pair,'label':name,**fields})
    print('Completed seven pairs for',folder.name,flush=True)
results=[]
for image in sorted({r['image'] for r in rows}):
    group=[r for r in rows if r['image']==image]
    assert len({tuple(r[k] for k in ('state','cycles','gif_packets','gif_result')) for r in group})==1
    changes=[]
    for pair in range(7):
        a=float(next(r for r in group if r['pair']==pair and r['label']=='base')['ns_per_cycle'])
        b=float(next(r for r in group if r['pair']==pair and r['label']=='shared')['ns_per_cycle'])
        changes.append((a-b)/a*100)
    results.append({'image':image,'paired_cost_reduction_percent':changes,'median_reduction_percent':statistics.median(changes)})
record={'scope':'Isolated real-snapshot VU cost INCLUDING GIF hashing; not gameplay FPS or CPU-only VU arithmetic',
        'results':results,'rows':rows,'binary_sha256':{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in binaries.items()}}
(out/'summary.json').write_text(json.dumps(record,indent=2))
print(json.dumps({'results':results},indent=2))

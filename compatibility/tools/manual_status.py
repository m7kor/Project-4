"""Read only the owned manual session; persist compact monitoring evidence."""
from pathlib import Path
import json,re,time,sys
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs'/ (sys.argv[1] if len(sys.argv)>1 else 'manual-play-01')
assert run.parent==ROOT/'artifacts/runs'
def tail(path,limit=262144):
    with path.open('rb') as f:
        f.seek(0,2);size=f.tell();f.seek(max(0,size-limit));data=f.read()
    return data.decode('utf-8',errors='replace').splitlines()
rows=tail(run/'diagnostics/state.jsonl')
states=[]
for row in rows:
    try:states.append(json.loads(row))
    except ValueError:pass
logs=tail(run/'stderr.txt',1048576)
frames=sorted((run/'diagnostics').glob('frame-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
identity=json.loads((run/'identity.json').read_text())
record=dict(observed_unix=time.time(),pid=identity['pid'],manual=True,
    latest_frame=str(frames[-1]) if frames else None,
    recent_input=[s for s in logs if '[pad trace]' in s][-8:],
    recent_audio=[s for s in logs if '[audio]' in s][-1:],
    recent_faults=[s[:600] for s in logs if re.search(r'guest-branch:missing-target|runtime exception|access violation|\[terminate\]|VK_ERROR',s,re.I)],
    closed=(run/'report.json').exists())
if states:
    latest=states[-1]
    record['state']={k:latest.get(k) for k in ('elapsed_seconds','ee_vsync_tick','pc','dma','gif','vif','ipu_cmds')}
    earlier=next((s for s in reversed(states) if latest['elapsed_seconds']-s['elapsed_seconds']>=20),None)
    if earlier:record['recent_guest_speed']=(latest['ee_vsync_tick']-earlier['ee_vsync_tick'])/(latest['elapsed_seconds']-earlier['elapsed_seconds'])/(60000/1001)
try:
    import psutil
    p=psutil.Process(identity['pid']);record['rss_bytes']=p.memory_info().rss
except Exception:pass
with (run/'monitor.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
print(json.dumps(record,indent=2))

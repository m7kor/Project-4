"""Deterministic synthetic retirement/copy/reset gate for the stateless candidate."""
from pathlib import Path
import os,json,subprocess,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
fmac='--fmac' in sys.argv
requested_out=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--out=')),None)
out=Path(requested_out).resolve() if requested_out else ROOT/'artifacts/phase5'/('random-03' if fmac else 'random-02')
assert out.is_relative_to(ROOT/'artifacts');out.mkdir(exist_ok=False)
binary=ROOT/'lab'/('phase5-fmac-state-01' if fmac else 'phase5-vector-state-01')/'state_probe.exe'
probe_name=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--probe-dir=')),None)
if probe_name:binary=(ROOT/'lab'/probe_name/'state_probe.exe').resolve();assert binary.is_relative_to(ROOT/'lab')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for path,digest in json.loads((binary.parent/'identity.json').read_text()).items():assert sha(path)==digest
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
rows=[]
for mode in ('0','1'):
 log=out/(mode+'.state.txt')
 p=subprocess.run([str(binary),'--phase5-random'],cwd=out,env={**env,('PS2X_VU1_FMAC_CLASSIFY' if fmac else 'PS2X_VU1_VECTOR_RETIRE'):mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=60)
 (out/(mode+'.stdout.txt')).write_text(p.stdout+p.stderr);assert p.returncode==0
 rows.append({'mode':mode,'checkpoints':len(log.read_text().splitlines()),'sha256':sha(log)})
assert rows[0]['sha256']==rows[1]['sha256'] and rows[0]['checkpoints']==6144
(out/'report.json').write_text(json.dumps({'passed':True,'rows':rows,'binary_sha256':sha(binary),'seed':'0x51f15eed','scope':'512 synthetic queue sets x12, copies/controlReset; no game RAM writes'},indent=2));print(rows)

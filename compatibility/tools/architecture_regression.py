"""The minimized real-state regression must pass fixed and reject original AOT."""
from pathlib import Path
import hashlib,json,os,subprocess
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture/regression-01';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
fixture=ROOT/'artifacts/architecture/minimized-01/fixture';expected=json.loads((ROOT/'artifacts/architecture/minimized-01/report.json').read_text())['fixture_sha256'];assert sha(fixture/'vu1snap_00000.bin')==expected
rows=[]
for label,folder,should_equal in [('original-mutant','architecture-aot-state-01',False),('fixed','architecture-aot-state-02',True)]:
 binary=ROOT/'lab'/folder/'state_probe.exe'
 for p,h in json.loads((binary.parent/'identity.json').read_text()).items():assert sha(Path(p))==h,p
 logs=[]
 for mode in ('0','1'):
  log=out/(label+'-'+mode+'.states.txt');p=subprocess.run([str(binary),str(fixture),'--budget','65536','--repeat','1','--gif-hash'],cwd=out,env={**env,'PS2X_VU1_AOT_COVERAGE':mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=30)
  (out/(label+'-'+mode+'.stdout.txt')).write_text(p.stdout+p.stderr);assert p.returncode==0;logs.append(sha(log))
 equal=logs[0]==logs[1];assert equal==should_equal,(label,logs)
 rows.append({'case':label,'binary_sha256':sha(binary),'full_state_equal':equal,'expected_equal':should_equal,'hashes':logs})
(out/'report.json').write_text(json.dumps({'passed':True,'fixture_sha256':expected,'rows':rows,'scope':'Compiled negative control, no fields removed from original v2 observer; rejects sequence/scoreboard regression even when final visible state/GIF match'},indent=2));print('Minimized regression passed; original compiled defect detected')

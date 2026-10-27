"""Single captured-state reproducer with first labelled field divergence."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture/minimized-01';out.mkdir(exist_ok=False);fixture=out/'fixture';fixture.mkdir()
original=ROOT/'artifacts/phase5/fixtures/image-53c46ebcaf7db574/vu1snap_00000.bin';target=fixture/original.name;shutil.copyfile(original,target)
binary=ROOT/'lab/architecture-aot-detail-01/state_probe.exe';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for p,h in json.loads((binary.parent/'identity.json').read_text()).items():assert sha(Path(p))==h,p
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
for mode in ('0','1'):
 p=subprocess.run([str(binary),str(fixture),'--budget','65536','--resumes','0','--repeat','1','--gif-hash'],cwd=out,env={**env,'PS2X_VU1_AOT_COVERAGE':mode,'PS2X_VU1_DETAIL_LOG':str(out/(mode+'.fields.txt')),'PS2X_VU1_PIPELINE_STATE_LOG':str(out/(mode+'.states.txt'))},capture_output=True,text=True,timeout=30)
 (out/(mode+'.stdout.txt')).write_text(p.stdout);(out/(mode+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,p.stderr
a,b=[(out/(m+'.fields.txt')).read_text().splitlines() for m in ('0','1')];assert len(a)==len(b)
diffs=[{'field_index':i,'reference':x,'candidate':y} for i,(x,y) in enumerate(zip(a,b)) if x!=y]
r={'fixture_sha256':sha(target),'probe_sha256':sha(binary),'fields':len(a),'differences':diffs,'first_divergence':diffs[0] if diffs else None,'scope':'One real snapshot, no field exclusions or guest writes; labelled primitive-field dump'}
(out/'report.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))

"""Replace only the verified VU core in the immutable Phase4-correctness link."""
from pathlib import Path
import hashlib,json,re,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[1]
fmac='--fmac' in sys.argv
out=ROOT/'lab'/('phase5-game-02' if fmac else 'phase5-game-01');out.mkdir(exist_ok=False);start=time.monotonic()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
parent=ROOT/'lab/phase4-game-03/ps2EntryRunner.exe'
assert sha(parent)=='fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53'
build=ROOT/'lab'/('phase5-fmac-01' if fmac else 'phase5-pipeline-01');inputs=json.loads((build/'engineering-inputs.json').read_text())
for path,digest in inputs['files'].items():assert sha(path)==digest
rsp=(parent.parent/'link.rsp').read_text();old=[p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name=='ps2_vu1_core.cpp.obj'];assert len(old)==1
rsp=rsp.replace(old[0],str(build/'ps2_vu1_core.cpp.obj'))
for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/('ps2EntryRunner.exe'+suffix))+'"',rsp)
rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(ROOT/'lab/phase4-game-01/lto-cache')+'"',rsp)
(out/'link.rsp').write_text(rsp);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(out/'link.rsp')],cwd=out,check=True)
(out/'identity.json').write_text(json.dumps({'runner_sha256':sha(out/'ps2EntryRunner.exe'),'parent_sha256':sha(parent),'core_object_sha256':sha(build/'ps2_vu1_core.cpp.obj'),'source_sha256':sha(ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'),'seconds':time.monotonic()-start,'default':'Reference; experiment explicitly opted in; no promotion'},indent=2))
print('Isolated Phase5 game linked',flush=True)

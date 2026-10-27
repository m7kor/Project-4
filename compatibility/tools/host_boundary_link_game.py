"""Stage the verified helper-boundary core in an isolated Phase4 RE4 link."""
from pathlib import Path
import hashlib,json,re,subprocess,time,shutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/host-boundary-game-01';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
parent=ROOT/'lab/phase4-game-03/ps2EntryRunner.exe';build=ROOT/'lab/host-boundary-inline-01'
assert sha(parent)=='fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53'
assert json.loads((ROOT/'artifacts/host-boundary/equivalence-01/report.json').read_text())['passed']
bench=json.loads((ROOT/'artifacts/host-boundary/benchmark-01/report.json').read_text());assert bench['completed'] and all(x['positive_pairs']==7 and x['median_paired_cost_reduction_percent']>0 for x in bench['summary'].values())
inputs=json.loads((build/'engineering-inputs.json').read_text())
for path,digest in inputs['files'].items():assert sha(path)==digest,path
rsp=(parent.parent/'link.rsp').read_text();old=[p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name=='ps2_vu1_core.cpp.obj'];assert len(old)==1
rsp=rsp.replace(old[0],str(build/'ps2_vu1_core.cpp.obj'))
for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/('ps2EntryRunner.exe'+suffix))+'"',rsp)
cache=out/'lto-cache';prior=ROOT/'lab/phase4-game-01/lto-cache'
if prior.is_dir():
    print('Copying existing cache into new private build; old cache remains untouched',flush=True);shutil.copytree(prior,cache)
rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(cache)+'"',rsp)
(out/'link.rsp').write_text(rsp);start=time.perf_counter();print('Link isolated RE4 helper-boundary candidate',flush=True)
subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(out/'link.rsp')],cwd=out,check=True)
(out/'identity.json').write_text(json.dumps({'runner_sha256':sha(out/'ps2EntryRunner.exe'),'parent_sha256':sha(parent),'core_object_sha256':sha(build/'ps2_vu1_core.cpp.obj'),'source_sha256':sha(build/'src/ps2_vu1_core.cpp'),'link_rsp_sha256':sha(out/'link.rsp'),'seconds':time.perf_counter()-start,'scope':'New isolated candidate, original Phase4 game objects and assets; no diagnostic instrumentation; not promoted'},indent=2));print('Staged game link complete',flush=True)

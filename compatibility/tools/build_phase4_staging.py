"""Add the DMA guard to the verified staged EE generation, with focused tests."""
from pathlib import Path
import hashlib,json,re,subprocess,time,os
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/phase4-game-02';out.mkdir(exist_ok=False);start=time.monotonic()
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
previous=json.loads((ROOT/'lab/phase4-game-01/identity.json').read_text())
assert all(sha(r['source'])==r['source_sha256'] and sha(r['object'])==r['object_sha256'] for r in previous['changed_units'])
def compile(src,recipe_name,objname):
    row=next(r for r in db if Path(r['file']).name==recipe_name);obj=out/objname
    cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',row['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/(objname+'.pdb'))+'"',cmd);cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- "'+str(src)+'"'
    subprocess.run(cmd,cwd=out,check=True);return obj
memory=ROOT/'engines/project4/ps2xRuntime/src/lib/ps2_memory.cpp';memobj=compile(memory,'ps2_memory.cpp','memory.obj');probe=compile(ROOT/'tests/phase4_dma_limits.cpp','vu1_bench.cpp','dma-tests.obj')
def link(name,rsp):
    for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/(name+suffix))+'"',rsp)
    rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(ROOT/'lab/phase4-game-01/lto-cache')+'"',rsp)
    oldmem=next((p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name=='ps2_memory.cpp.obj'),None)
    rsp=rsp.replace(oldmem,str(memobj)) if oldmem else '"'+str(memobj)+'"\n'+rsp
    path=out/(name+'.rsp');path.write_text(rsp);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(path)],cwd=out,check=True)
rsp=(ROOT/'lab/shared-link/ps2x_vu1_bench.exe.rsp').read_text();old=next(p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name=='vu1_bench.cpp.obj');link('dma-tests.exe',rsp.replace(old,str(probe)))
env=os.environ.copy();env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
r=subprocess.run([out/'dma-tests.exe'],cwd=out,env=env,capture_output=True,text=True,timeout=60);(out/'dma-tests.stdout.txt').write_text(r.stdout);(out/'dma-tests.stderr.txt').write_text(r.stderr);print(r.stdout+r.stderr,flush=True)
if r.returncode:raise RuntimeError('DMA guard regression failed')
link('ps2x_tests.exe',(ROOT/'lab/phase4-tests-01/link.rsp').read_text())
link('ps2EntryRunner.exe',(ROOT/'lab/phase4-game-01/ps2EntryRunner.exe.rsp').read_text())
(out/'identity.json').write_text(json.dumps({'binaries':{p.name:sha(p) for p in out.glob('*.exe')},'memory_source_sha256':sha(memory),'memory_object_sha256':sha(memobj),'dma_regression_exit':r.returncode,'previous':previous,'seconds':time.monotonic()-start},indent=2));print('Staged F1/F2/F3 candidate complete',flush=True)

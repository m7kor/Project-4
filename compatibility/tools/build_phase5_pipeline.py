"""Compile the changed VU TU and relink isolated Phase4-compatible tests first."""
from pathlib import Path
import hashlib,json,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'lab'/('phase5-pipeline-01' if len(sys.argv)==1 else sys.argv[1]);out.mkdir(exist_ok=False);start=time.monotonic()
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text())
recipe=next(r for r in db if Path(r['file']).name==source.name)
obj=out/'ps2_vu1_core.cpp.obj'
command=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',recipe['command'])
command=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/'compiler.pdb')+'"',command)
command=command[:command.rindex(' -c -- ')]+' -c -- "'+str(source)+'"'
subprocess.run(command,cwd=out,check=True)
inputs={str(p):sha(p) for p in source.parent.rglob('*') if p.suffix in ('.cpp','.h','.inl','.inc')}
for name,base in [('ps2x_tests.exe',ROOT/'lab/phase4-tests-02/link.rsp'),('ps2x_vu1_bench.exe',ROOT/'lab/shared-link/ps2x_vu1_bench.exe.rsp')]:
 rsp=base.read_text();objects=re.findall(r'"([^"]+\.obj)"',rsp)
 old=[p for p in objects if Path(p).name=='ps2_vu1_core.cpp.obj'];assert len(old)==1,old
 rsp=rsp.replace(old[0],str(obj))
 for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/(name+suffix))+'"',rsp)
 rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(ROOT/'lab/phase4-game-01/lto-cache')+'"',rsp)
 path=out/(name+'.rsp');path.write_text(rsp)
 subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(path)],cwd=out,check=True)
(out/'identity.json').write_text(json.dumps({p.name:sha(p) for p in out.glob('*.exe')},indent=2))
(out/'engineering-inputs.json').write_text(json.dumps({'files':{**inputs,str(obj):sha(obj)},'covered_source_files':[str(source)],'scope':'New VU core only, Phase4 C++ unit link and accepted unchanged VU benchmark dependencies'},indent=2))
print('Focused VU build completed',time.monotonic()-start,flush=True)

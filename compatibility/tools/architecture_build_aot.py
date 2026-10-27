"""Build one private VU TU and link tests/bench without rebuilding game code."""
from pathlib import Path
import hashlib,json,re,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab'/('architecture-aot-01' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'lab';source=out/'src/ps2_vu1_core.cpp'
assert source.is_file() and not (out/'ps2_vu1_core.cpp.obj').exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
generation=json.loads((out/'generation.json').read_text())
for p,h in {**generation['input_files'],**generation['generated_files']}.items():assert sha(p)==h,p
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text());recipe=next(x for x in db if Path(x['file']).name=='ps2_vu1_core.cpp')
obj=out/'ps2_vu1_core.cpp.obj';cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',recipe['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/'compiler.pdb')+'"',cmd);cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- "'+str(source)+'"'
begin=time.monotonic();print('Compiling isolated native coverage candidate',flush=True);subprocess.run(cmd,cwd=out,check=True)
for name,base in [('ps2x_tests.exe',ROOT/'lab/phase4-tests-02/link.rsp'),('ps2x_vu1_bench.exe',ROOT/'lab/shared-link/ps2x_vu1_bench.exe.rsp')]:
 rsp=base.read_text();old=[x for x in re.findall(r'"([^"]+\.obj)"',rsp) if Path(x).name=='ps2_vu1_core.cpp.obj'];assert len(old)==1;rsp=rsp.replace(old[0],str(obj))
 for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/(name+suffix))+'"',rsp)
 rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(out/'lto-cache')+'"',rsp)
 path=out/(name+'.rsp');path.write_text(rsp);print('Link',name,flush=True);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(path)],cwd=out,check=True)
(out/'identity.json').write_text(json.dumps({p.name:sha(p) for p in out.glob('*.exe')},indent=2))
(out/'engineering-inputs.json').write_text(json.dumps({'files':{**generation['generated_files'],str(obj):sha(obj)},'covered_source_files':[str(source)],'scope':'Phase4 base core with extra generated native coverage only; reference object dependencies unchanged','compile_command':cmd,'seconds':time.monotonic()-begin},indent=2));print('Build complete',flush=True)

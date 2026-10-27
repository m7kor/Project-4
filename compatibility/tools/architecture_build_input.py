"""Integrate already-existing exact EE pad tracing into the Phase4 reference link.

Fresh objects, no new game-input semantics. Original packages remain untouched.
"""
from pathlib import Path
import hashlib,json,re,subprocess,time
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/architecture-input-01';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text());known=json.loads((ROOT/'lab/pad-trace-link/source-inputs.json').read_text())
inputs={};objects=[];start=time.monotonic()
for name,h in known['sources'].items():
 source=ROOT/'engines/project4/ps2xRuntime/src/lib'/name;assert sha(source)==h
 recipe=next(r for r in db if Path(r['file']).name==name);obj=out/(name+'.obj')
 cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',recipe['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/(name+'.pdb'))+'"',cmd);cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- "'+str(source)+'"'
 print('Compile diagnostic',name,flush=True);subprocess.run(cmd,cwd=out,check=True);inputs[str(source)]=h;inputs[str(obj)]=sha(obj);objects.append(obj)
parent=ROOT/'lab/phase4-game-03/ps2EntryRunner.exe';assert sha(parent)=='fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53'
for name,base in [('ps2x_tests.exe',ROOT/'lab/phase4-tests-02/link.rsp'),('ps2EntryRunner.exe',parent.parent/'link.rsp')]:
 rsp=base.read_text();assert '/FORCE:MULTIPLE' in rsp and 'ps2_runtime.lib' in rsp
 rsp='\n'.join('"'+str(p)+'"' for p in objects)+'\n'+rsp
 for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/(name+suffix))+'"',rsp)
 rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(out/'lto-cache')+'"',rsp)
 target=out/(name+'.rsp');target.write_text(rsp);print('Link tracing',name,flush=True);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(target)],cwd=out,check=True)
(out/'identity.json').write_text(json.dumps({'binaries':{p.name:sha(p) for p in out.glob('*.exe')},'files':inputs,'parent_sha256':sha(parent),'seconds':time.monotonic()-start,'scope':'Fresh build of existing diagnostic source; Phase4 generated arithmetic and VU preserved. No input or save semantics changed.'},indent=2));print('Input clock diagnostic built',flush=True)

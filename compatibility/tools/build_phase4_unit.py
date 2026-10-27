"""Relink candidate unit tests with freshly compiled permanent regression cases."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
ROOT=Path(__file__).resolve().parents[1];parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=ROOT/'lab/phase4-tests-01');parser.add_argument('--base-rsp',type=Path,default=ROOT/'lab/phase4-game-01/ps2x_tests.exe.rsp');args=parser.parse_args();out=args.out.resolve();assert out.is_relative_to(ROOT/'lab');out.mkdir(exist_ok=False)
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text());src=ROOT/'engines/project4/ps2xTest/src/ps2_recompiler_tests.cpp';obj=out/'recompiler-tests.obj'
row=next(r for r in db if Path(r['file']).name==src.name);cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',row['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/'tests.pdb')+'"',cmd);cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- "'+str(src)+'"';subprocess.run(cmd,cwd=out,check=True)
rsp=args.base_rsp.read_text();old=next((p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name in (src.name+'.obj','recompiler-tests.obj')),None);rsp=rsp.replace(old,str(obj)) if old else '"'+str(obj)+'"\n'+rsp
for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/('ps2x_tests.exe'+suffix))+'"',rsp)
rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(ROOT/'lab/phase4-game-01/lto-cache')+'"',rsp)
(out/'link.rsp').write_text(rsp);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(out/'link.rsp')],cwd=out,check=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();(out/'identity.json').write_text(json.dumps({'source':sha(src),'binary':sha(out/'ps2x_tests.exe')},indent=2));print('Candidate unit suite linked')

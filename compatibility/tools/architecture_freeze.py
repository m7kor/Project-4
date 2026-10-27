"""Read-only inventory and immutable starting evidence for architecture work."""
from pathlib import Path
import hashlib,json,subprocess,shutil
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def git(path,*args):return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
out=ROOT/'artifacts/architecture/freeze-01';out.mkdir(parents=True,exist_ok=False)
old=json.loads((ROOT/'artifacts/phase5/final-manifest-03.json').read_text())
for p,h in old['files'].items():assert sha(ROOT/p)==h,p
for p,h in old['protected_verified'].items():assert sha(ROOT/p)==h,p
result={'phase5_identities_verified':len(old['files']),'protected':old['protected_verified'],'projects':{},'source_files':{}}
for path in [ROOT,ROOT/'engines/project4',Path('D:/Project/Zmbor'),Path('C:/Project/PS2redmption')]:
 try:result['projects'][str(path)]={'head':git(path,'rev-parse','HEAD'),'branch':git(path,'branch','--show-current'),'status':git(path,'status','--short','-uno')}
 except subprocess.CalledProcessError as e:result['projects'][str(path)]={'read_error':str(e)}
core=ROOT/'engines/project4'
for folder in ['ps2xRuntime/src/lib','ps2xRuntime/include','ps2xIOP/src','ps2xRecomp/src','ps2xRecomp/tools','ps2xTest/src']:
 for p in (core/folder).rglob('*'):
  if p.is_file() and 'runner' not in p.parts and p.suffix in ('.cpp','.h','.hpp','.inl','.inc','.py'):
   result['source_files'][str(p.relative_to(ROOT))]=sha(p)
for rel in ['ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp','ps2xRuntime/src/lib/vu/generated/vu1_compiled_programs.inc','ps2xRuntime/src/lib/ps2_pad.cpp','ps2xRuntime/src/lib/ps2_vu1_execution.cpp']:
 p=core/rel;shutil.copyfile(p,out/p.name)
(out/'manifest.json').write_text(json.dumps(result,indent=2));print('Frozen',len(result['source_files']),'runtime/tool/test source identities; Phase5 and accepted/card identities verified')

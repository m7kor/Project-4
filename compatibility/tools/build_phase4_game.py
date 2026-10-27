"""Recompile only genuinely changed EE units, preserve accepted runner/objects."""
from pathlib import Path
import concurrent.futures,hashlib,json,re,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'lab/phase4-game-01';out.mkdir(exist_ok=False);start=time.monotonic();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    regenerated=ROOT/'artifacts/phase4/recompile-01/generated';affected=json.loads((regenerated.parent/'affected.json').read_text());assert not affected['unexpected_preexisting']
    db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text());rsp=(ROOT/'lab/shared-link/ps2EntryRunner.exe.rsp').read_text();original_objects=re.findall(r'"([^"]+\.obj)"',rsp)
    jobs=[]
    for name in affected['changed']:
        row=next(r for r in db if Path(r['file']).name==name and 'ps2EntryRunner.dir' in r['command']);src=regenerated/name;obj=out/(name+'.obj')
        old=next(p for p in original_objects if Path(p).name==name+'.obj');assert rsp.count('"'+old+'"')==1
        cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',row['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/(name+'.pdb'))+'"',cmd)
        cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- "'+str(src)+'"';jobs.append((src,obj,cmd,old));rsp=rsp.replace('"'+old+'"','"'+str(obj)+'"')
    def compile(job):
        src,obj,cmd,old=job;r=subprocess.run(cmd,cwd=out,capture_output=True,text=True);(out/(src.name+'.log')).write_text(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError(src.name+': '+r.stdout[-600:]+r.stderr[-1800:])
        return {'source':str(src),'source_sha256':sha(src),'object':str(obj),'object_sha256':sha(obj),'replaced_object':old,'command':cmd}
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(compile,jobs):results.append(result);print('Compiled',len(results),'/',len(jobs),flush=True)
    def relink(name,response):
        for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:response=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/(name+suffix))+'"',response)
        response=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(out/'lto-cache')+'"',response)
        f=out/(name+'.rsp');f.write_text(response);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(f)],cwd=out,check=True)
    relink('ps2EntryRunner.exe',rsp)
    unit=(ROOT/'lab/shared-link/ps2x_tests.exe.rsp').read_text();overrides=[ROOT/'lab/phase4-fixed-01'/(n+'.obj') for n in ('instruction_translator.cpp','special_translator.cpp','elf_parser.cpp')]
    relink('ps2x_tests.exe','\n'.join('"'+str(p)+'"' for p in overrides)+'\n'+unit)
    (out/'identity.json').write_text(json.dumps({'binaries':{p.name:sha(p) for p in out.glob('*.exe')},'changed_units':results,'accepted_reference':'e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a','recompiler_identity':json.loads((ROOT/'lab/phase4-fixed-01/identity.json').read_text()),'seconds':time.monotonic()-start},indent=2));print('Isolated staged game and candidate tests built',flush=True)
if __name__=='__main__':main()

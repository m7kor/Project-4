"""Regenerate full SNR2 modules with the fixed emitter; original plans/images read-only."""
from pathlib import Path
import concurrent.futures,hashlib,json,os,re,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];SOURCE=Path('C:/Project/PS2redmption');OLD=SOURCE/'core/out/build'
def main():
    out=ROOT/'lab/phase4-native-01';out.mkdir(exist_ok=False);data=ROOT/'artifacts/phase4/native-01';data.mkdir(exist_ok=False);start=time.monotonic();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    # Reuse the independently verified corrected emitter objects, never the old native generator.
    libs=[OLD/p for p in ['ps2xRecomp/ps2_recomp_lib.lib','_deps/fmt-build/fmt.lib','_deps/libdwarf-build/src/lib/libdwarf/dwarf.lib','ps2xRecomp/rabbitizer.lib']]
    objects=[ROOT/'lab/phase4-fixed-01'/(p+'.obj') for p in ('instruction_translator.cpp','special_translator.cpp','elf_parser.cpp')]
    mainobj=OLD/'ps2xRecomp/CMakeFiles/ps2_native_module_codegen.dir/src/tools/native_module_codegen_main.cpp.obj';exe=out/'native-codegen.exe';rsp=out/'codegen.rsp'
    rsp.write_text('\n'.join('"'+str(p)+'"' for p in [mainobj,*objects,*libs])+f'\n/out:"{exe}"\n/pdb:"{out / "codegen.pdb"}"\nkernel32.lib user32.lib gdi32.lib winspool.lib shell32.lib ole32.lib oleaut32.lib uuid.lib comdlg32.lib advapi32.lib')
    subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(rsp)],cwd=out,check=True)
    original=SOURCE/'recomp/native/SLUS_211.34/full';plan=data/'plans';plan.mkdir();manifest=json.loads((original/'manifest.json').read_text());shutil.copy2(original/'manifest.json',plan/'manifest.json');records=[]
    for index,module in enumerate(manifest['modules']):
        name=module['identifier'];binary=original/(name+'.bin');assert sha(binary)==module['identity'],name
        for suffix in ('.toml','.bin'):shutil.copy2(original/(name+suffix),plan/(name+suffix))
        p=subprocess.run([exe,plan/(name+'.toml'),plan/(name+'.cpp')],cwd=plan,capture_output=True,text=True)
        (plan/(name+'.log')).write_text(p.stdout+p.stderr)
        if p.returncode:raise RuntimeError(name+': '+p.stderr[-1000:])
        records.append({'identifier':name,'image_sha256':sha(binary),'generated_sha256':sha(plan/(name+'.cpp'))});print('Regenerated native module',index+1,'/',len(manifest['modules']),flush=True)
    generated=data/'full_build'
    subprocess.run([sys.executable,'-m','tools.diagnostics.snr2_full_build',plan,generated,'--hybrid-partial-dir',SOURCE/'recomp/native/SLUS_211.34'],cwd=ROOT/'reference-tools',check=True)
    db=json.loads((OLD/'compile_commands.json').read_text());body=next(r for r in db if Path(r['file']).name=='snr2_bodies_000.cpp');desc=next(r for r in db if Path(r['file']).name=='snr2_descriptors_000.cpp');installer=next(r for r in db if Path(r['file']).name=='re4-native-modules-full.cpp');jobs=[]
    for src in generated.glob('*.cpp'):
        recipe=body if src.name.startswith('snr2_bodies_') else desc if src.name.startswith('snr2_descriptors_') else installer
        obj=out/(src.name+'.obj');cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',recipe['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/(src.name+'.pdb'))+'"',cmd);cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- "'+str(src)+'"';jobs.append((src,obj,cmd))
    def compile(job):
        src,obj,cmd=job;p=subprocess.run(cmd,cwd=out,capture_output=True,text=True);(out/(src.name+'.log')).write_text(p.stdout+p.stderr)
        if p.returncode:raise RuntimeError(src.name+': '+p.stdout[-500:]+p.stderr[-1500:])
        return {'source':str(src),'source_sha256':sha(src),'object':str(obj),'object_sha256':sha(obj)}
    compiled=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for item in pool.map(compile,jobs):compiled.append(item);print('Compiled native unit',len(compiled),'/',len(jobs),flush=True)
    (out/'identity.json').write_text(json.dumps({'modules':records,'compiled':compiled,'native_codegen_sha256':sha(exe),'seconds':time.monotonic()-start,'scope':'Full default native modules regenerated. Existing optional hybrid partial implementations preserved and NOT claimed fixed.'},indent=2));print('Full native regeneration and compilation complete',flush=True)
if __name__=='__main__':main()

"""Focused recompiler build; old libraries read-only, new TUs override old members."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
ROOT=Path(__file__).resolve().parents[1];OLD=Path('C:/Project/PS2redmption/core/out/build')
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--baseline',action='store_true');a=p.parse_args()
    out=(ROOT/a.out).resolve();assert out.is_relative_to(ROOT/'lab');out.mkdir(exist_ok=False)
    db=json.loads((OLD/'compile_commands.json').read_text());sources={} ;objects=[]
    def compile(src,recipe,name):
        obj=out/(name+'.obj');cmd=recipe['command'];cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',cmd)
        cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/(name+'.pdb'))+'"',cmd)
        if ' -c -- ' in cmd:cmd=cmd[:cmd.rindex(' -c -- ')]+' /O2 -c -- "'+str(src)+'"'
        else:cmd=re.sub(r'/c\s+.*$',lambda _: '/O2 /c "'+str(src)+'"',cmd)
        print('Compile',name,flush=True);subprocess.run(cmd,cwd=out,check=True);sources[str(src)]=hashlib.sha256(src.read_bytes()).hexdigest();return obj
    if not a.baseline:
        for name in ('instruction_translator.cpp','special_translator.cpp','elf_parser.cpp'):
            row=next(r for r in db if Path(r['file']).name==name)
            objects.append(compile(ROOT/'engines/project4/ps2xRecomp/src/lib'/name,row,name))
    probe=compile(ROOT/'tests/phase4_codegen_probe.cpp',next(r for r in db if Path(r['file']).name=='special_translator.cpp'),'probe')
    libs=[OLD/p for p in ['ps2xRecomp/ps2_recomp_lib.lib','_deps/fmt-build/fmt.lib','_deps/libdwarf-build/src/lib/libdwarf/dwarf.lib','ps2xRecomp/rabbitizer.lib']]
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    for name,mainobj in [('probe',probe),('ps2_recomp',OLD/'ps2xRecomp/CMakeFiles/ps2_recomp.dir/src/runner/main.cpp.obj')]:
        exe=out/(name+'.exe');rsp=out/(name+'.rsp');rsp.write_text('\n'.join('"'+str(p)+'"' for p in [mainobj,*objects,*libs])+'\n/nologo\n/out:"'+str(exe)+'"\n/pdb:"'+str(out/(name+'.pdb'))+'"\nkernel32.lib user32.lib gdi32.lib winspool.lib shell32.lib ole32.lib oleaut32.lib uuid.lib comdlg32.lib advapi32.lib')
        subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(rsp)],cwd=out,check=True)
    (out/'identity.json').write_text(json.dumps({'baseline':a.baseline,'sources':sources,'libraries':{str(p):sha(p) for p in libs},'binaries':{p.name:sha(p) for p in out.glob('*.exe')}},indent=2))
if __name__=='__main__':main()

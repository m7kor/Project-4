"""Compile one standalone fixture consumer, using the accepted production VIF TU."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=ROOT/'lab/vif-replay-observed');parser.add_argument('--phase3',action='store_true');args=parser.parse_args()
out=(ROOT/args.out).resolve();assert out.is_relative_to((ROOT/'lab').resolve());out.mkdir(exist_ok=False)
def header_inputs():
    result={}
    for folder in (ROOT/'engines/project4/ps2xRuntime/include',ROOT/'engines/project4/ps2xRuntime/src/lib',Path('C:/Project/PS2redmption/core/ps2xRuntime/include')):
        for p in folder.rglob('*'):
            if p.is_file() and p.suffix in ('.h','.inl'):result[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    if args.phase3:
        for p in (ROOT/'lab/zmbor-phase2/deps/nlohmann_json/include').rglob('*.hpp'):result[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        # Reused IOP libraries are explicitly distinguished from the freshly
        # compiled transport TUs. Freeze their source trees too, so a later
        # source edit cannot silently keep using this old library generation.
        for folder in (ROOT/'engines/project4/ps2xIOP',Path('C:/Project/PS2redmption/core/ps2xIOP'),Path('C:/Project/PS2redmption/core/ps2xRuntime/src/lib')):
            for p in folder.rglob('*'):
                if p.is_file() and p.suffix in ('.h','.hpp','.inl','.cpp'):result[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result
headers=header_inputs()
src=ROOT/('tests/dma_iop_replay.cpp' if args.phase3 else 'tests/vif_direct_replay.cpp');obj=out/'replay.obj'
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text())
entry=next(r for r in db if Path(r['file']).name=='vu1_bench.cpp')
cmd=re.sub(r'/Fo[^ ]+',lambda _: '/Fo"'+str(obj)+'"',entry['command'])
cmd=re.sub(r'/Fd[^ ]+',lambda _: '/Fd"'+str(out/'replay.pdb')+'"',cmd)
cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- "'+str(src)+'"'
if args.phase3:cmd=cmd.replace(' -c -- ',' /O2 /I"'+str(ROOT/'lab/zmbor-phase2/deps/nlohmann_json/include')+'" -c -- ')
subprocess.run(cmd,cwd=out,check=True)
vif=ROOT/'engines/project4/ps2xRuntime/src/lib/ps2_vif1_interpreter.cpp'
vifentry=next(r for r in db if Path(r['file']).name==vif.name)
vifobj=out/'vif-observed.obj'
vifcmd=re.sub(r'/Fo[^ ]+',lambda _: '/Fo"'+str(vifobj)+'"',vifentry['command'])
vifcmd=re.sub(r'/Fd[^ ]+',lambda _: '/Fd"'+str(out/'vif.pdb')+'"',vifcmd)
vifcmd=vifcmd[:vifcmd.rindex(' -c -- ')]+' /DPS2X_VIF_REPLAY_OBSERVER=1 -c -- "'+str(vif)+'"'
subprocess.run(vifcmd,cwd=out,check=True)
rsp=(ROOT/'lab/shared-link/ps2x_vu1_bench.exe.rsp').read_text()
old=next(p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name=='vu1_bench.cpp.obj');rsp=rsp.replace(old,str(obj))
oldvif=next(p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name=='ps2_vif1_interpreter.cpp.obj');rsp=rsp.replace(oldvif,str(vifobj))
production_sources={str(vif):hashlib.sha256(vif.read_bytes()).hexdigest()}
if args.phase3:
    for name,relative in [('ps2_memory.cpp','ps2_memory.cpp'),('SIF.cpp','Kernel/Stubs/SIF.cpp')]:
        source=ROOT/'engines/project4/ps2xRuntime/src/lib'/relative
        row=next(r for r in db if Path(r['file']).name==name)
        target=out/(name+'.obj')
        command=re.sub(r'/Fo[^ ]+',lambda _: '/Fo"'+str(target)+'"',row['command'])
        command=re.sub(r'/Fd[^ ]+',lambda _: '/Fd"'+str(out/(name+'.pdb'))+'"',command)
        command=command[:command.rindex(' -c -- ')]+' -c -- "'+str(source)+'"'
        subprocess.run(command,cwd=out,check=True)
        oldobject=next((p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name==name+'.obj'),None)
        rsp=rsp.replace(oldobject,str(target)) if oldobject else '"'+str(target)+'"\n'+rsp
        production_sources[str(source)]=hashlib.sha256(source.read_bytes()).hexdigest()
for switch,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:
    rsp=re.sub(r'/'+switch+r':"[^"]+"',lambda _: '/'+switch+':"'+str(out/('vif_replay.exe'+suffix))+'"',rsp)
rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:"'+str(out/'lto-cache')+'"',rsp)
(out/'link.rsp').write_text(rsp);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(out/'link.rsp')],cwd=out,check=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
objects={p:sha(p) for p in re.findall(r'"([^"]+\.(?:obj|lib))"',rsp) if Path(p).is_file()}
assert headers==header_inputs(),'Header dependencies changed during build'
(out/'identity.json').write_text(json.dumps({'binary_sha256':sha(out/'vif_replay.exe'),'harness_path':str(src),'harness_sha256':sha(src),'included_harness_sha256':sha(ROOT/'tests/vif_direct_replay.cpp'),'production_sources':production_sources,'vif_source_sha256':sha(vif),'headers':headers,'observer_define':'PS2X_VIF_REPLAY_OBSERVER=1','linked_objects':objects,'scope':'Production VIF; phase3 also freshly compiles DMAC memory and SIF transport. Other accepted link objects reused. No RE4 ELF or runner compiled or launched'},indent=2));print('Built standalone production replay',flush=True)

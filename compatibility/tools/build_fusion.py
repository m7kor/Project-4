"""Compile one changed runtime TU and relink using private response files and cache."""
from pathlib import Path
import re,subprocess,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
old=ROOT/'lab/native-link'
out_name=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--out=')), 'fusion-link')
assert out_name in ('fusion-link','shared-link','queue-link','flag-link','normal-link')
out=ROOT/'lab'/out_name;out.mkdir(exist_ok=True)
if '--verify-only' in sys.argv:
    manifest=json.loads((out/'identity.json').read_text())
    assert set(manifest)=={'ps2EntryRunner.exe','ps2x_tests.exe','ps2x_vu1_bench.exe'}
    assert all(hashlib.sha256((out/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
    print('Verified all three completed fusion binaries against the successful-link manifest')
    raise SystemExit(0)
src=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text())
entry=next(r for r in db if Path(r['file']).name=='ps2_vu1_core.cpp')
obj=out/'ps2_vu1_core.cpp.obj'
quote=lambda p:'"'+str(p)+'"'
cmd=re.sub(r'/Fo[^ ]+',lambda _: '/Fo'+quote(obj),entry['command'])
cmd=re.sub(r'/Fd[^ ]+',lambda _: '/Fd'+quote(out/'vu1.pdb'),cmd)
cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- '+quote(src)
inputs={str(p.relative_to(src.parent)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in src.parent.rglob('*') if p.is_file() and p.suffix in ('.cpp','.inl','.inc','.h')}
stamp=out/'compile-inputs.json'
if '--reuse-object' in sys.argv:
    previous=json.loads(stamp.read_text())
    assert previous['inputs']==inputs and previous['object_sha256']==hashlib.sha256(obj.read_bytes()).hexdigest(), 'Changed compiler inputs; do not reuse stale object'
else:
    assert not obj.exists(), 'Use a new output directory or explicitly reuse the verified existing object'
    print('Compiling the isolated VU runtime',flush=True)
    subprocess.run(cmd,cwd=out,check=True)
    stamp.write_text(json.dumps({'inputs':inputs,'object_sha256':hashlib.sha256(obj.read_bytes()).hexdigest()},indent=2))
targets=[('ps2x_tests_after.exe','ps2x_tests.exe'),('ps2x_vu1_bench.exe','ps2x_vu1_bench.exe'),('ps2EntryRunner.exe','ps2EntryRunner.exe')]
if '--small' in sys.argv:targets=targets[:2]
if '--runner-only' in sys.argv:targets=targets[2:]
for original,name in targets:
    assert not (out/name).exists(), 'Do not overwrite a completed binary'
    rsp=(old/(original+'.rsp')).read_text()
    assert str(old/'ps2_vu1_core.cpp.obj') in rsp
    rsp=rsp.replace(str(old/'ps2_vu1_core.cpp.obj'),str(obj))
    for switch,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:
        rsp=re.sub(r'/'+switch+r':"[^"]+"',lambda _: '/'+switch+':'+quote(out/(name+suffix)),rsp)
    target=out/(name+'.rsp');target.write_text(rsp)
    print('Linking fused',name,flush=True)
    subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(target)],cwd=out,check=True)
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.exe')}
    (out/'identity.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest),flush=True)

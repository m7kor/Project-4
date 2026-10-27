"""Build the two diagnostic-only TUs against accepted immutable runtime objects."""
from pathlib import Path
import json,re,subprocess,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'lab/pad-trace-link';out.mkdir(exist_ok='--link-only' in sys.argv)
old=ROOT/'lab/native-link';accepted=ROOT/'lab/shared-link'
manifest=json.loads((accepted/'identity.json').read_text())
assert hashlib.sha256((accepted/'ps2EntryRunner.exe').read_bytes()).hexdigest()==manifest['ps2EntryRunner.exe']
assert hashlib.sha256((ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp').read_bytes()).hexdigest()=='48077ba02c66e8d0dc0efe6182db011ca2d7575db19e6b4f1e03412dfd207f98'
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text())
quote=lambda p:'"'+str(p)+'"'
objects={};inputs={}
for name in ('ps2_pad.cpp','ps2_iop_host.cpp'):
    src=ROOT/'engines/project4/ps2xRuntime/src/lib'/name
    entry=next(r for r in db if Path(r['file']).name==name)
    obj=out/(name+'.obj')
    cmd=re.sub(r'/Fo[^ ]+',lambda _: '/Fo'+quote(obj),entry['command'])
    cmd=re.sub(r'/Fd[^ ]+',lambda _: '/Fd'+quote(out/(name+'.pdb')),cmd)
    cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- '+quote(src)
    if '--link-only' in sys.argv:
        integration=json.loads((ROOT/'artifacts/experiments/pad-exact-trace/integration.json').read_text())
        expected=next(r['after'] for r in integration['files'] if r['file']==name)
        assert obj.is_file() and hashlib.sha256(src.read_bytes()).hexdigest()==expected
    else:
        print('Compiling diagnostic',name,flush=True)
        subprocess.run(cmd,cwd=out,check=True)
    original=re.search(r'/Fo([^ ]+)',entry['command'])[1]
    objects[original]=str(obj);inputs[name]=hashlib.sha256(src.read_bytes()).hexdigest()
for original,name in [('ps2x_tests_after.exe','ps2x_tests.exe'),('ps2EntryRunner.exe','ps2EntryRunner.exe')]:
    assert not (out/name).exists(), 'Never overwrite a completed binary'
    rsp=(old/(original+'.rsp')).read_text()
    assert str(old/'ps2_vu1_core.cpp.obj') in rsp
    rsp=rsp.replace(str(old/'ps2_vu1_core.cpp.obj'),str(accepted/'ps2_vu1_core.cpp.obj'))
    # These two TUs are archive members in ps2_runtime.lib, not individual
    # response entries. Explicit object definitions precede the original
    # archive, exactly as the existing accepted runtime-overlay build does.
    assert 'ps2_runtime.lib' in rsp and '/FORCE:MULTIPLE' in rsp
    rsp='\n'.join(quote(p) for p in objects.values())+'\n'+rsp
    rsp=re.sub(r'/lldltocache:"[^"]+"',lambda _: '/lldltocache:'+quote(out/'lto-cache'),rsp)
    for switch,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:
        rsp=re.sub(r'/'+switch+r':"[^"]+"',lambda _: '/'+switch+':'+quote(out/(name+suffix)),rsp)
    target=out/(name+'.rsp');target.write_text(rsp)
    print('Linking diagnostic',name,flush=True)
    subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(target)],cwd=out,check=True)
    (out/'identity.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.exe')},indent=2))
(out/'source-inputs.json').write_text(json.dumps({'sources':inputs,'accepted_vu_object_sha256':hashlib.sha256((accepted/'ps2_vu1_core.cpp.obj').read_bytes()).hexdigest(),'scope':'Two trace TUs only; original accepted VU object and original ABI'},indent=2))
print((out/'identity.json').read_text(),flush=True)

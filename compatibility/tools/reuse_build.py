"""Compile changed runtime TUs and relink against READ-ONLY existing objects.

No Ninja/CMake operation executes in the reference build. Every compiler output,
response file, LTO cache, EXE and PDB is placed in the lab. The original build's
flags and libraries are reused to preserve its FFmpeg/SPU2/parallel-gs ABI.
"""
from pathlib import Path
import json,re,subprocess,sys,hashlib
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path('C:/Project/PS2redmption/core')
BUILD=ORIGINAL/'out/build'
OUT=ROOT/'lab/native-link'
def quote(p):return '"'+str(p)+'"'
def build():
    OUT.mkdir(parents=True,exist_ok=True)
    db=json.loads((BUILD/'compile_commands.json').read_text())
    files=json.loads((ROOT/'artifacts/gif-integration.json').read_text())['files']
    objects=[]
    for name in files:
        src=ROOT/'engines/project4/ps2xRuntime/src/lib'/name
        original=ORIGINAL/'ps2xRuntime/src/lib'/name
        entry=next(row for row in db if Path(row['file'])==original)
        obj=OUT/(src.name+'.obj');objects.append(obj)
        if '--link-only' in sys.argv or '--tests-only' in sys.argv or '--bench-only' in sys.argv:
            assert obj.is_file()
            continue
        cmd=entry['command']
        cmd=re.sub(r'/Fo[^ ]+',lambda _: '/Fo'+quote(obj),cmd)
        cmd=re.sub(r'/Fd[^ ]+',lambda _: '/Fd'+quote(OUT/(src.name+'.pdb')),cmd)
        cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- '+quote(src)
        # Compiler inputs use original headers; the copied headers are byte-identical.
        assert str(obj).startswith(str(ROOT)) and '/Fo"'+str(OUT) in cmd
        print('Compiling',name,flush=True)
        subprocess.run(cmd,cwd=OUT,check=True)
    runtime_objects=objects[:]
    test_objects=[]
    if '--tests-only' in sys.argv:
        for name in ('ps2_gs_tests.cpp','ps2_memory_tests.cpp','ps2_vu1_tests.cpp'):
            src=ROOT/'engines/project4/ps2xTest/src'/name
            entry=next(row for row in db if Path(row['file']).name==name)
            obj=OUT/(name+'.obj');test_objects.append(obj)
            cmd=re.sub(r'/Fo[^ ]+',lambda _: '/Fo'+quote(obj),entry['command'])
            cmd=re.sub(r'/Fd[^ ]+',lambda _: '/Fd'+quote(OUT/(name+'.pdb')),cmd)
            cmd=cmd[:cmd.rindex(' -c -- ')]+' -c -- '+quote(src)
            print('Compiling regression unit',name,flush=True)
            subprocess.run(cmd,cwd=OUT,check=True)
    text=(BUILD/'build.ninja').read_text()
    def native_tokens(line):
        # Ninja escapes spaces with '$ '; protect those before whitespace splitting.
        return [x.replace('\x01',' ').replace('$$','$').replace('$:',':') for x in line.replace('$ ','\x01').split()]
    def link(target,output,extra=None):
        prefix='build '+target+': '
        start=text.index(prefix);end=text.find('\nbuild ',start+1)
        block=text[start:end];lines=block.splitlines()
        inputs=lines[0].split(': ',1)[1].split(' ',1)[1].split(' |')[0]
        entries=native_tokens(inputs)
        if test_objects and 'ps2xTest' in target:
            entries=[token for token in entries if not any(token.replace('\\','/').endswith('/'+p.name) for p in test_objects)]
        libs=re.search(r'^  LINK_LIBRARIES = (.+)$',block,re.M).group(1)
        original_flags=re.search(r'^  LINK_FLAGS = (.+)$',block,re.M).group(1)
        stack_flags=re.findall(r'/STACK:[^ ]+',original_flags,re.I)
        paths=[]
        for token in entries+native_tokens(libs):
            if token.endswith(('.obj','.lib')) and (BUILD/token).is_file():paths.append(quote((BUILD/token).resolve()))
            else:paths.append(quote(token))
        # Explicit replacement objects precede archive libraries. Their symbols prevent
        # extraction of the original runtime archive members with those same symbols.
        response=[quote(p) for p in (extra if extra is not None else runtime_objects)]+paths+stack_flags+['/nologo','/subsystem:console','/DEBUG:FULL','/OPT:REF','/OPT:ICF',
            '/lldltocache:'+quote(OUT/'lto-cache'),'/lldltocachepolicy:cache_size_bytes=2147483648',
            '/FORCE:MULTIPLE', # Original build uses this for raylib/Win32 CloseWindow and ShowCursor collisions.
            '/out:'+quote(OUT/output),'/pdb:'+quote(OUT/(output+'.pdb')),'/implib:'+quote(OUT/(output+'.lib'))]
        rsp=OUT/(output+'.rsp');rsp.write_text('\n'.join(response))
        print('Linking isolated',output,'with',len(entries),'existing objects',flush=True)
        subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(rsp)],cwd=OUT,check=True)
    if '--bench-only' in sys.argv:
        link('ps2xTest\\ps2x_vu1_bench.exe','ps2x_vu1_bench.exe')
    elif '--tests-only' in sys.argv:
        link('ps2xTest\\ps2x_tests.exe','ps2x_tests_before.exe',test_objects)
        link('ps2xTest\\ps2x_tests.exe','ps2x_tests_after.exe',runtime_objects+test_objects)
    else:
        link('ps2xRuntime\\ps2EntryRunner.exe','ps2EntryRunner.exe')
        link('ps2xTest\\ps2x_tests.exe','ps2x_tests.exe')
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.exe')}
    (OUT/'build-identity.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest),flush=True)
if __name__=='__main__':build()

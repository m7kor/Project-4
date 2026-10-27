"""Reuse Zmbor's small e2e programs and existing read-only runtime archives."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
REF=Path('D:/Project/Zmbor/wt-integration')
BUILD=REF/'build'
CURRENT=ROOT/'artifacts/phase2/hardware-current/catalog.json'
if CURRENT.exists():
    REF=ROOT/'lab/zmbor-phase2/src'
    BUILD=ROOT/'lab/zmbor-phase2/build'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tokens(s):return [x.replace('\x01',' ').replace('$$','$').replace('$:',':') for x in s.replace('$ ','\x01').split()]
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--project4-recompiler',type=Path);args=parser.parse_args()
    out=args.out.absolute();assert out.is_relative_to(ROOT/'artifacts');out.mkdir(parents=True,exist_ok=False)
    report={'scope':'Fresh synthetic source→ELF→Zmbor analysis/recompiler→native build→reference runtime; no RE4 or proprietary code',
            'runtime_scope':'Fresh phase2 integration runtime archives' if CURRENT.exists() else 'Existing wt-integration runtime archives; not a Project4 candidate','steps':[],'hashes':{},'passed':False}
    env=os.environ.copy();env['PS2X_HIDDEN_WINDOW']='1'
    env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
    def run(label,cmd,cwd):
        start=time.monotonic();p=subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,capture_output=True,text=True,errors='replace',timeout=120)
        (out/(label+'.stdout.txt')).write_text(p.stdout,encoding='utf-8');(out/(label+'.stderr.txt')).write_text(p.stderr,encoding='utf-8')
        report['steps'].append({'name':label,'exit_code':p.returncode,'seconds':time.monotonic()-start,'command':list(map(str,cmd))})
        if p.returncode:raise RuntimeError(label+': '+p.stderr[-1000:])
        return p.stdout
    try:
        recompiler=out/'ps2_recomp.exe';shutil.copy2(BUILD/'ps2xRecomp/ps2_recomp.exe',recompiler)
        report['hashes']['recompiler']=digest(recompiler)
        report['hashes']['reference-compile-commands']=digest(BUILD/'compile_commands.json')
        report['hashes']['reference-build-recipes']=digest(BUILD/'build.ninja')
        report['hashes']['synthetic-elf-generator']=digest(ROOT/'engines/zmbor/ps2xTest/e2e/e2e_programs.py')
        report['reference_revision']=json.loads(CURRENT.read_text())['source_identity']['source_commit'] if CURRENT.exists() else subprocess.run(['git','-C',str(REF),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
        db=json.loads((BUILD/'compile_commands.json').read_text());ninja=(BUILD/'build.ninja').read_text()
        for name in ('basic','gs_sprite'):
            work=out/name;work.mkdir()
            run(name+'-assemble',[sys.executable,REF/'ps2xTest/e2e/e2e_programs.py',name,work],work)
            report['hashes'][name+'.elf']=digest(work/(name+'.elf'))
            run(name+'-recompile',[recompiler,work/(name+'.toml')],work)
            entries=[r for r in db if 'ps2x_e2e_'+name+'.dir' in r['command']]
            assert len(entries)==3, 'Expected three existing e2e compiler recipes'
            objects=[];oldgen=BUILD/'ps2xTest/e2e'/name/(name+'_generated');newgen=work/(name+'_generated')
            for i,entry in enumerate(entries):
                oldsrc=Path(entry['file']);src=oldsrc if oldsrc.name=='main.cpp' else newgen/oldsrc.name
                obj=work/(str(i)+'.obj');objects.append(obj)
                cmd=entry['command']
                for spelling in (str(oldgen),oldgen.as_posix()):cmd=cmd.replace(spelling,str(newgen))
                cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',cmd)
                cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(work/(str(i)+'.pdb'))+'"',cmd)
                # MSVC's source is the final /c argument in this build database.
                cmd=re.sub(r'/c\s+.*$',lambda _: '/c "'+str(src)+'"',cmd)
                p=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True,errors='replace',timeout=120)
                (out/(name+'-compile-'+str(i)+'.log')).write_text(p.stdout+p.stderr)
                report['steps'].append({'name':name+'-compile-'+str(i),'exit_code':p.returncode,'source_sha256':digest(src)})
                if p.returncode:raise RuntimeError(p.stdout[-800:]+p.stderr[-800:])
            prefix='build ps2xTest\\e2e\\ps2x_e2e_'+name+'.exe: '
            start=ninja.index(prefix);end=ninja.find('\nbuild ',start+1);block=ninja[start:end if end>=0 else None]
            libs=tokens(re.search(r'^  LINK_LIBRARIES = (.+)$',block,re.M)[1]);response=['"'+str(p)+'"' for p in objects]
            for token in libs:
                path=BUILD/token
                if path.is_file():
                    response.append('"'+str(path)+'"');report['hashes'][str(path)]=digest(path)
                else:response.append(token)
            exe=work/'runner.exe'
            response+=['/nologo','/subsystem:console','/FORCE:MULTIPLE','/OUT:"'+str(exe)+'"','/PDB:"'+str(work/'runner.pdb')+'"']
            rsp=work/'link.rsp';rsp.write_text('\n'.join(response))
            run(name+'-link',['link.exe','@'+str(rsp)],work);report['hashes'][name+'-runner']=digest(exe)
            cmd=['cmake','-DRUNNER='+str(exe),'-DELF='+str(work/(name+'.elf')),'-DEXPECTED_FILE='+str(work/(name+'.expected'))]
            if name=='gs_sprite':cmd+=['-DFRAME_EXPECTED='+str(work/(name+'.frame.json')),'-DFRAME_FILE='+str(work/'frame.ppm'),'-DPYTHON='+sys.executable,'-DCHECK_FRAME='+str(ROOT/'engines/zmbor/ps2xTest/e2e/check_frame.py')]
            cmd+=['-P',str(ROOT/'engines/zmbor/ps2xTest/e2e/run_e2e.cmake')]
            run(name+'-execute',cmd,work)
        # Project4's canary also checks incremental output preservation, a
        # contract absent from the older Zmbor recompiler. Pair it with its
        # matching existing Project4 toolchain; keep the two scopes explicit.
        project4=out/'project4_recomp.exe'
        selected=args.project4_recompiler or Path('C:/Project/PS2redmption/core/out/build/ps2xRecomp/ps2_recomp.exe')
        shutil.copy2(selected,project4);report['project4_recompiler_selected']=str(selected)
        report['hashes']['project4-canary-recompiler']=digest(project4)
        run('native-canary',[sys.executable,ROOT/'reference-tools/ps2l/canary.py','--recompiler',project4,
            '--runtime-root',ROOT/'engines/project4','--out',out/'native-canary'],out)
        report['passed']=True
    except Exception as exc:report['error']=str(exc);print(str(exc),file=sys.stderr)
    finally:(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

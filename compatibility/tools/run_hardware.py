"""Rerun existing Zmbor binaries with copied test ELFs and local outputs."""
from pathlib import Path
import re,json,shutil,subprocess,sys,os,collections
ROOT=Path(__file__).resolve().parents[1]
source=Path('D:/Project/Zmbor/wt/build/ps2xTest/e2e')
out=ROOT/'artifacts/hardware';out.mkdir(exist_ok=True)
temp=out/'temp';temp.mkdir(exist_ok=True)
os.environ['TMP']=os.environ['TEMP']=str(temp)
os.environ['PYTHONDONTWRITEBYTECODE']='1'
text=(source/'CTestTestfile.cmake').read_text()
rows=[]
for line in text.splitlines():
    if not line.startswith('add_test("hw_'):continue
    args=re.findall(r'"([^"\n]*)"',line)
    get=lambda key:Path(args[args.index(key)+1])
    binary,elf,expected=get('--runner'),get('--elf'),get('--expected')
    name=binary.stem;work=out/name;work.mkdir(exist_ok=True)
    for p in (binary,elf,expected):shutil.copy2(p,work/p.name)
    result=work/'result.json'
    cmd=[sys.executable,str(ROOT/'engines/zmbor/tools/hwtest/hwtest.py'),'run','--runner',str(work/binary.name),
         '--elf',str(work/elf.name),'--expected',str(work/expected.name),'--result',str(result),'--timeout','15']
    with (work/'driver.log').open('w') as f:p=subprocess.run(cmd,cwd=work,stdout=f,stderr=subprocess.STDOUT)
    r=json.loads(result.read_text());r['id']=name;rows.append(r)
    print(name,r['status'],flush=True)
summary=dict(scope='Rerun of existing pre-integration ae1c119 Zmbor hardware binaries; NOT Project4 candidate hardware coverage',
             counts=dict(collections.Counter(r['status'] for r in rows)),tests=rows)
(out/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary['counts']))
# Current integration end-to-end binaries, copied with their synthetic inputs.
e2e=Path('D:/Project/Zmbor/wt-integration/build/ps2xTest/e2e')
for name in ('basic','gs_sprite'):
    work=out/('e2e-'+name);work.mkdir(exist_ok=True)
    shutil.copy2(e2e/('ps2x_e2e_'+name+'.exe'),work/'runner.exe')
    for p in (e2e/name).glob('*'):
        if p.is_file() and p.suffix in ('.elf','.expected','.json'):shutil.copy2(p,work/p.name)
    cmd=['cmake','-DRUNNER='+str(work/'runner.exe'),'-DELF='+str(work/(name+'.elf')),
         '-DEXPECTED_FILE='+str(work/(name+'.expected'))]
    if name=='gs_sprite':cmd+=['-DFRAME_EXPECTED='+str(work/(name+'.frame.json')),'-DFRAME_FILE='+str(work/'frame.ppm'),
                              '-DPYTHON='+sys.executable,'-DCHECK_FRAME='+str(ROOT/'engines/zmbor/ps2xTest/e2e/check_frame.py')]
    cmd+=['-P',str(ROOT/'engines/zmbor/ps2xTest/e2e/run_e2e.cmake')]
    with (work/'driver.log').open('w') as f:p=subprocess.run(cmd,cwd=work,stdout=f,stderr=subprocess.STDOUT)
    print('e2e',name,p.returncode,flush=True)
    (work/'result.json').write_text(json.dumps(dict(exit_code=p.returncode)))

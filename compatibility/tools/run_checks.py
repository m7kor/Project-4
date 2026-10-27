"""Run existing suites from isolated copies and retain their logs/exit codes."""
from pathlib import Path
import sys,shutil,subprocess,json,os
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/checks';out.mkdir(exist_ok=True)
env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
checks=[]
def run(name,cmd,cwd):
    with (out/(name+'.log')).open('w',encoding='utf-8') as f:
        p=subprocess.run(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
    record=dict(name=name,exit_code=p.returncode,command=list(map(str,cmd)))
    checks.append(record);print(name,p.returncode,flush=True)
    (out/'summary.json').write_text(json.dumps(checks,indent=2))
run('project4-python',[sys.executable,'-m','unittest','discover','-s','tests'],ROOT/'reference-tools')
for label,source in [('project4',Path('C:/Project/PS2redmption/core/out/build')),('zmbor',Path('D:/Project/Zmbor/wt-integration/build'))]:
    binary=out/label;binary.mkdir(exist_ok=True)
    for folder in ('ps2xIOP','ps2xTest'):
        for p in (source/folder).glob('*.exe'):
            if p.name!='ps2x_tests.exe' and folder=='ps2xTest':continue
            shutil.copy2(p,binary/p.name)
    for p in binary.glob('*.exe'):
        if p.name=='ps2x_tests.exe':continue
        run(label+'-'+p.stem,[str(p)],ROOT/'engines'/label)
    if (binary/'ps2x_tests.exe').exists():run(label+'-unit',[str(binary/'ps2x_tests.exe')],ROOT/'engines'/label)

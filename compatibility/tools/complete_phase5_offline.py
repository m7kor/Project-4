"""Wait for owned game measurements to end, then run final independent gates."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
import psutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/phase5/post-measurement-01';out.mkdir(exist_ok=False)
performance=ROOT/'artifacts/phase5/game-performance-01/report.json'
deadline=time.monotonic()+3600
while not performance.exists():
    if (ROOT/'artifacts/phase5/cancel-request.json').exists():raise SystemExit('Owner cancellation; no post-measurement work started')
    if time.monotonic()>deadline:raise TimeoutError('Measurement completion gate')
    time.sleep(1)
measured=json.loads(performance.read_text());assert measured['completed'],'Game measurements incomplete; no automatic retry'
assert not [p.info['name'] for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() in ('ps2entryrunner.exe','clang-cl.exe','lld-link.exe')]
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='9d57a24024632c1beeb84bc11eb4fc1d968598092e920b52b5093eb9bee347df'
temp=out/'temp';temp.mkdir();env={**os.environ,'TEMP':str(temp),'TMP':str(temp),'PYTHONIOENCODING':'utf-8'}
rows=[];start=time.monotonic()
def run(name,args,timeout):
    if (ROOT/'artifacts/phase5/cancel-request.json').exists():raise RuntimeError('Owner cancellation')
    begin=time.monotonic()
    with (out/(name+'.log')).open('x') as log:p=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    rows.append({'name':name,'returncode':p.returncode,'seconds':time.monotonic()-begin});print('Post-measurement gate',name,p.returncode,flush=True)
    (out/'progress.json').write_text(json.dumps(rows,indent=2));return p.returncode
wrapper=['cmd.exe','/c',ROOT/'lab/test-dev-env.cmd',sys.executable]
try:
    built=run('build-state-v2',wrapper+[ROOT/'tools/build_phase5_state_probe.py','phase5-fmac-state-v2-01','phase5-fmac-01','v2'],180)
    if built==0:
        run('equivalence-context-v2',[sys.executable,ROOT/'tools/validate_phase5_pipeline.py','--fmac','--probe-dir=phase5-fmac-state-v2-01','--out='+str(out/'equivalence-v2')],300)
        run('catalog-context-v2',[sys.executable,ROOT/'tools/validate_phase5_catalog.py','--probe-dir=phase5-fmac-state-v2-01','--out='+str(out/'catalog-v2'),'--reuse-fixtures='+str(ROOT/'artifacts/phase5/catalog-01/fixtures')],180)
        run('random-context-v2',[sys.executable,ROOT/'tools/validate_phase5_random.py','--fmac','--probe-dir=phase5-fmac-state-v2-01','--out='+str(out/'random-v2')],90)
    run('fmac-sanitizers',wrapper+[ROOT/'tools/validate_phase5_fmac_sanitizers.py'],180)
    run('full',[sys.executable,ROOT/'tools/lab_regression.py','full','--candidate-dir','lab/phase5-suite-02','--baseline-dir','lab/phase4-suite-02','--project4-recompiler',ROOT/'lab/phase4-fixed-01/ps2_recomp.exe','--vu-fmac-classify','1','--changed','engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'],420)
finally:
    report={'passed':len(rows)==6 and all(r['returncode']==0 for r in rows),'rows':rows,'seconds':time.monotonic()-start,'scope':'All heavy builds/tests began only after all14 controlled game runs ended'}
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)

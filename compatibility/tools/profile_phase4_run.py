"""Sample only the verified owned baseline; mark interference for timing exclusion."""
from pathlib import Path
import json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/phase4-baseline-01'
while not (run/'report.json').exists():
    try:
        state=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1]);identity=json.loads((run/'identity.json').read_text())
        if state['elapsed_seconds']>=175 and state['ee_vsync_tick']>=3300:break
        if state['elapsed_seconds']>215:raise RuntimeError('Required scene progress not reached before sampling deadline')
    except (OSError,ValueError,IndexError):pass
    time.sleep(1)
else:raise RuntimeError('Baseline ended before sampling criteria')
out=run/'phase4-profiler';out.mkdir(exist_ok=False);start=time.monotonic()
p=subprocess.run([sys.executable,ROOT/'reference-tools/tools/diagnostics/hot_thread_sampler.py','--pid',str(identity['pid']),'--expected-exe',run/'guest/ps2EntryRunner.exe','--seconds','10','--rate','100','--depth','12','--top','40'],capture_output=True,text=True,timeout=30)
(out/'stdout.txt').write_text(p.stdout);(out/'stderr.txt').write_text(p.stderr)
(out/'report.json').write_text(json.dumps({'returncode':p.returncode,'start_host_seconds':state['elapsed_seconds'],'start_ee_tick':state['ee_vsync_tick'],'elapsed_seconds':time.monotonic()-start,'rate_hz':100,'timing_exclusion':'Exclude this entire marked window plus2seconds on either side; thread suspension perturbs execution'},indent=2));print(p.stdout[-4000:]);raise SystemExit(p.returncode)

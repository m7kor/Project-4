"""Own one bounded Phase4-correctness runner and sample its loaded gameplay."""
from pathlib import Path
import hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/phase5-profile-base-01'
out=ROOT/'artifacts/phase5/profile-base-01';out.mkdir(parents=True,exist_ok=False)
binary=ROOT/'lab/phase4-game-03/ps2EntryRunner.exe'
assert hashlib.sha256(binary.read_bytes()).hexdigest()=='fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53'
command=[sys.executable,ROOT/'tools/run_lab.py','phase5-profile-base-01','180',binary,
 ROOT/'artifacts/phase4/game-acceptance/input.csv','replay',
 '--fixture='+str(ROOT/'artifacts/runs/manual-20261024-112541-942897/guest/saves'),'--capture-every=60','--audio-record','--vif-witness','--trace-pad']
with (out/'driver.log').open('x') as log:
 driver=subprocess.Popen(list(map(str,command)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 begin=time.monotonic()
 while time.monotonic()-begin<140 and driver.poll() is None:
  try:
   state=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1])
   if state['ee_vsync_tick']>=3500:break
  except (OSError,ValueError,IndexError):pass
  time.sleep(1)
 else:raise RuntimeError('Loaded-game profiling gate unavailable; owned driver remains bounded180s')
 identity=json.loads((run/'identity.json').read_text())
 sampler=[sys.executable,ROOT/'reference-tools/tools/diagnostics/hot_thread_sampler.py','--pid',str(identity['pid']),'--expected-exe',run/'guest/ps2EntryRunner.exe','--seconds','15','--rate','100','--depth','12','--top','50']
 p=subprocess.run(list(map(str,sampler)),cwd=ROOT,capture_output=True,text=True,timeout=40)
 (out/'stdout.txt').write_text(p.stdout);(out/'stderr.txt').write_text(p.stderr)
 (out/'sample.json').write_text(json.dumps({'returncode':p.returncode,'start_ee':state['ee_vsync_tick'],'start_elapsed_seconds':state['elapsed_seconds'],'runner_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'scope':'Diagnostic sample perturbs runtime, NOT controlled speed measurement'},indent=2))
 print(p.stdout[-6500:],flush=True)
 driver.wait(timeout=190)
 assert p.returncode==0
 result=json.loads((run/'report.json').read_text());assert result['terminated_at_planned_timeout'] and result['test_saves_unchanged']
 print('Owned profiling run ended, private card unchanged',flush=True)

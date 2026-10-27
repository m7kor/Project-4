"""Bounded, identity-checked thread samples after the loaded-game field gate."""
from pathlib import Path
import json,subprocess,sys,time,re
ROOT=Path(__file__).resolve().parents[1];run=ROOT/'artifacts/runs/architecture-profile-01'
out=ROOT/'artifacts/architecture/profile-01';out.mkdir(exist_ok=False)
start=time.monotonic()
while time.monotonic()-start<150:
 try:
  s=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1])
  if s['ee_vsync_tick']>=3500:break
 except (OSError,ValueError,IndexError):pass
 if (run/'report.json').exists():raise RuntimeError('Owned run ended before profiling')
 time.sleep(.5)
else:raise TimeoutError('Guest field3500 unavailable')
identity=json.loads((run/'identity.json').read_text());base=[sys.executable,str(ROOT/'reference-tools/tools/diagnostics/hot_thread_sampler.py'),'--pid',str(identity['pid']),'--expected-exe',str(run/'guest/ps2EntryRunner.exe'),'--rate','80','--depth','14','--top','80']
results=[];threads=[]
for i in range(3):
 args=base+['--seconds','8' if i==0 else '4']+([] if i==0 else ['--tid',str(threads[i])])
 before=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1]);begin=time.monotonic()
 p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=35)
 after=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1])
 (out/f'{i}.stdout.txt').write_text(p.stdout);(out/f'{i}.stderr.txt').write_text(p.stderr)
 assert p.returncode==0,(i,p.stderr)
 if i==0:
  threads=[int(x) for x in re.findall(r'tid=\s*(\d+)\s+[\d.]+%',p.stdout)]
  if len(threads)<3:raise RuntimeError('Insufficient live owned threads for separate costs')
 results.append({'index':i,'seconds':time.monotonic()-begin,'before':before,'after':after,'command':args})
 print('Sampled owned thread',i,flush=True)
(out/'report.json').write_text(json.dumps({'runner_sha256':identity['runner_sha256'],'samples':results,'scope':'Sequential thread-specific stack samples, perturbed diagnostic run; fractions are NOT whole-process wall fractions'},indent=2))

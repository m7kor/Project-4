"""One bounded replay-plus-feedback gate test. Native controller only; no guest writes."""
from pathlib import Path
import subprocess,sys,time,json
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/room-feedback-01';inputs=ROOT/'artifacts/navigation-inputs'
command=[sys.executable,str(ROOT/'tools/run_lab.py'),'room-feedback-01','900',str(ROOT/'lab/shared-link/ps2EntryRunner.exe'),str(inputs/'manual-room-feedback-start.csv'),'live','--fixture='+str(ROOT/'artifacts/runs/manual-20261024-112541-942897/guest/saves'),'--capture-every=60','--stream-trace','--audio-record']
with (ROOT/'artifacts/room-feedback-01-driver.log').open('x') as output:
 game=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
 try:
  deadline=time.monotonic()+330
  while time.monotonic()<deadline and game.poll() is None:
   try:
    state=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1])
    if state['ee_vsync_tick']>=4400:break
   except (OSError,ValueError,IndexError):pass
   time.sleep(.5)
  else:raise RuntimeError('Partial replay gate not reached')
  identity=json.loads((run/'identity.json').read_text());pid=identity['pid']
  common=['--pid',str(pid),'--run',str(run),'--identity',str(run/'identity.json'),'--exe',str(run/'guest/ps2EntryRunner.exe'),'--elf',str(run/'guest/SLUS_211.34'),'--exports',str(inputs/'player-exports.json'),'--room-exports',str(inputs/'room-exports.json'),'--movie-witness',str(inputs/'movie-witness.json')]
  subprocess.run([sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py'),*common,'--out',str(run/'route-start.json')],cwd=ROOT,check=True)
  start=json.loads((run/'route-start.json').read_text());assert start['completed']
  print('Starting new feedback hypothesis from observed partial replay pose',flush=True)
  route=[sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_feedback_route.py'),'--run',str(run),'--lab-owner',str(run),'--pid',str(pid),'--rdram-base',start['rdram_base'],'--exe',str(run/'guest/ps2EntryRunner.exe'),'--elf',str(run/'guest/SLUS_211.34'),'--exports',str(inputs/'player-exports.json'),'--room-exports',str(inputs/'room-exports.json'),'--movie-witness',str(inputs/'movie-witness.json'),'--route',str(inputs/'room100-user-gate-route.json'),'--timeout','540','--max-commands','80','--label','gate-feedback']
  with (run/'gate-controller.log').open('x') as log:
   subprocess.run(route,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=570,check=True)
  result=json.loads((run/'gate-feedback/summary.json').read_text());print('Feedback result',result['status'],flush=True)
  if result['status']=='arrived':
   subprocess.run([sys.executable,str(ROOT/'reference-tools/tools/diagnostics/live_pad_command.py'),'--run',str(run),'--lab-owner',str(run),'--buttons','49151','--delay','40','--duration','16'],cwd=ROOT,check=True)
   time.sleep(12)
  subprocess.run([sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py'),*common,'--rdram-base',start['rdram_base'],'--samples','20','--interval','1','--out',str(run/'route-final.json')],cwd=ROOT,check=True)
 finally:
  if run.exists() and not (run/'report.json').exists():
   (run/'stop-request.json').write_text(json.dumps({'reason':'Bounded gate hypothesis complete or first blocker; preserve all results'}))
  game.wait(timeout=30)

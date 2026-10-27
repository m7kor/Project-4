"""Optional Windows GPU-engine counters for the two owned long runs, post-window."""
from pathlib import Path
import hashlib,json,subprocess,time
import psutil
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/phase5/gpu-observations-02';out.mkdir(exist_ok=False)
for mode in ('0','1'):
 run=ROOT/'artifacts/runs'/('phase5-perf-6-'+mode);start=time.monotonic();result={'mode':mode,'available':False,'scope':'Post-measurement only, EE>=4000; owned-process GPU-engine counters, not GPU timestamps or whole-device occupancy'}
 try:
  while time.monotonic()-start<3600:
   failure=ROOT/'artifacts/phase5/game-performance-01/report.json'
   if failure.exists() and not json.loads(failure.read_text()).get('completed'):raise RuntimeError('Controlled benchmark ended before GPU observation')
   try:
    with (run/'diagnostics/state.jsonl').open('rb') as stream:
     stream.seek(max(0,(run/'diagnostics/state.jsonl').stat().st_size-16384));state=json.loads(stream.read().splitlines()[-1])
    if state['ee_vsync_tick']>=4000:break
   except (OSError,ValueError,IndexError):pass
   time.sleep(1)
  else:raise TimeoutError('GPU observation gate')
  identity=json.loads((run/'identity.json').read_text());pid=identity['pid'];exe=run/'guest/ps2EntryRunner.exe'
  assert Path(psutil.Process(pid).exe()).resolve()==exe.resolve()
  assert hashlib.sha256(exe.read_bytes()).hexdigest()==identity['runner_sha256']
  command=r"$ErrorActionPreference='Stop'; Get-Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 1 -MaxSamples 3 | ForEach-Object { $_.CounterSamples | Where-Object { $_.InstanceName -like 'pid___PID___*' } | Select-Object InstanceName,CookedValue } | ConvertTo-Json -Depth 3"
  command=command.replace('__PID__',str(pid))
  command=command.replace(chr(92)+chr(92),chr(92))
  p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=10,creationflags=0x08000000)
  (out/(mode+'.txt')).write_text(p.stdout+p.stderr);result.update(pid=pid,start_ee=state['ee_vsync_tick'],returncode=p.returncode)
  if p.returncode==0 and p.stdout.strip():result.update(available=True,samples=json.loads(p.stdout))
  else:result['reason']=p.stderr[-1000:] or 'No owned GPU engine counter returned'
 except Exception as error:result['reason']=str(error)
 (out/(mode+'.json')).write_text(json.dumps(result,indent=2));print('Post-window GPU observation',mode,result['available'],flush=True)

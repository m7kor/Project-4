"""Complete current validation once the owned isolated link succeeds."""
from pathlib import Path
import time,json,hashlib,subprocess,sys,re
ROOT=Path(__file__).resolve().parents[1]
exe=ROOT/'lab/fusion-link/ps2EntryRunner.exe'
manifest=exe.parent/'identity.json'
deadline=time.monotonic()+1800
print('Waiting for verified isolated link manifest',flush=True)
while time.monotonic()<deadline:
    try:
        expected=json.loads(manifest.read_text()).get(exe.name)
        if expected and exe.is_file() and hashlib.sha256(exe.read_bytes()).hexdigest()==expected:break
    except (OSError,ValueError):pass
    time.sleep(2)
else:raise RuntimeError('No successful complete runner link manifest within30minutes')
print('Verified fused runner. Starting same-input180s comparison.',flush=True)
subprocess.run([sys.executable,str(ROOT/'tools/run_lab.py'),'fusion-01','180',str(exe)],cwd=ROOT,check=True)
run=ROOT/'artifacts/runs/fusion-01'
report=json.loads((run/'report.json').read_text())
rows=[json.loads(l) for l in (run/'diagnostics/state.jsonl').read_text().splitlines()]
faults=[]
for name in ('stdout.txt','stderr.txt'):
    faults += re.findall(r'guest-branch:missing-target|runtime exception|access violation|\[terminate\]|VK_ERROR',(run/name).read_text(errors='replace'),re.I)
assert report['terminated_at_planned_timeout'] and report['test_saves_unchanged'] and rows[-1]['ee_vsync_tick']>=4900 and not faults,(report,faults)
subprocess.run([sys.executable,str(ROOT/'tools/compare_runs.py'),'candidate-01','fusion-01'],cwd=ROOT,check=True)
print('Comparison complete. Starting600s known house-entry input.',flush=True)
subprocess.run([sys.executable,str(ROOT/'tools/run_lab.py'),'fusion-play','600',str(exe),
               'C:/Project/PS2redmption/artifacts/verification/review-20261018-house-right-room-controls-v9.csv'],cwd=ROOT,check=True)
print('Fusion gameplay run ended; requires visual and state review before acceptance.',flush=True)

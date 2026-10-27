"""Launch the validated private lab runner with a fresh copy of the latest clean manual save."""
from pathlib import Path
from datetime import datetime
import json,subprocess,sys,hashlib
ROOT=Path(__file__).resolve().parents[1]
binary=ROOT/'lab/shared-link/ps2EntryRunner.exe'
manifest=json.loads((binary.parent/'identity.json').read_text())
assert hashlib.sha256(binary.read_bytes()).hexdigest()==manifest[binary.name]
assert json.loads((ROOT/'artifacts/experiments/vu-shared-regions/validation-v2/summary.json').read_text())['all_matched']
fixtures=[]
for run in (ROOT/'artifacts/runs').glob('manual-*'):
    report=run/'report.json'
    if not report.exists():continue
    r=json.loads(report.read_text())
    card=run/'guest/saves/cards/native-card-0.ps2'
    if r.get('input_mode')=='manual' and r.get('exit_code')==0 and card.is_file():
        expected=r['saves_after'].get('cards\\native-card-0.ps2')
        if expected and hashlib.sha256(card.read_bytes()).hexdigest()==expected:
            fixtures.append((report.stat().st_mtime,run/'guest/saves'))
assert fixtures,'No verified private manual save fixture'
fixture=max(fixtures,key=lambda item:item[0])[1]
if '--check' in sys.argv:
    print(json.dumps({'runner_sha256':manifest[binary.name],'private_fixture':str(fixture),'launch_ready':True},indent=2))
    raise SystemExit(0)
label='manual-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
print('Private RE4 lab session:',label,flush=True)
print('Test duration limit: one hour. Session saves remain under artifacts/runs/'+label+'/guest/saves.',flush=True)
print('Original game data and original saves are not modified.',flush=True)
subprocess.run([sys.executable,str(ROOT/'tools/run_lab.py'),label,'3600',str(binary),'-','manual','--fixture='+str(fixture)],cwd=ROOT,check=True)

"""Continue only after the owned link manifest verifies; never overlap timing with build."""
from pathlib import Path
import time,json,hashlib,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
exe=ROOT/'lab/shared-link/ps2EntryRunner.exe'
print('Waiting for successful completed shared-region runner link',flush=True)
deadline=time.monotonic()+2400
while time.monotonic()<deadline:
    try:
        manifest=json.loads((exe.parent/'identity.json').read_text())
        expected=manifest.get(exe.name)
        if expected and exe.is_file() and hashlib.sha256(exe.read_bytes()).hexdigest()==expected:break
    except (OSError,ValueError):pass
    time.sleep(2)
else:raise RuntimeError('No completed verified runner link within bounded wait')
print('Runner verified. Starting isolated alternating measurements.',flush=True)
subprocess.run([sys.executable,str(ROOT/'tools/benchmark_shared_regions.py')],cwd=ROOT,check=True)
print('Isolated measurements complete. Starting matched saved-scene pairs.',flush=True)
subprocess.run([sys.executable,str(ROOT/'tools/run_shared_game_comparison.py')],cwd=ROOT,check=True)
print('Matched pairs completed; visual review required.',flush=True)

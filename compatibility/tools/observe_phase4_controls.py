"""Read-only observations after the candidate's matched speed interval."""
from pathlib import Path
import json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];run=ROOT/'artifacts/runs/phase4-candidate-01';begin=time.monotonic()
while time.monotonic()-begin<1800:
    try:
        identity=json.loads((run/'identity.json').read_text());state=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1])
        if state['ee_vsync_tick']>=4700:break
        if (run/'report.json').exists():raise RuntimeError('Candidate ended before control observation gate')
    except (OSError,ValueError,IndexError):pass
    time.sleep(2)
else:raise TimeoutError('Candidate control observation deadline')
inputs=ROOT/'artifacts/navigation-inputs'
cmd=[sys.executable,ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py','--pid',str(identity['pid']),'--run',run,'--identity',run/'identity.json','--exe',run/'guest/ps2EntryRunner.exe','--elf',run/'guest/SLUS_211.34','--exports',inputs/'player-exports.json','--room-exports',inputs/'room-exports.json','--movie-witness',inputs/'movie-witness.json','--samples','60','--interval','1','--out',run/'phase4-controls-observations.json']
p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=100)
(run/'phase4-controls-observer.log').write_text(p.stdout+p.stderr)
print('Read-only control observer exit',p.returncode);raise SystemExit(p.returncode)

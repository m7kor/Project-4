"""Continue one explicit bounded route on the still-owned isolated game process."""
from pathlib import Path
import sys,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/regions-route';inputs=ROOT/'artifacts/navigation-inputs'
assert not (run/'report.json').exists()
label=sys.argv[1];route=Path(sys.argv[2]).resolve();timeout=int(sys.argv[3]);commands=int(sys.argv[4])
assert route.is_relative_to(inputs.resolve()) and route.is_file()
identity=json.loads((run/'identity.json').read_text());start=json.loads((run/'route-start.json').read_text())
assert identity['pid']==start['pid'] and start['completed']
command=[sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_feedback_route.py'),
    '--run',str(run),'--lab-owner',str(run),'--pid',str(identity['pid']),'--rdram-base',start['rdram_base'],
    '--exe',str(run/'guest/ps2EntryRunner.exe'),'--elf',str(run/'guest/SLUS_211.34'),
    '--exports',str(inputs/'player-exports.json'),'--room-exports',str(inputs/'room-exports.json'),
    '--movie-witness',str(inputs/'movie-witness.json'),'--route',str(route),'--timeout',str(timeout),
    '--max-commands',str(commands),'--label',label]
with (run/(label+'-driver.log')).open('x') as log:
    result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout+30)
print('Bounded route ended',result.returncode,flush=True)

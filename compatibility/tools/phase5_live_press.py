"""Publish at a fresh diagnostic boundary: fast menus can outrun a stale capture."""
from pathlib import Path
import importlib.util,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'reference-tools/tools/diagnostics/live_pad_command.py'
spec=importlib.util.spec_from_file_location('phase5_live_reference',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
run=Path(sys.argv[1]).resolve(strict=True)
assert run.is_relative_to((ROOT/'artifacts/runs').resolve()) and not (run/'report.json').exists()
state=run/'diagnostics/state.jsonl'
def latest():
 with state.open('rb') as f:
  f.seek(max(0,state.stat().st_size-16384));return json.loads(f.read().splitlines()[-1])
initial=latest()['tick'];start=time.monotonic()
while latest()['tick']==initial:
 if (run/'report.json').exists() or time.monotonic()-start>15:raise TimeoutError('No fresh owned diagnostic capture')
 time.sleep(.01)
# Delegate ownership, interval validation, atomic publication and receipts to existing tool.
sys.argv=[str(path),'--run',str(run),'--lab-owner',str(run),'--buttons',sys.argv[2],'--duration','16','--delay','120']
m.main()

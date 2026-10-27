"""Explain why historical transition input is not an exact replay fixture."""
from pathlib import Path
import hashlib,json,sys
from replay_input_quality import parse_guest_trace,field_replay
ROOT=Path(__file__).resolve().parents[1];run=ROOT/'artifacts/runs/manual-20261024-112541-942897'
out=ROOT/'artifacts/phase5/route-audit-01';out.mkdir(exist_ok=False)
identity=json.loads((run/'identity.json').read_text());log=run/'stderr.txt'
assert identity['runner_sha256']=='e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a'
events=parse_guest_trace(log.read_text(errors='replace'))
states=[json.loads(line) for line in (run/'diagnostics/state.jsonl').read_text().splitlines()]
report={'runner_sha256':identity['runner_sha256'],'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'guest_events':len(events),'trace_guest_tick_range':[min(e['tick'] for e in events),max(e['tick'] for e in events)],'diagnostic_guest_tick_range':[min(s['ee_vsync_tick'] for s in states),max(s['ee_vsync_tick'] for s in states)],'scope':'Input recording quality; does not invalidate independently observed historical room100->101. No new navigation launch or invented timing.'}
try:
 rows=field_replay(events);report.update(replay_build_possible=True,rows=len(rows))
except ValueError as error:report.update(replay_build_possible=False,blocker=str(error))
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));raise SystemExit(0 if report['replay_build_possible'] else 2)

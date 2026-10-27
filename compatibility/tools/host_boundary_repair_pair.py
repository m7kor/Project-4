"""Replace pair4's mismatched observer conditions; keep every original sample."""
from pathlib import Path
import json,sys
from host_boundary_measure_game import prepared_source
ROOT=Path(__file__).resolve().parents[1]
prior=ROOT/'artifacts/host-boundary/game-performance-02/report.json'
assert prior.exists() and json.loads(prior.read_text())['completed'],'Finish the original continuation first'
script,text=prepared_source()
text=text.replace("ROOT/'artifacts/host-boundary/game-performance-01'","ROOT/'artifacts/host-boundary/game-performance-03'")
assert text.count('range(7)')==2;text=text.replace('range(7)','range(4,5)')
text=text.replace("label=f'host-boundary-perf-{pair}-{mode}'","label=f'host-boundary-perf-repair-{pair}-{mode}'")
text=text.replace('Seven alternating pairs. Monotonic sampled guest progress. Last pair extends to ordinary controls; observer activity must start after the measurement interval.',
                  'Preregistered replacement of pair4 after original observer failure. Both reference and candidate have identical host monitoring. Original pair4 retained as supplemental, never selected by speed. Same3300..3900 guest interval and fixtures.')
sys.argv=[str(script),str(ROOT/'artifacts/host-boundary/gate-01/report.json')]
exec(compile(text,str(script),'exec'),{'__file__':str(script),'__name__':'__main__'})

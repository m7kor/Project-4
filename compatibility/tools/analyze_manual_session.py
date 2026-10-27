"""Summarize observed input publication/consumption and guest speed, not display latency."""
from pathlib import Path
import re,json,statistics
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/manual-play-02'
lines=(run/'stderr.txt').read_text(errors='replace').splitlines()
pattern=re.compile(r'\[pad trace\] stage=(host|guest).*?focused=(-?\d+).*?buttons=(\d+) lx=(\d+) ly=(\d+) rx=(\d+) ry=(\d+) host_ms=(\d+)')
latest=None;delays=[];consumed=0
for line in lines:
    m=pattern.search(line)
    if not m:continue
    stage,focused,*values=m.groups();state=tuple(map(int,values[:-1]));stamp=int(values[-1])
    if stage=='host':latest=(state,stamp) if focused=='1' else None
    else:
        consumed+=1
        if latest and state==latest[0] and 0<=stamp-latest[1]<=1000:delays.append(stamp-latest[1])
sorted_delays=sorted(delays)
states=[json.loads(s) for s in (run/'diagnostics/state.jsonl').read_text().splitlines()]
audio=[]
for line in lines:
    m=re.search(r'\[audio\] requested=(\d+) delivered=(\d+) underrun=(\d+) tempo=([\d.]+)',line)
    if m:audio.append(dict(zip(('requested','delivered','underrun','tempo'),map(float,m.groups()))))
record={'scope':'Observed software publication-to-native-consumption only, not controller hardware or display response latency; sampled on state changes',
        'matched_changed_states':len(delays),'native_changed_state_records':consumed,
        'delivery_ms_median':statistics.median(delays),'delivery_ms_p95':sorted_delays[int(.95*(len(sorted_delays)-1))],
        'delivery_ms_max':max(delays),'last_audio':audio[-1],
        'last_ee':states[-1]['ee_vsync_tick'],'last_capture_seconds':states[-1]['elapsed_seconds'],
        'exit':json.loads((run/'report.json').read_text())['exit_code']}
(run/'manual-analysis.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2))

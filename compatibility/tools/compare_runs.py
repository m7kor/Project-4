"""Compare the same guest-field interval using Project4's sparse-endpoint model."""
from pathlib import Path
import json,sys,re,importlib.util
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reference-tools/tools/diagnostics'))
from game_speed_compare import endpoint,HZ
runs=[]
labels=tuple(sys.argv[1:3]) if len(sys.argv)>2 else ('baseline-01','candidate-01')
first,last=(int(sys.argv[3]),int(sys.argv[4])) if len(sys.argv)>4 else (4600,4900)
assert 0<=first<last
for label in labels:
    run=ROOT/'artifacts/runs'/label
    report=json.loads((run/'report.json').read_text())
    rows=[json.loads(line) for line in (run/'diagnostics/state.jsonl').read_text().splitlines()]
    a,ab=endpoint(rows,first);b,bb=endpoint(rows,last)
    longest=bb[1]-ab[0];shortest=bb[0]-ab[1]
    audio=[]
    for line in (run/'stderr.txt').read_text(errors='replace').splitlines():
        m=re.search(r'\[audio\] requested=(\d+) delivered=(\d+) underrun=(\d+) tempo=([\d.]+) peak=(\d+)',line)
        if m:audio.append(dict(zip(('requested','delivered','underrun','tempo','peak'),map(float,m.groups()))))
    runs.append(dict(label=label,input_sha256=report['input_sha256'],elf_sha256=report['elf_sha256'],saves_before=report['saves_before'],settings=report['settings'],
                     first_ee=first,last_ee=last,estimated_seconds=b-a,estimated_speed=((last-first)/HZ)/(b-a),
                     sparse_speed_bounds=[((last-first)/HZ)/longest,((last-first)/HZ)/shortest] if shortest>0 else None,
                     audio_last=audio[-1] if audio else None,
                     last_counters={k:rows[-1][k] for k in ('dma','gif','vif','ipu_cmds','ee_vsync_tick')}))
for key in ('input_sha256','elf_sha256','saves_before'):assert runs[0][key]==runs[1][key],key
settings=lambda r:{k:v for k,v in r['settings'].items() if k not in ('PS2X_NATIVE_PAD_REPLAY','PS2X_CAPTURE_DIR')}
assert settings(runs[0])==settings(runs[1])
result=dict(scope='One matched cold-boot pair, same private fixture and input; sparse endpoint uncertainty. No established performance gain.',
            runs=runs,estimated_rate_change_percent=(runs[1]['estimated_speed']/runs[0]['estimated_speed']-1)*100)
target=ROOT/'artifacts'/('controlled-comparison.json' if not sys.argv[1:] else 'comparison-'+labels[0]+'-'+labels[1]+'.json')
target.write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))

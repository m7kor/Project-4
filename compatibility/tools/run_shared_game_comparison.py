"""Two alternating matched saved-scene pairs; no profiler or RAM reader while timing."""
from pathlib import Path
import subprocess,sys,json,hashlib,time
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-shared-regions'
new=ROOT/'lab/shared-link/ps2EntryRunner.exe'
manifest=json.loads((new.parent/'identity.json').read_text())
assert hashlib.sha256(new.read_bytes()).hexdigest()==manifest[new.name]
assert json.loads((out/'validation-v2/summary.json').read_text())['all_matched']
assert (out/'timing/summary.json').exists(), 'Finish isolated benchmarks before game comparisons'
bins={'base':ROOT/'lab/fusion-link/ps2EntryRunner.exe','shared':new}
fixture='--fixture='+str(ROOT/'artifacts/runs/manual-play-02/guest/saves')
tape=ROOT/'artifacts/navigation-inputs/load-private-save-v3.csv'
labels=[]
for pair in range(2):
    for mode in (('base','shared') if pair%2==0 else ('shared','base')):
        label=f'regions-p{pair}-{mode}';labels.append(label)
        print('Matched saved-scene run',label,flush=True)
        subprocess.run([sys.executable,str(ROOT/'tools/run_lab.py'),label,'180',str(bins[mode]),str(tape),'replay',fixture,'--capture-every=60'],cwd=ROOT,check=True)
        report=json.loads((ROOT/'artifacts/runs'/label/'report.json').read_text())
        assert report['test_saves_unchanged'] and report['terminated_at_planned_timeout']
    subprocess.run([sys.executable,str(ROOT/'tools/compare_runs.py'),f'regions-p{pair}-base',f'regions-p{pair}-shared','3300','3900'],cwd=ROOT,check=True)
records=[]
for label in labels:
    run=ROOT/'artifacts/runs'/label
    rows=[json.loads(s) for s in (run/'diagnostics/state.jsonl').read_text().splitlines()]
    mid=min(rows,key=lambda row:abs(row['ee_vsync_tick']-3600))
    records.append({'label':label,'review_frame':str(run/'diagnostics'/f"frame-{mid['tick']}.png"),'nearest_ee':mid['ee_vsync_tick']})
(out/'game-comparison-frames.json').write_text(json.dumps(records,indent=2))
print('Both pairs completed; inspect matching-scene images before acceptance',flush=True)

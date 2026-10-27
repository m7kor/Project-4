"""Aggregate alternating real-game pairs and verify private runtime dependencies."""
from pathlib import Path
import json,statistics,hashlib,re
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-shared-regions'
frames=json.loads((out/'game-comparison-frames.json').read_text())
pairs=[];dlls=[];records=[]
for pair in range(2):
    comparison=json.loads((ROOT/f'artifacts/comparison-regions-p{pair}-base-regions-p{pair}-shared.json').read_text())
    a,b=comparison['runs']
    pairs.append({'pair':pair,'base_speed':a['estimated_speed'],'shared_speed':b['estimated_speed'],
        'speed_increase_percent':comparison['estimated_rate_change_percent'],
        'sampling_uncertainty_percent_bounds':[(b['sparse_speed_bounds'][0]/a['sparse_speed_bounds'][1]-1)*100,
                                              (b['sparse_speed_bounds'][1]/a['sparse_speed_bounds'][0]-1)*100]})
    for row in (a,b):
        run=ROOT/'artifacts/runs'/row['label'];report=json.loads((run/'report.json').read_text())
        assert report['test_saves_unchanged'] and report['terminated_at_planned_timeout']
        for name in ('stdout.txt','stderr.txt'):
            assert not re.search(r'guest-branch:missing-target|runtime exception|access violation|\[terminate\]|VK_ERROR',(run/name).read_text(errors='replace'),re.I)
        dlls.append({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (run/'guest').glob('*.dll')})
        records.append({'label':row['label'],'peak_rss_bytes':report['peak_rss_bytes'],'binary_sha256':report['runner_sha256'],'card_unchanged':True,'audio':row['audio_last']})
assert all(dlls[0]==d for d in dlls)
record={'scope':'Two alternating matched cold-boot pairs from the same private saved scene; scene-specific speed, not global FPS or full-speed compatibility',
    'window_ee':[3300,3900],'capture_every_host_ticks':60,'pairs':pairs,
    'median_speed_increase_percent':statistics.median(p['speed_increase_percent'] for p in pairs),
    'median_base_speed':statistics.median(p['base_speed'] for p in pairs),'median_shared_speed':statistics.median(p['shared_speed'] for p in pairs),
    'all_dependency_dlls_identical':True,'records':records,'matching_scene_frames':frames,
    'limits':['Sampling bounds are not statistical confidence intervals','Only one stationary saved scene','No profiler or RAM observer during timing','Graphics require recorded visual review']}
(out/'game-comparison-summary.json').write_text(json.dumps(record,indent=2))
print(json.dumps({k:record[k] for k in ('pairs','median_speed_increase_percent','median_base_speed','median_shared_speed','all_dependency_dlls_identical')},indent=2))

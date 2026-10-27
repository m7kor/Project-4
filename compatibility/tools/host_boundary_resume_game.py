"""Continue the interrupted seven-pair experiment without rerunning good pairs."""
from pathlib import Path
import sys
from host_boundary_measure_game import prepared_source
ROOT=Path(__file__).resolve().parents[1]
script,text=prepared_source()
text=text.replace("ROOT/'artifacts/host-boundary/game-performance-01'","ROOT/'artifacts/host-boundary/game-performance-02'")
marker='    try:\n        for pair in range(7):';assert text.count(marker)==1
recover='''    prior_path=ROOT/'artifacts/host-boundary/game-performance-01/report.json'
    prior=json.loads(prior_path.read_text())
    assert not prior['completed'] and len(prior['runs'])==8
    result['runs']=list(prior['runs']);result['resumed_from_sha256']=sha(prior_path)
    recovered=ROOT/'artifacts/runs/host-boundary-perf-4-0'
    recovered_report=json.loads((recovered/'report.json').read_text())
    assert recovered_report['process_exit_observed'] and recovered_report['test_saves_unchanged']
    assert recovered_report['runner_sha256']==sha(baseline) and recovered_report['input_sha256']==result['input_sha256']
    assert recovered_report['terminated_at_requested_stop']
    samples=[json.loads(line) for line in (recovered/'diagnostics/state.jsonl').read_text().splitlines()]
    a,ab=endpoint(samples,3300);b,bb=endpoint(samples,3900);guest=600/HZ
    result['runs'].append({'pair':4,'mode':'0','run':str(recovered),'runner_sha256':sha(baseline),'speed':guest/(b-a),'wall_seconds':b-a,'bounds':[guest/(bb[1]-ab[0]),guest/(bb[0]-ab[1])],'peak_rss_bytes':recovered_report['peak_rss_bytes'],'private_card_unchanged':True,'recovered_after_observer_failure':True,'continuous_host_meters_available':False})
    (out/'progress.json').write_text(json.dumps(result,indent=2))
'''
text=text.replace(marker,recover+marker)
marker="                assert sha(candidate)==identity['runner_sha256']";assert text.count(marker)==1
text=text.replace(marker,"                if any(r['pair']==pair and r['mode']==mode for r in result['runs']):continue\n"+marker)
sys.argv=[str(script),str(ROOT/'artifacts/host-boundary/gate-01/report.json')]
exec(compile(text,str(script),'exec'),{'__file__':str(script),'__name__':'__main__'})

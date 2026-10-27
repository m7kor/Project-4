"""Reuse controlled Phase5 scene/input methodology for the new ABI candidate."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
def prepared_source():
    script=ROOT/'tools/measure_phase5_game.py';text=script.read_text()
    old="timing=json.loads((ROOT/'artifacts/phase5/timing-04/report.json').read_text())\n    if not timing['all_pairs_improved'] or timing['median_cost_reduction_percent']<=0:"
    new="timing=json.loads((ROOT/'artifacts/host-boundary/benchmark-01/report.json').read_text())\n    if not timing['completed'] or not all(r['positive_pairs']==7 and r['median_paired_cost_reduction_percent']>0 for r in timing['summary'].values()):"
    assert text.count(old)==1;text=text.replace(old,new)
    text=text.replace("gate['passed'] and gate['vu_fmac_classify']=='1'","gate['passed'] and gate['candidate_sha256']=='ad1d9722779cc171366e8123f7339dc74151971a3694d0adea0d9fb5f50f9d7e'")
    text=text.replace("ROOT/'lab/phase5-game-02/ps2EntryRunner.exe'","ROOT/'lab/host-boundary-game-01/ps2EntryRunner.exe'")
    text=text.replace("ROOT/'artifacts/phase5/game-performance-01'","ROOT/'artifacts/host-boundary/game-performance-01'")
    text=text.replace("label=f'phase5-perf-{pair}-{mode}'","label=f'host-boundary-perf-{pair}-{mode}'")
    text=text.replace("'--vu-fmac-classify='+mode","'--vu-aot-coverage=0'")
    assert 'phase5-game-02' not in text and '--vu-fmac-classify' not in text
    return script,text

if __name__=='__main__':
    script,text=prepared_source()
    sys.argv=[str(script),str(ROOT/'artifacts/host-boundary/gate-01/report.json')]
    exec(compile(text,str(script),'exec'),{'__file__':str(script),'__name__':'__main__'})

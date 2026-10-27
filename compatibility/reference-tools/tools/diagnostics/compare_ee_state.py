"""Compare EE thread and semaphore state of two runs at the same EE vsync tick.

Takes the state.jsonl snapshot nearest to --tick in each run and prints the
threads (status, wait reason/id, pc, ra) and semaphores (count, waiters) that
differ, so a pass/fail pair shows what the stalled run is still waiting for.

    python -I tools/diagnostics/compare_ee_state.py PASSRUN FAILRUN --tick 7450
"""
import argparse
import json
from pathlib import Path


def nearest(run, tick):
    best = None
    with open(run / 'diagnostics' / 'state.jsonl', encoding='utf-8') as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if best is None or abs(row['ee_vsync_tick'] - tick) < abs(best['ee_vsync_tick'] - tick):
                best = row
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('a', type=Path)
    parser.add_argument('b', type=Path)
    parser.add_argument('--tick', type=int, required=True)
    args = parser.parse_args()
    a, b = nearest(args.a, args.tick), nearest(args.b, args.tick)
    print(f'A tick {a["ee_vsync_tick"]}  B tick {b["ee_vsync_tick"]}')
    for key in ('ipu_cmds', 'ipu_ch3_kicks', 'ipu_ch4_kicks', 'dma', 'gif'):
        print(f'  {key}: A={a.get(key)} B={b.get(key)}')
    ta = {t['id']: t for t in a['threads']}
    tb = {t['id']: t for t in b['threads']}
    print('threads (id: status wait_reason/wait_id pc ra):')
    for tid in sorted(set(ta) | set(tb)):
        def fmt(t):
            return '-' if t is None else f'{t["status"]} {t["wait_reason"]}/{t["wait_id"]} pc={t["pc"]:#x} ra={t["ra"]:#x}'
        x, y = fmt(ta.get(tid)), fmt(tb.get(tid))
        print(f'  {"*" if x != y else " "}{tid:3d}: A {x:45s} B {y}')
    sa = {s['id']: s for s in a['semaphores']}
    sb = {s['id']: s for s in b['semaphores']}
    print('semaphores that differ (id: A count/waiters, B count/waiters):')
    for sid in sorted(set(sa) | set(sb)):
        x = sa.get(sid)
        y = sb.get(sid)
        fx = '-' if x is None else f'{x["count"]}/{x["waiters"]}'
        fy = '-' if y is None else f'{y["count"]}/{y["waiters"]}'
        if fx != fy:
            print(f'  {sid:4d}: A {fx:8s} B {fy}')


if __name__ == '__main__':
    main()

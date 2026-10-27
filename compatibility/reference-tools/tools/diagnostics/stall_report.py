"""Summarize where a native RE4 capture stopped making progress.

Reads one closed capture directory (report.json, stdout.txt, stderr.txt,
diagnostics/state.jsonl) and prints, without modifying anything:
  - native module binds/rejections/untranslated modules and missing targets,
  - EE progress (VSync ticks, GIF packets, GS writes) and the point where GS
    output collapsed (the start of a black screen),
  - the last CDVD reads (ordinal 63 a0=LSN a1=sectors) and how long before the
    end of the capture they happened, when the CDVD trace was enabled,
  - the busiest sampled EE PCs after the stall.

    python -m tools.diagnostics.stall_report artifacts/runs/<capture>
"""
import argparse
import collections
import json
from pathlib import Path
import re

CDVD = re.compile(r'\[CDVD import\] (?:cycles=(\d+) )?ordinal=(\d+) .*?a0=(0x[0-9a-f]+) a1=(0x[0-9a-f]+)')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    cap = args.capture
    out = (cap / 'stdout.txt').read_text(encoding='utf-8', errors='replace') if (cap / 'stdout.txt').exists() else ''
    err = (cap / 'stderr.txt').read_text(encoding='utf-8', errors='replace') if (cap / 'stderr.txt').exists() else ''

    print('== native modules')
    for line in (out + err).splitlines():
        if line.startswith('[native-module:'):
            print('  ' + line[:200])
    missing = [l for l in err.splitlines() if '[guest-branch:missing-target]' in l]
    print(f'== missing targets: {len(missing)}')
    for line in missing[:8]:
        print('  ' + line[:260])

    states = [json.loads(l) for l in (cap / 'diagnostics' / 'state.jsonl').read_text().splitlines() if l.strip()]
    print(f'== EE progress: {len(states)} samples, last ee={states[-1]["ee_vsync_tick"]} host={states[-1]["tick"]}')
    # GS writes per EE tick over sliding windows; find where it collapsed.
    rates = []
    for a, b in zip(states, states[1:]):
        dt = max(1, b['ee_vsync_tick'] - a['ee_vsync_tick'])
        rates.append((b['ee_vsync_tick'], (b['gs_writes'] - a['gs_writes']) / dt, (b['gif'] - a['gif']) / dt))
    peak = max((r[1] for r in rates), default=0)
    collapse = None
    for i, (tick, gsw, _) in enumerate(rates):
        if peak and gsw < 0.1 * peak and all(r[1] < 0.1 * peak for r in rates[i:]):
            collapse = tick
            break
    print(f'  peak GS writes/tick {peak:.1f}; GS output stays below 10% of peak from ee={collapse}')
    # Captured frames are the direct evidence of a black screen.
    try:
        from PIL import Image, ImageStat
        frames = sorted((cap / 'diagnostics').glob('frame-*.png'), key=lambda p: int(re.sub(r'\D', '', p.stem)))
        means = [(int(re.sub(r'\D', '', f.stem)), sum(ImageStat.Stat(Image.open(f).convert('L')).mean)) for f in frames]
        black_from = None
        for i, (tick, mean) in enumerate(means):
            if all(m < 4.0 for _, m in means[i:]):
                black_from = tick
                break
        print(f'  {len(means)} frames; frames stay black (mean luma < 4) from host tick {black_from}')
        if black_from is not None:
            host_to_ee = {s['tick']: s['ee_vsync_tick'] for s in states}
            nearest = min(host_to_ee, key=lambda t: abs(t - black_from))
            collapse = host_to_ee[nearest]
            print(f'  which is about ee={collapse}')
    except ImportError:
        pass

    reads = [(int(c or 0), int(o), int(a, 16), int(b, 16)) for c, o, a, b in CDVD.findall(err)]
    if reads:
        last_cycle = reads[-1][0]
        r63 = [r for r in reads if r[1] == 63]
        print(f'== CDVD: {len(reads)} imports, {len(r63)} sector reads; last import at IOP cycle {last_cycle}')
        for cycle, _, lsn, count in r63[-12:]:
            print(f'  read lsn={lsn:#x} sectors={count:#x} at cycle {cycle}')
        ordinals = collections.Counter(r[1] for r in reads[-200:])
        print('  last-200 ordinals', dict(ordinals))
    else:
        print('== CDVD: no trace lines (set PS2X_TRACE_CDVD=1 and PS2X_TRACE_CDVD_LIMIT)')

    if collapse is not None:
        after = [s for s in states if s['ee_vsync_tick'] >= collapse]
        pcs = collections.Counter((f'{s["pc"]:#x}', f'{s["ra"]:#x}', s['running_thread']) for s in after)
        print('== sampled EE pc/ra/thread after the collapse')
        for key, count in pcs.most_common(10):
            print(f'  {count:4d} {key}')
        last = after[-1]
        print('  threads:', ' '.join(f'{t["id"]}:{t["status"]}/{t["wait_reason"]}/{t["wait_id"]}@{t["pc"]:#x}'
                                     for t in last['threads']))


if __name__ == '__main__':
    main()

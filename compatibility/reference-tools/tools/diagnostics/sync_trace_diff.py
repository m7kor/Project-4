"""Find where two runs' EE synchronisation traces first diverge.

Both runs must have been started with PS2X_TRACE_SYNC_FROM=0. The "[EE sync]"
lines (vsync, thread, ra, operation, object id, state) are compared in order;
the first mismatch is printed with context from both runs. When one run is
deterministic and passes and the other fails, this is the earliest point the
emulated schedule differs.

    python -I tools/diagnostics/sync_trace_diff.py RUN_A RUN_B [--context 12]
"""
import argparse
from pathlib import Path


def events(run):
    out = []
    with open(run / 'stderr.txt', 'rb') as f:
        for line in f:
            if line.startswith(b'[EE sync]'):
                out.append(line.decode('latin-1').rstrip())
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('a', type=Path)
    parser.add_argument('b', type=Path)
    parser.add_argument('--context', type=int, default=12)
    args = parser.parse_args()
    a, b = events(args.a), events(args.b)
    print(f'A: {len(a)} events, B: {len(b)} events')
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print(f'first divergence at event {i}')
            lo = max(0, i - args.context)
            print('--- A'); print('\n'.join(a[lo:i + args.context]))
            print('--- B'); print('\n'.join(b[lo:i + args.context]))
            return 1
    print('no divergence in the common prefix')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Track CRI SJ-remote chunks across the EE<->IOP DTX exchange (PS2X_TRACE_SIF).

The SJ-over-DTX channel exchanges 0x880-byte blocks: EE 0x30EE00 -> IOP and
back. Block = count, 3 pad words, then 4-word entries:
  EE->IOP  type 0x100 "data chunk": (type, IOP SJ id, address, size)
  IOP->EE  type 0 "chunk returned": (type|lane<<8, EE SJRMT handle, address, size)
Every chunk the EE sends must come back. This prints chunks still held by the
IOP at the end of the trace (or at --at VSYNC), with the vsync they were sent.

    python -I tools/diagnostics/sj_chunk_tracker.py RUNDIR [--at 11145]
"""
import argparse
from pathlib import Path
import re

VSYNC = re.compile(r'^\[vsync\] (\d+)')
SIF = re.compile(r'^\[SIF (EE>IOP|IOP>EE)\] src=0x([0-9a-f]+) dst=0x([0-9a-f]+) size=0x880 .*words=([0-9a-f,]*)')


def entries(words):
    if not words:
        return []
    count = words[0]
    out = []
    for i in range(count):
        e = words[4 + i * 4:8 + i * 4]
        if len(e) < 4:
            out.append(None)  # beyond the logged prefix
            break
        out.append(e)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', type=Path)
    parser.add_argument('--at', type=int, default=None, help='stop at this vsync')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    vsync = 0
    held = {}  # (iop id, address) -> (size, vsync)
    id_by_handle = {}
    truncated = 0
    with open(args.run / 'stderr.txt', errors='replace') as f:
        for line in f:
            m = VSYNC.match(line)
            if m:
                vsync = int(m[1])
                if args.at is not None and vsync > args.at:
                    break
                continue
            m = SIF.match(line)
            if not m:
                continue
            direction, src, dst = m[1], int(m[2], 16), int(m[3], 16)
            words = [int(w, 16) for w in m[4].split(',') if w]
            if direction == 'EE>IOP' and src == 0x30EE00:
                for e in entries(words):
                    if e is None:
                        truncated += 1
                        continue
                    if (e[0] & 0xFFFF) == 0x100:
                        key = (e[1], e[2])
                        if key in held and args.verbose:
                            print(f'v={vsync} resend {e[1]:#x} {e[2]:#x}+{e[3]:#x}')
                        held[key] = (e[3], vsync)
            elif direction == 'IOP>EE' and dst == 0x30EE00:
                for e in entries(words):
                    if e is None:
                        truncated += 1
                        continue
                    if (e[0] & 0xFF) != 0:
                        continue
                    handle, address, size = e[1], e[2], e[3]
                    # A return may cover several sent chunks (the IOP merges).
                    end = address + size
                    matched = [k for k, (s, _) in held.items()
                               if address <= k[1] < end and id_by_handle.get(handle, k[0]) == k[0]]
                    if matched and handle not in id_by_handle:
                        id_by_handle[handle] = matched[0][0]
                    for k in matched:
                        del held[k]
                    if not matched and args.verbose:
                        print(f'v={vsync} return without send {handle:#x} {address:#x}+{size:#x}')
    print(f'at v={vsync}: {len(held)} chunks still held by the IOP'
          + (f' ({truncated} entries beyond the logged prefix)' if truncated else ''))
    for (iop, address), (size, sent) in sorted(held.items(), key=lambda kv: kv[1][1]):
        print(f'  id={iop:#x} {address:#x}+{size:#x} sent at v={sent}')


if __name__ == '__main__':
    main()

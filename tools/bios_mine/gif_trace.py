"""Decode bounded runtime GIF traces without treating a short prefix as corruption.

This is packet evidence, not a GS emulator or a game compatibility certificate.
Usage: python tools/bios_mine/gif_trace.py stderr.txt --out decoded.json
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

LINE = re.compile(r'\[GIF packet\] index=(\d+) size=(\d+) published_pc=(0x[\da-f]+) prefix=([\da-f]*)')


def decode(data, declared_size):
    offset, tags = 0, []
    complete = len(data) == declared_size
    while offset + 16 <= len(data):
        lo = int.from_bytes(data[offset:offset + 8], 'little')
        hi = int.from_bytes(data[offset + 8:offset + 16], 'little')
        nloop, flg, nreg = lo & 0x7fff, (lo >> 58) & 3, (lo >> 60) & 15
        nreg = nreg or 16
        regs = [(hi >> (4 * i)) & 15 for i in range(nreg)]
        tag = dict(offset=offset, nloop=nloop, flg=flg, nreg=nreg,
                   eop=bool(lo & 0x8000), pre=bool((lo >> 46) & 1),
                   prim=(lo >> 47) & 0x7ff, regs=regs, writes=[])
        tags.append(tag)
        offset += 16
        payload = nloop * (nreg * (16 if flg == 0 else 8) if flg < 2 else 16)
        padded = (payload + 15) & ~15
        end = offset + padded
        if flg < 2:
            slot = 16 if flg == 0 else 8
            for i in range(min(nloop * nreg, (len(data) - offset) // slot)):
                start = offset + i * slot
                value = int.from_bytes(data[start:start + 8], 'little')
                desc = regs[i % nreg]
                entry = dict(descriptor=desc, lo=hex(value))
                if flg == 0:
                    upper = int.from_bytes(data[start + 8:start + 16], 'little')
                    entry['hi'] = hex(upper)
                    if desc == 14:
                        entry['register'] = upper & 255
                    if desc == 1:
                        entry['rgba'] = [value & 255, (value >> 32) & 255,
                                         upper & 255, (upper >> 32) & 255]
                else:
                    entry['register'] = desc
                tag['writes'].append(entry)
        tag['payload_bytes'] = payload
        tag['payload_available'] = max(0, min(payload, len(data) - offset))
        if end > len(data):
            return dict(status='short-packet' if complete else 'prefix-truncated', tags=tags)
        offset = end
    status = 'complete' if complete and offset == len(data) else (
        'trailing-bytes' if complete else 'prefix-truncated')
    return dict(status=status, tags=tags)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    raw = args.trace.read_bytes()
    packets = []
    for match in LINE.finditer(raw.decode('utf-8', errors='replace')):
        index, size, pc, prefix = match.groups()
        packet = dict(index=int(index), declared_size=int(size), sampled_pc=pc,
                      captured_bytes=len(prefix) // 2)
        packet.update(decode(bytes.fromhex(prefix), int(size)))
        packets.append(packet)
    result = dict(schema=1, trace_sha256=hashlib.sha256(raw).hexdigest(),
                  trace_capped=b'[GIF packet trace capped]' in raw,
                  compatibility='unverified', packets=packets)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(packets=len(packets), capped=result['trace_capped'],
                         statuses={status: sum(p['status'] == status for p in packets)
                                   for status in sorted({p['status'] for p in packets})})))


if __name__ == '__main__':
    main()

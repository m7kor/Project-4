"""Read-only PS2 card integrity audit; never repairs or certifies game save/load.

Adapted from thiagordsfx/urban-reign-recomp tools/mc_check.py at
d2d30d781ec1b1acd9d44b93fa6f67a81e03453b (GPL-3.0).
Corrected flags offset/allocation range against PCSX2 MemoryCardFolder.h.
SPDX-License-Identifier: GPL-3.0-only
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

PARITY = tuple(i.bit_count() & 1 for i in range(256))
MASKS = (0x55, 0x33, 0x0F, 0, 0xAA, 0xCC, 0xF0)
COL = tuple(sum(PARITY[i & mask] << j for j, mask in enumerate(MASKS)) for i in range(256))


def ecc_calc(chunk):
    column = lp0 = lp1 = 0
    for i, byte in enumerate(chunk):
        column ^= COL[byte]
        if PARITY[byte]:
            lp0 ^= ~i & 0x7F
            lp1 ^= i
    return bytes((~column & 0x77, ~lp0 & 0x7F, ~lp1 & 0x7F))


class Card:
    def __init__(self, data):
        self.data = data
        self.stride = 528 if len(data) in {m * 1024 * 1024 // 512 * 528 for m in (8, 16, 32, 64)} else 512
        if len(data) not in {m * 1024 * 1024 // 512 * self.stride for m in (8, 16, 32, 64)}:
            raise ValueError('unsupported or truncated card size')
        sb = self.page(0)
        if not sb.startswith(b'Sony PS2 Memory Card Format '):
            raise ValueError('missing PS2 superblock')
        self.page_len, self.ppc, self.ppb = struct.unpack_from('<HHH', sb, 0x28)
        self.clusters, self.alloc_off, self.alloc_end, self.root = struct.unpack_from('<IIII', sb, 0x30)
        self.ifc = struct.unpack_from('<32I', sb, 0x50)
        self.card_type, self.flags = sb[0x150:0x152]
        if self.page_len != 512 or self.ppc != 2 or self.clusters != len(data) // (self.stride * self.ppc):
            raise ValueError('unsupported or inconsistent page/cluster geometry')
        if not 0 < self.alloc_off < self.clusters or not 0 < self.alloc_end <= self.clusters - self.alloc_off:
            raise ValueError('allocation area outside image')
        if self.root >= self.alloc_end:
            raise ValueError('root outside allocation area')
        self.size = self.page_len * self.ppc

    def page(self, index):
        if not 0 <= index < len(self.data) // self.stride:
            raise ValueError(f'page {index} outside image')
        return self.data[index * self.stride:index * self.stride + 512]

    def cluster(self, index):
        if not 0 <= index < self.clusters:
            raise ValueError(f'cluster {index} outside image')
        return b''.join(self.page(index * self.ppc + i) for i in range(self.ppc))

    def fat_entry(self, index):
        if not 0 <= index < self.alloc_end:
            raise ValueError(f'FAT index {index} outside allocation area')
        per = self.size // 4
        indirect = self.ifc[index // (per * per)]
        fat = struct.unpack_from('<I', self.cluster(indirect), 4 * ((index // per) % per))[0]
        return struct.unpack_from('<I', self.cluster(fat), 4 * (index % per))[0]

    def chain(self, start):
        chain, seen = [], set()
        while True:
            if start in seen:
                raise ValueError(f'FAT loop at {start}')
            seen.add(start)
            entry = self.fat_entry(start)
            if not entry & 0x80000000:
                raise ValueError(f'free cluster {start} in chain')
            chain.append(start)
            if entry == 0xFFFFFFFF:
                return chain
            start = entry & 0x7FFFFFFF


def audit(data):
    result = {'schema': 1, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
              'scope': 'read-only ECC/FAT/directory audit; game progress save/load unverified',
              'problems': [], 'files': [], 'ecc_bad_pages': [], 'unreferenced_allocated_clusters': []}
    problems = result['problems']
    try:
        card = Card(data)
        result['geometry'] = {k: getattr(card, k) for k in ('stride', 'ppc', 'clusters', 'alloc_off', 'alloc_end', 'root', 'flags')}
        if card.stride == 528 and card.flags & 1:
            result['ecc'] = 'checked'
            for page in range(len(data) // card.stride):
                content = card.page(page)
                if content == b'\xff' * 512:
                    continue
                want = b''.join(ecc_calc(content[i:i + 128]) for i in range(0, 512, 128))
                if data[page * 528 + 512:page * 528 + 524] != want:
                    result['ecc_bad_pages'].append(page)
        else:
            result['ecc'] = 'not-present-or-disabled'
        root = card.cluster(card.alloc_off + card.root)
        pending = [('/', card.root, struct.unpack_from('<I', root, 4)[0])]
        visited, owners = set(), {}
        def read_chain(path, start, size):
            chain = card.chain(start)
            for c in chain:
                if c in owners:
                    problems.append(f'cluster {c} shared by {owners[c]} and {path}')
                owners[c] = path
            if size > len(chain) * card.size:
                raise ValueError(f'{path}: size exceeds chain')
            return b''.join(card.cluster(card.alloc_off + c) for c in chain)[:size]
        while pending:
            path, start, count = pending.pop()
            if start in visited:
                problems.append(f'{path}: directory cycle/shared directory')
                continue
            visited.add(start)
            try:
                if count > card.alloc_end * 2:
                    raise ValueError('directory count outside card capacity')
                entries = read_chain(path, start, count * 512)
                for offset in range(0, len(entries), 512):
                    entry = entries[offset:offset + 512]
                    mode, _, length, first = struct.unpack_from('<HHI8xI', entry)
                    name = entry[0x40:0x60].split(b'\0')[0].decode('ascii', 'replace')
                    if not mode & 0x8000 or name in ('.', '..'):
                        continue
                    full = path.rstrip('/') + '/' + name
                    if mode & 0x20:
                        pending.append((full, first, length))
                    else:
                        try:
                            content = read_chain(full, first, length) if length else b''
                            result['files'].append({'path': full, 'bytes': length, 'sha256': hashlib.sha256(content).hexdigest()})
                        except ValueError as error:
                            problems.append(str(error))
            except ValueError as error:
                problems.append(f'{path}: {error}')
        leaked = [c for c in range(card.alloc_end) if card.fat_entry(c) & 0x80000000 and c not in owners]
        result['unreferenced_allocated_clusters'] = leaked
    except (ValueError, struct.error, IndexError) as error:
        problems.append(str(error))
    result['passed'] = not (problems or result['ecc_bad_pages'] or result['unreferenced_allocated_clusters'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('card', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.out and args.out.resolve() == args.card.resolve():
        parser.error('report cannot replace card')
    result = audit(args.card.read_bytes())
    result['path'] = str(args.card.resolve())
    result['source_unchanged'] = hashlib.sha256(args.card.read_bytes()).hexdigest() == result['sha256']
    result['passed'] = result['passed'] and result['source_unchanged']
    text = json.dumps(result, indent=2)
    if args.out:
        with args.out.open('x', encoding='utf-8') as out:
            out.write(text + '\n')
    print(text)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

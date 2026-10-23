"""Verify corruption detection on in-memory copies; never writes a card."""
import argparse
import importlib.util
import json
import random
import struct
from pathlib import Path
from integrity_check import Card, audit, ecc_calc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('card', type=Path)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    original = args.card.read_bytes()
    card = Card(original)
    spec = importlib.util.spec_from_file_location('urban_mc_reference', args.reference)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    rng = random.Random(6130)
    blocks = [bytes(128), b'\xff' * 128] + [rng.randbytes(128) for _ in range(20)]
    assert all(ecc_calc(block) == reference.ecc_calc(block) for block in blocks)

    def patch(offset, value):
        data = bytearray(original)
        data[offset:offset + len(value)] = value
        # Recompute affected ECC so structural checks must detect this corruption.
        for page in range(offset // 528, (offset + len(value) - 1) // 528 + 1):
            raw = data[page * 528:page * 528 + 512]
            data[page * 528 + 512:page * 528 + 524] = b''.join(ecc_calc(raw[i:i + 128]) for i in range(0, 512, 128))
        return bytes(data)

    def fat_offset(index):
        per = card.size // 4
        indirect = card.ifc[index // (per * per)]
        fat = struct.unpack_from('<I', card.cluster(indirect), 4 * ((index // per) % per))[0]
        byte = (index % per) * 4
        return (fat * card.ppc + byte // 512) * 528 + byte % 512

    bad_ecc = bytearray(original)
    bad_ecc[512] ^= 1
    cases = {
        'valid': original,
        'truncated': original[:-1],
        'wrong_geometry': patch(0x28, struct.pack('<H', 1024)),
        'ecc_corruption': bytes(bad_ecc),
        'root_chain_loop': patch(fat_offset(card.root), struct.pack('<I', 0x80000000 | card.root)),
        'root_chain_out_of_bounds': patch(fat_offset(card.root), struct.pack('<I', 0x80000000 | card.alloc_end)),
        'root_chain_free': patch(fat_offset(card.root), bytes(4)),
        'tail_allocation_leak': patch(fat_offset(card.alloc_end - 1), struct.pack('<I', 0xFFFFFFFF)),
        'directory_size_exceeds_chain': patch((card.alloc_off + card.root) * card.ppc * 528 + 4, struct.pack('<I', card.alloc_end * 3)),
    }
    results = {}
    for name, data in cases.items():
        result = audit(data)
        assert result['passed'] == (name == 'valid'), (name, result)
        if name == 'tail_allocation_leak':
            assert card.alloc_end - 1 in result['unreferenced_allocated_clusters']
        results[name] = {'accepted': result['passed'], 'problems': result['problems'],
                         'bad_ecc_pages': len(result['ecc_bad_pages']),
                         'leaks': len(result['unreferenced_allocated_clusters'])}
    assert args.card.read_bytes() == original
    report = {'passed': True, 'scope': 'nine read-only valid/corruption cases; game save/load unverified',
              'ecc_reference_blocks': len(blocks), 'source_card_unchanged': True, 'cases': results}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

"""Read a verified packed counter from existing RAM dumps; never write guest state.

The decoding contract belongs to one ELF and item type. It must come from
independent analysis, not a search for a desired before/after byte pattern.
This module does not treat a backing counter as proof of HUD correctness.
"""
from pathlib import Path
import hashlib
import json
import struct

ROOT = Path(__file__).resolve().parents[1]


def packed_counter(memory, pointer_address, expected_item_id, field_offset=8, shift=3):
    if not 0 <= shift <= 15 or field_offset < 2 or field_offset % 2:
        raise ValueError('Invalid packed-counter contract')
    if pointer_address < 0 or pointer_address + 4 > len(memory):
        raise ValueError('Pointer slot outside captured memory')
    pointer = struct.unpack_from('<I', memory, pointer_address)[0]
    if not pointer or pointer % 2 or pointer + field_offset + 2 > len(memory):
        raise ValueError('Item pointer outside captured memory or misaligned')
    item_id = struct.unpack_from('<H', memory, pointer)[0]
    if item_id != expected_item_id:
        raise ValueError('Unsupported item identity; do not guess its layout')
    packed = struct.unpack_from('<H', memory, pointer + field_offset)[0]
    return {'item_address': pointer, 'item_id': item_id,
            'counter': packed >> shift, 'low_bits': packed & ((1 << shift) - 1)}


def main():
    # This address contract was recovered through the ELF export table and
    # existing isolated Ghidra project; the game-derived pseudocode stays private.
    elf_hash = '465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'
    analysis = ROOT / 'artifacts/architecture/ghidra-ammo-04/query-07.json'
    exports = json.loads((ROOT / 'artifacts/architecture/ammo-exports-01.json').read_text())
    assert any(r['name'] == 'bulletNum__8cItemMgrP5cItem' and r['address'] == 0x1205d8 for r in exports)
    decompile = json.loads(analysis.read_text())['response']
    assert not decompile.get('isError') and decompile['structuredContent']['function']['address'] == '001205d8'
    out = ROOT / 'artifacts/architecture/ammo-counter-01'
    out.mkdir(exist_ok=False)
    rows = []
    for mode in ('0', '1'):
        folder = ROOT / f'artifacts/runs/phase5-perf-6-{mode}/phase5-ammo'
        identity = json.loads((folder / 'discovery.json').read_text())
        capture = json.loads((folder / 'report.json').read_text())
        assert identity['elf_sha256'] == elf_hash and capture['completed']
        for sample in capture['snapshots']:
            path = folder / (sample['label'] + '.bin')
            memory = path.read_bytes()
            digest = hashlib.sha256(memory).hexdigest()
            assert len(memory) == 32 * 1024 * 1024 and digest == sample['sha256']
            result = packed_counter(memory, 0x3ce154, 0x23)
            rows.append({'mode': mode, 'label': sample['label'], 'sha256': digest,
                         'ee_before': sample['before']['ee'], 'ee_after': sample['after']['ee'],
                         'runner_sha256': capture['runner_sha256'], **result})
    expected = [5, 4, 3, 3]
    for mode in ('0', '1'):
        assert [r['counter'] for r in rows if r['mode'] == mode] == expected
    report = {'passed': True, 'elf_sha256': elf_hash, 'rows': rows,
              'analysis_sha256': hashlib.sha256(analysis.read_bytes()).hexdigest(),
              'contract': {'pointer_slot': '0x3ce154', 'supported_item_id': '0x23',
                           'field_offset': 8, 'shift': 3},
              'scope': 'Historical non-atomic read-only snapshots; backing weapon counter, not HUD pixels, host audio or fresh gameplay',
              'conclusion': 'Both reference and Phase5 candidate contain 5,4,3,3; no backing-counter rebound in these snapshots'}
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    print('Verified eight historical RAM captures: both backing counters 5,4,3,3; HUD remains separate')


if __name__ == '__main__':
    main()

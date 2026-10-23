"""Inventory uncompressed MIPS ELF signatures and SNR2 modules in game files.

Scans every byte of supplied files for ELF headers, including embedded IRX.
Does not unpack compressed/encrypted payloads or certify Ghidra coverage.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

from snr2_inventory import read_modules


def elf_at(stream, offset, total):
    def get(relative, size):
        if relative < 0 or size < 0 or offset + relative + size > total:
            raise ValueError('ELF span exceeds containing file')
        stream.seek(offset + relative)
        result = stream.read(size)
        if len(result) != size:
            raise ValueError('Short ELF span')
        return result
    header = get(0, 52)
    if header[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('Not ELF32 little-endian version 1')
    kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, strings = struct.unpack_from('<HHIIIIIHHHHHH', header, 16)
    if machine != 8 or version != 1 or ehsize != 52 or phnum > 4096 or shnum > 4096:
        raise ValueError('Not a supported bounded MIPS ELF32 header')
    extent = 52
    if phnum:
        if phsize != 32:
            raise ValueError('Unexpected ELF32 program header size')
        table = get(phoff, phsize * phnum)
        extent = max(extent, phoff + len(table))
        for i in range(phnum):
            values = struct.unpack_from('<8I', table, i * 32)
            extent = max(extent, values[1] + values[4])
    if shnum:
        if shsize != 40:
            raise ValueError('Unexpected ELF32 section header size')
        table = get(shoff, shsize * shnum)
        extent = max(extent, shoff + len(table))
        for i in range(shnum):
            values = struct.unpack_from('<10I', table, i * 40)
            if values[1] != 8:  # SHT_NOBITS has no file payload.
                extent = max(extent, values[4] + values[5])
    if not phnum and not shnum or extent > 32 * 1024 * 1024:
        raise ValueError('Empty or oversized ELF extent')
    data = get(0, extent)
    return {'offset': offset, 'minimum_extent_bytes': extent, 'sha256': hashlib.sha256(data).hexdigest(),
            'type': kind, 'machine': machine, 'flags': f'0x{flags:08x}', 'entry': f'0x{entry:08x}',
            'program_headers': phnum, 'section_headers': shnum,
            'scope': 'ELF table-derived extent; trailing container padding is excluded'}


def scan(path):
    total = path.stat().st_size
    result = {'file': str(path.resolve()), 'bytes': total, 'elf': [], 'rejected_signatures': [], 'snr2': []}
    digest = hashlib.sha256()
    consumed, overlap = 0, b''
    with path.open('rb') as source, path.open('rb') as probe:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
            data, base = overlap + chunk, consumed - len(overlap)
            at = 0
            while (at := data.find(b'\x7fELF', at)) >= 0:
                absolute = base + at
                try:
                    result['elf'].append(elf_at(probe, absolute, total))
                except ValueError as error:
                    result['rejected_signatures'].append({'offset': absolute, 'reason': str(error)})
                at += 4
            consumed += len(chunk)
            overlap = data[-3:]
    result['sha256'] = digest.hexdigest()
    with path.open('rb') as stream:
        afs = stream.read(4) == b'AFS\0'
    if afs:
        with path.open('rb') as stream:
            result['afs_entries'] = struct.unpack('<I', stream.read(8)[4:])[0]
        for module, payload in read_modules(path):
            result['snr2'].append({key: module[key] for key in ('afs_index', 'archive_offset', 'bytes', 'sha256', 'original_image_name', 'constructor_offset', 'destructor_offset')})
    if path.stat().st_size != total:
        raise ValueError('Source size changed during inventory')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+')
    parser.add_argument('--ghidra-info', type=Path, required=True, help='Current get_program_info JSON')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Preserve previous inventories')
    missing = [str(path) for path in args.files if not path.is_file()]
    if missing:
        parser.error('Missing input files: ' + ', '.join(missing))
    rows = [scan(path) for path in args.files]
    info = json.loads(args.ghidra_info.read_text(encoding='utf-8'))
    elves = [dict(file=row['file'], **entry) for row in rows for entry in row['elf']]
    modules = [dict(file=row['file'], **entry) for row in rows for entry in row['snr2']]
    hashes = Counter(entry['sha256'] for entry in elves)
    active_sha = info['sha256']
    result = {'scope': __doc__.strip(), 'files': rows,
              'elf_occurrences': len(elves), 'unique_elf_images': len(hashes),
              'snr2_occurrences': len(modules), 'unique_snr2_images': len(set(entry['sha256'] for entry in modules)),
              'active_ghidra_program': {'name': info['name'], 'sha256': active_sha, 'language_id': info['language_id']},
              'active_program_matches': [entry for entry in elves if entry['sha256'] == active_sha],
              'elf_not_matching_active_program': [entry for entry in elves if entry['sha256'] != active_sha],
              'all_game_binaries_imported_and_analyzed': 'unproven',
              'limits': ['Only supplied files were scanned; ISO files not supplied are excluded.',
                         'Compressed/encrypted ELF payloads are not unpacked by magic scanning.',
                         'SNR2 modules retain original .elf names but are a different on-disc format.',
                         'get_program_info identifies the active program, not all programs stored in a Ghidra project.',
                         'Inventory and extraction do not prove correct decompilation or runtime support.']}
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('elf_occurrences', 'unique_elf_images', 'snr2_occurrences', 'unique_snr2_images', 'active_ghidra_program', 'all_game_binaries_imported_and_analyzed')}, indent=2))


if __name__ == '__main__':
    main()

"""Extract inventoried ELF/SNR2 images without conversion or source changes.

Requires a fresh output directory, checks inventory identities, deduplicates by
full SHA-256, and verifies written bytes. This does not import into Ghidra.
"""
import argparse
import hashlib
import json
from pathlib import Path

from game_binary_inventory import elf_at
from snr2_inventory import parse_snr2


def extract(inventory, destination):
    rows = json.loads(inventory.read_text(encoding='utf-8'))
    if destination.exists():
        raise ValueError('Output directory must be new; existing evidence is preserved')
    for row in rows['files']:
        source = Path(row['file'])
        if not source.is_file() or source.stat().st_size != row['bytes']:
            raise ValueError(f'Source missing or resized: {source}')
    destination.mkdir(parents=True)
    images, occurrences = {}, []
    for row in rows['files']:
        source = Path(row['file'])
        with source.open('rb') as stream:
            for kind, entries in (('elf', row['elf']), ('snr2', row['snr2'])):
                for entry in entries:
                    offset = entry['offset'] if kind == 'elf' else entry['archive_offset']
                    size = entry['minimum_extent_bytes'] if kind == 'elf' else entry['bytes']
                    if offset < 0 or size <= 0 or offset + size > row['bytes']:
                        raise ValueError('Inventory span exceeds source')
                    stream.seek(offset)
                    data = stream.read(size)
                    digest = hashlib.sha256(data).hexdigest()
                    if len(data) != size or digest != entry['sha256']:
                        raise ValueError(f'Inventoried image changed: {source} at {offset}')
                    metadata = elf_at(stream, offset, row['bytes']) if kind == 'elf' else parse_snr2(data)
                    if metadata['sha256'] != digest:
                        raise ValueError('Parser identity differs from inventory')
                    target = destination / kind / (digest + ('.elf' if kind == 'elf' else '.snr2'))
                    key = (kind, digest)
                    if key not in images:
                        target.parent.mkdir(exist_ok=True)
                        with target.open('xb') as output:
                            output.write(data)
                        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                            raise ValueError('Extracted image verification failed')
                        images[key] = {'format': kind, 'sha256': digest, 'bytes': size,
                                       'path': str(target.resolve()), 'metadata': metadata,
                                       'ghidra_import': 'not performed by extractor'}
                    occurrences.append({'format': kind, 'sha256': digest, 'source': str(source),
                                        'offset': offset, 'afs_index': entry.get('afs_index'),
                                        'original_image_name': entry.get('original_image_name')})
    for kind, expected in (('elf', rows['unique_elf_images']), ('snr2', rows['unique_snr2_images'])):
        if sum(k[0] == kind for k in images) != expected:
            raise ValueError(f'{kind} unique count differs from inventory')
    result = {'inventory': str(inventory.resolve()),
              'inventory_sha256': hashlib.sha256(inventory.read_bytes()).hexdigest(),
              'images': list(images.values()), 'occurrences': occurrences,
              'verified_unique_images': len(images),
              'limits': ['Only inventoried spans are extracted; compressed payloads remain excluded.',
                         'SNR2 bytes retain original format, symbols and relocations; no ELF conversion.',
                         'Image spans are verified; containing-file bytes outside these spans are not rehashed.',
                         'Extraction does not prove Ghidra analysis or runtime coverage.']}
    (destination / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.inventory, args.out_dir)
    print(json.dumps({'verified_unique_images': result['verified_unique_images'],
                      'occurrences': len(result['occurrences']),
                      'manifest': str((args.out_dir / 'manifest.json').resolve())}))


if __name__ == '__main__':
    main()

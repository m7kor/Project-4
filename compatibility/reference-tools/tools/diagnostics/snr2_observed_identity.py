"""Match a bounded original-loader observation to SNR2 images; never execute them."""
import argparse
import json
from pathlib import Path
import re
import struct

from tools.diagnostics.snr2_inventory import parse_snr2, read_modules

LINE = re.compile(r'^\[native-module:untranslated\] name=(.+) base=0x([0-9a-fA-F]+) '
                  r'target=0x([0-9a-fA-F]+) size=0x([0-9a-fA-F]+) header=([0-9a-fA-F,]+)$')
POINTER_FIELDS = {1, 3, 5, 6, 7, 8, 13, 14}


def parse_observation(line, ram_size=32 * 1024 * 1024):
    match = LINE.fullmatch(line.strip())
    if not match:
        raise ValueError('Malformed SNR2 loader observation')
    name, base, target, size, header = match.groups()
    base, target, size = (int(x, 16) for x in (base, target, size))
    words = [int(x, 16) for x in header.split(',')]
    if (name == '<unreadable>' or len(name) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in name)
            or len(words) != 15 or any(w > 0xffffffff for w in words)
            or base & 3 or size < 60 or base + size > min(ram_size, 0x100000000)
            or words[0] != 0x32524e53 or words[11] != size
            or not base + 60 <= target < base + size or target & 3
            or words[6] != target):
        raise ValueError('Unusable SNR2 header/name/range/constructor observation')
    return dict(name=name, base=base, target=target, bytes=size, header=words)


def match_image(data, observed):
    metadata = parse_snr2(data)
    if (metadata['original_image_name'] != observed['name'] or len(data) != observed['bytes']
            or observed['base'] + metadata['constructor_offset'] != observed['target']):
        return None
    original = struct.unpack_from('<15I', data)
    fields = []
    for index, value in enumerate(original):
        expected = observed['base'] + value if index in POINTER_FIELDS and value else value
        fields.append(dict(offset=index*4, original=value, expected=expected,
                           observed=observed['header'][index], checked=index != 12,
                           matches=None if index == 12 else expected == observed['header'][index]))
    if not all(f['matches'] for f in fields if f['checked']):
        return None
    return dict(source_image_sha256=metadata['sha256'], image_name=metadata['original_image_name'],
                constructor_offset=metadata['constructor_offset'], fields=fields,
                header_and_name_match=True, runtime_full_image_hash_verified=False)


def unique_image(matches):
    identities = {item['source_image_sha256'] for item in matches}
    if len(identities) != 1:
        raise ValueError('Original image absent or ambiguous; extraction refused')
    return next(iter(identities))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--stdout', type=Path, required=True)
    parser.add_argument('--target', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--extract-to', type=Path)
    args = parser.parse_args()
    sources = {args.archive.resolve(), args.stdout.resolve()}
    outputs = [args.out.resolve()] + ([args.extract_to.resolve()] if args.extract_to else [])
    if len(set(outputs)) != len(outputs) or any(path in sources for path in outputs):
        parser.error('Outputs must differ from each other and the input files')
    observations = []
    with args.stdout.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            if line.startswith('[native-module:untranslated]'):
                observed = parse_observation(line)
                if observed['target'] == args.target and observed not in observations:
                    observations.append(observed)
    if len(observations) != 1:
        raise ValueError('Need exactly one distinct original-loader observation for this target')
    observed = observations[0]
    matches, images = [], {}
    for metadata, data in read_modules(args.archive):
        match = match_image(data, observed)
        if match:
            match.update(afs_index=metadata['afs_index'], archive_offset=metadata['archive_offset'])
            matches.append(match)
            images[match['source_image_sha256']] = data
    identity = unique_image(matches)
    if args.extract_to:
        data = images[identity]
        if args.extract_to.exists() and args.extract_to.read_bytes() != data:
            raise ValueError('Different existing extraction preserved')
        args.extract_to.parent.mkdir(parents=True, exist_ok=True)
        if not args.extract_to.exists():
            args.extract_to.write_bytes(data)
    report = dict(schema=1, observation=observed, matches=matches,
                  unique_source_image_sha256=identity,
                  runtime_full_image_hash_verified=False, execution_verified=False,
                  scope='Original loader name and relocated immutable header only; '
                        'field +0x30 is mutable. Duplicate byte-identical AFS images collapse. '
                        'Compiled code validation and execution remain required.')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Matched {observed['name']} at {observed['base']:#x}; {len(matches)} identical source entries")


if __name__ == '__main__':
    main()

"""Read a stored PS2 decompilation reference after checking its local evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = ROOT / 'research/decomp-wtf-evaluation/analysis-reference.json'
DEFAULT_ELF = ROOT / 'game/Resident Evil 4 (USA)/SLUS_211.34'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def address(value: str) -> int:
    raw = re.sub(r'^(?:func_|fun_|sub_|0x)', '', value, flags=re.IGNORECASE)
    if not re.fullmatch(r'[0-9a-fA-F]{1,8}', raw):
        raise ValueError('Use a 32-bit hexadecimal address or a func_/FUN_/sub_ name')
    return int(raw, 16)


def target_bytes(program: bytes, start: int, size: int) -> bytes:
    if len(program) < 52 or program[:6] != b'\x7fELF\x01\x01':
        raise ValueError('Expected a 32-bit little-endian ELF')
    if struct.unpack_from('<H', program, 18)[0] != 8:
        raise ValueError('Expected a MIPS ELF')
    phoff = struct.unpack_from('<I', program, 28)[0]
    phsize, count = struct.unpack_from('<HH', program, 42)
    if phsize < 32 or phoff + phsize * count > len(program):
        raise ValueError('Invalid ELF program headers')
    for k in range(count):
        kind, offset, vaddr, _, filesz = struct.unpack_from('<IIIII', program, phoff + k * phsize)
        if kind == 1 and vaddr <= start and start + size <= vaddr + filesz:
            at = offset + start - vaddr
            if at + size > len(program):
                raise ValueError('ELF segment extends beyond the file')
            return program[at:at + size]
    raise ValueError('Function bytes are not in a file-backed ELF segment')


def artifact(root: Path, raw: str) -> Path:
    path = Path(raw)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Reference artifact is outside the index directory')
    return path


def lookup(index_path: Path, elf_path: Path, query: int | None = None) -> dict:
    index_path = index_path.resolve()
    root = index_path.parent
    index = json.loads(index_path.read_text(encoding='utf-8'))
    program = elf_path.read_bytes()
    if hashlib.sha256(program).hexdigest() != index['elf_sha256']:
        raise ValueError('ELF identity differs from the recorded reference')
    entries = sorted(index['entries'], key=lambda e: address(e['address']))
    end = -1
    for entry in entries:
        start, size = address(entry['address']), entry['size']
        if not isinstance(size, int) or size <= 0 or size % 4 or start % 4 or start < end:
            raise ValueError('Invalid, duplicate or overlapping function ranges')
        end = start + size
    chosen = [e for e in entries if query is None or address(e['address']) <= query < address(e['address']) + e['size']]
    if not chosen:
        return {'status': 'not_found', 'address': f'0x{query:08X}',
                'message': 'No recorded match covers this address'}
    results = []
    for entry in chosen:
        if entry.get('exact_reverified') is not True or entry.get('mutated_target_rejected') is not True:
            raise ValueError('Reference lacks a recorded exact match and negative control')
        evidence_path = artifact(root, entry['evidence'])
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        recorded = [e for e in evidence['entries'] if e['name'] == entry['name']]
        if evidence['elf_sha256'] != index['elf_sha256'] or len(recorded) != 1:
            raise ValueError('Reference is not backed by its evidence manifest')
        proof = recorded[0]
        for key in ('address', 'size', 'source_sha256', 'object_sha256', 'target_sha256',
                    'flags', 'exact_reverified', 'mutated_target_rejected', 'origin',
                    'candidate_repairs', 'context_sha256'):
            if proof.get(key) != entry.get(key):
                raise ValueError('Index and evidence manifest disagree: ' + key)
        item = dict(entry)
        for kind in ('source', 'object'):
            path = artifact(root, entry[kind])
            if sha256(path) != entry[kind + '_sha256']:
                raise ValueError(kind.capitalize() + ' has changed since verification')
            item[kind] = str(path)
        if entry.get('context'):
            context = artifact(root, entry['context'])
            if sha256(context) != entry['context_sha256']:
                raise ValueError('Context has changed since verification')
            item['context'] = str(context)
        code = target_bytes(program, address(entry['address']), entry['size'])
        if hashlib.sha256(code).hexdigest() != entry['target_sha256']:
            raise ValueError('Target bytes differ from the original ELF')
        item['offset'] = 0 if query is None else query - address(entry['address'])
        results.append(item)
    return {'status': 'verified_artifacts', 'elf_sha256': index['elf_sha256'], 'entries': results,
            'scope': 'Stored PS2 matching evidence and current file hashes; no compiler or runtime execution'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('address', nargs='?', help='Hex address, including an address inside a matched function')
    parser.add_argument('--index', type=Path, default=DEFAULT_INDEX)
    parser.add_argument('--elf', type=Path, default=DEFAULT_ELF)
    parser.add_argument('--json', action='store_true', help='Print structured evidence')
    parser.add_argument('--source', action='store_true', help='Print the verified C source for one address')
    args = parser.parse_args(argv)
    try:
        if args.source and not args.address:
            raise ValueError('--source requires an address')
        result = lookup(args.index, args.elf, address(args.address) if args.address else None)
        if args.json:
            print(json.dumps(result, indent=2))
        elif result['status'] == 'not_found':
            print(result['message'])
        else:
            for item in result['entries']:
                print(f"{item['name']} +0x{item['offset']:X} | {item['size']} bytes | stored PS2 match; hashes verified")
                print('  Source: ' + item['source'])
                print('  Evidence: ' + item['evidence'])
                if item.get('origin') == 'assisted':
                    print('  Assisted: explicit context and recorded candidate repairs')
                if args.source:
                    print(Path(item['source']).read_text(encoding='utf-8'))
        return 1 if result['status'] == 'not_found' else 0
    except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
        error = {'status': 'error', 'error': str(exc)}
        print(json.dumps(error) if args.json else 'Reference check failed: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

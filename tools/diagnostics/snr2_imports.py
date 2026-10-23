"""Resolve selected SNR2 imports against named original EE ELF export records."""
import hashlib
import struct
from tools.diagnostics.snr2_inventory import parse_snr2, span
from tools.diagnostics.snr2_relocations import patch_word, relocate_local_code


def resolve_imports(module, elf, selected_names):
    metadata = parse_snr2(module)
    span(elf, 0, 52)
    if elf[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H', elf, 18)[0] != 8:
        raise ValueError('Expected original 32-bit little-endian MIPS ELF')
    phoff = struct.unpack_from('<I', elf, 28)[0]
    ents, count = struct.unpack_from('<HH', elf, 42)
    if ents < 32:
        raise ValueError('Invalid ELF program header size')
    span(elf, phoff, ents * count)
    segments = []
    for i in range(count):
        kind, file_at, address, _, file_size, mem_size, flags, _ = struct.unpack_from('<8I', elf, phoff + ents*i)
        if kind != 1:
            continue
        span(elf, file_at, file_size)
        if file_size > mem_size or address + mem_size > 0x100000000:
            raise ValueError('Invalid ELF load segment')
        segments.append((file_at, address, file_size, mem_size, flags))

    def virtual(offset):
        matches = [address + offset - file_at for file_at, address, file_size, _, _ in segments if file_at <= offset < file_at + file_size]
        if len(matches) != 1:
            raise ValueError('Export record/string has ambiguous or absent ELF mapping')
        return matches[0]

    imports = []
    for name in sorted(set(selected_names)):
        symbols = [s for s in metadata['symbols'] if s['name'] == name and s['raw_type'] == 1]
        if len(symbols) != 1:
            raise ValueError('Selected import is absent or ambiguous in SNR2')
        symbol = symbols[0]
        pattern = name.encode('ascii') + b'\0'
        candidates = []
        at = 0
        while True:
            at = elf.find(pattern, at)
            if at < 0:
                break
            if at and elf[at-1] != 0:
                at += 1
                continue
            name_address = virtual(at)
            if virtual(at + len(pattern) - 1) != name_address + len(pattern) - 1:
                raise ValueError('Export string crosses its ELF mapping')
            pointer = struct.pack('<I', name_address)
            pos = 0
            while True:
                pos = elf.find(pointer, pos)
                if pos < 0:
                    break
                if pos % 4 == 0 and pos + 12 <= len(elf):
                    _, value, hash16, kind, reserved = struct.unpack_from('<IIHBB', elf, pos)
                    if hash16 == symbol['raw_auxiliary'] and kind in (2, 3) and not reserved:
                        record_address = virtual(pos)
                        if virtual(pos + 11) != record_address + 11:
                            raise ValueError('Export record crosses its ELF mapping')
                        if any(address <= value < address + mem_size for _, address, _, mem_size, _ in segments):
                            candidates.append({'symbol_index': symbol['index'], 'name': name, 'address': value,
                                               'hash16': hash16, 'export_record': record_address})
                pos += 1
            at += 1
        if len(candidates) != 1:
            raise ValueError('Original named export is absent or ambiguous')
        imports.append(candidates[0])
    return {'module_sha256': metadata['sha256'], 'elf_sha256': hashlib.sha256(elf).hexdigest(), 'imports': imports,
            'scope': 'Selected named export records only; does not resolve all imports or certify module readiness.'}


def relocate_selected_imports(module, base, resolution):
    metadata = parse_snr2(module)
    if resolution['module_sha256'] != metadata['sha256']:
        raise ValueError('Import resolution belongs to another original module')
    values = {item['symbol_index']: item['address'] for item in resolution['imports']}
    if len(values) != len(resolution['imports']):
        raise ValueError('Duplicate resolved symbol')
    result = bytearray(relocate_local_code(module, base))
    for relocation in metadata['relocations']:
        if relocation['symbol_index'] not in values:
            continue
        offset, kind = relocation['offset'], relocation['type']
        if offset % 4:
            raise ValueError('Unaligned imported relocation')
        word = struct.unpack_from('<I', result, offset)[0]
        struct.pack_into('<I', result, offset, patch_word(word, kind, values[relocation['symbol_index']] + relocation['addend']))
    return bytes(result)

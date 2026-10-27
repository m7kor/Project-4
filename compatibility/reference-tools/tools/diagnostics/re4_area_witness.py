"""Pinned original PS2 area lookup and bounded, read-only observation.

Flags and hit bitmap are separate observations. No collision geometry or
event-readiness inference is made here; pointer checks are not atomicity.
"""
import hashlib
import struct

from tools.diagnostics.re4_encounter_witness import ELF_SHA, RAM_SIZE
from tools.diagnostics.re4_name_table import segments


def derive_area_witness(elf):
    if hashlib.sha256(elf).hexdigest() != ELF_SHA:
        raise ValueError('Area derivation requires the pinned original PS2 ELF')
    def words(address, count):
        segment = next(s for s in segments(elf) if s[0] == 1
                       and s[2] <= address and address + count * 4 <= s[2] + s[4])
        return list(struct.unpack_from(f'<{count}I', elf, segment[1] + address - segment[2]))
    # Original head + iterator, including branch-likely delay slots.
    iterator = [0x3c030045, 0x8c6263f0, 0x03e00008, 0x2442008c,
                0x3c02ffff, 0x8c840000, 0x3442ffff, 0x1082000c,
                0x3c020045, 0x3c05ffff, 0x8c4363f0, 0x34a5ffff,
                0x2463008c, 0x0064102b, 0x50400003, 0x8c840000,
                0x03e00008, 0x0080102d, 0x1485fffb, 0x0064102b,
                0x03e00008, 0x0000102d]
    if words(0x2661b0, 22) != iterator:
        raise ValueError('Original area iterator changed')
    checks = {0x26a75c: 0x0c09986c, 0x26a778: 0x0c099870,
              0x26a784: 0x5480fffa, 0x26a788: 0x90820036,
              0x26a9d4: 0x0c09a9d4, 0x26a9ec: 0x90820034,
              0x26a9f4: 0x34420001, 0x26a9f8: 0x304200fe,
              0x26a9fc: 0xa0820034}
    if any(words(at, 1)[0] != value for at, value in checks.items()):
        raise ValueError('Original area lookup or enable field changed')
    hit = [0x3c030045, 0x00041142, 0x8c6563f0, 0x00021080,
           0x3084001f, 0x3c038000, 0x00a22821, 0x00831806,
           0x8ca20010, 0x00431024, 0x03e00008, 0x0002102b]
    if words(0x26aab0, 12) != hit:
        raise ValueError('Original area hit bitmap changed')
    return {'schema': 1, 'elf_sha256': ELF_SHA, 'root_pointer_address': 0x4563f0,
            'anchor_offset': 0x8c, 'next_offset': 0, 'sentinel': 0xffffffff,
            'flags_offset': 0x34, 'type_offset': 0x35, 'id_offset': 0x36,
            'enable_mask': 1, 'hit_bitmap_offset': 0x10,
            'original_functions': [{'address': hex(at), 'words': words(at, n)}
                                   for at, n in [(0x2661b0, 22), (0x26a750, 20),
                                                 (0x26a9c8, 15), (0x26aab0, 12)]],
            'scope': 'Original area lookup fields only; no geometry or event-readiness proof'}


def capture_area_guest(guest, witness, area_id=10, max_links=128):
    """Mirror original first-match lookup with an explicit diagnostic read bound.

    Below-anchor links are traversed but never interpreted as area objects.
    Invalid links, cycles, exhausted limits or changing bytes discard the
    selected node and hit interpretation. The supplied reader only reads RAM.
    """
    if type(area_id) is not int or not 0 <= area_id <= 255:
        raise ValueError('Area ID must fit the original byte field')
    if type(max_links) is not int or not 1 <= max_links <= 512:
        raise ValueError('Diagnostic link limit must be 1..512')
    def bounded(pointer, size):
        return pointer % 4 == 0 and 0x1000 <= pointer <= RAM_SIZE - size
    def u32(address):
        return struct.unpack('<I', guest(address, 4))[0]
    root_slot = witness['root_pointer_address']
    if not bounded(root_slot, 4):
        raise ValueError('Root export is outside guest RAM')
    root = u32(root_slot)
    result = {'area_id': area_id, 'root_pointer': hex(root), 'status': 'invalid_root',
              'reference_stable': False, 'selected_node': None, 'hit': None,
              'links': [], 'scope': 'Read-only first-match lookup; stable reads do not prove atomicity, geometry, AI or event readiness'}
    if not bounded(root, witness['anchor_offset'] + 4):
        return result
    anchor = root + witness['anchor_offset']
    bitmap_address = root + witness['hit_bitmap_offset'] + (area_id >> 5) * 4
    bitmap = guest(bitmap_address, 4)
    current = anchor
    visited = set()
    reads = []
    selected = None
    status = 'limit'
    for _ in range(max_links):
        if current in visited:
            status = 'cycle'
            break
        if not bounded(current, 4):
            status = 'invalid_link'
            break
        visited.add(current)
        raw_link = guest(current, 4)
        reads.append((current, raw_link))
        pointer = struct.unpack('<I', raw_link)[0]
        result['links'].append({'from': hex(current), 'to': hex(pointer)})
        if pointer == witness['sentinel']:
            status = 'not_found'
            break
        if not bounded(pointer, 4):
            status = 'invalid_link'
            break
        if pointer > anchor:
            size = witness['id_offset'] + 1
            if not bounded(pointer, size):
                status = 'invalid_node'
                break
            node = guest(pointer, size)
            reads.append((pointer, node))
            if node[witness['id_offset']] == area_id:
                selected = {'pointer': hex(pointer), 'bytes_hex': node.hex(),
                            'flags': node[witness['flags_offset']],
                            'type': node[witness['type_offset']],
                            'enabled': bool(node[witness['flags_offset']] & witness['enable_mask'])}
                status = 'found'
                break
        current = pointer
    same_reads = all(guest(address, len(raw)) == raw for address, raw in reads)
    bitmap_after = guest(bitmap_address, 4)
    root_after = u32(root_slot)
    stable = root == root_after and same_reads and bitmap == bitmap_after
    valid = stable and status in ('found', 'not_found')
    result.update(root_pointer_after=hex(root_after), status=status if stable else 'changed',
                  reference_stable=stable, lookup_complete=valid,
                  selected_node=selected if valid else None,
                  hit=bool(struct.unpack('<I', bitmap)[0] & (0x80000000 >> (area_id & 31))) if valid else None,
                  bitmap_address=hex(bitmap_address), bitmap_bytes_hex=bitmap.hex(),
                  bitmap_after_bytes_hex=bitmap_after.hex())
    return result

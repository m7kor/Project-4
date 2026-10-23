"""Pinned PS2 first-house actor reference: static derivation and bounded reads."""
import hashlib
import struct
import time

from tools.diagnostics.re4_name_table import segments
from tools.diagnostics.snr2_imports import resolve_imports
from tools.diagnostics.snr2_inventory import parse_snr2
from tools.diagnostics.snr2_relocations import compact_relocations

ELF_SHA = '465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'
MODULE_SHA = '01718aa3fdb13d69bc00d4b577a09231d33cf612eee79a1c489c86813c496f5f'
RAM_SIZE = 32 * 1024 * 1024


def derive_encounter_witness(module, elf):
    if hashlib.sha256(module).hexdigest() != MODULE_SHA or hashlib.sha256(elf).hexdigest() != ELF_SHA:
        raise ValueError('Encounter derivation requires the pinned original PS2 inputs')
    metadata = parse_snr2(module)
    local = {r['offset']: r for r in compact_relocations(module)}
    hi, low = local.get(0x341c), local.get(0x3420)
    if (not hi or not low or hi['type'] != 5 or low['type'] != 6
            or hi['final_low_offset'] != 0x3420 or hi['target_offset'] != 0xf320
            or low['target_offset'] != 0xf320):
        raise ValueError('Original local actor-holder relocation changed')
    words = list(struct.unpack_from('<3I', module, 0x341c))
    if words != [0x3c030001, 0x8c63f320, 0xac620004]:
        raise ValueError('Expected relocated holder load followed by actor result store')
    imports = resolve_imports(module, elf, ['EmSetEvent__FP7EM_LIST', 'errEm'])
    addresses = {row['name']: row['address'] for row in imports['imports']}
    factory = addresses['EmSetEvent__FP7EM_LIST']
    if factory != 0x1bd800 or not any(r['offset'] == 0x3414 and
            metadata['symbols'][r['symbol_index']]['name'] == 'EmSetEvent__FP7EM_LIST'
            for r in metadata['relocations']):
        raise ValueError('Original actor factory call changed')
    mapping = next(s for s in segments(elf) if s[0] == 1 and s[2] <= factory < s[2] + s[4])
    def word(address):
        return struct.unpack_from('<I', elf, mapping[1] + address - mapping[2])[0]
    if word(0x1bd87c) != 0x3c014120 or word(0x1bd880) != 0x44811000:
        raise ValueError('Original actor position scale changed')
    for address, offset in [(0x1bd910, 12), (0x1bd928, 14), (0x1bd940, 16)]:
        expected = [0x86220000 | offset, 0x44820000, 0, 0x46800020, 0x46020002,
                    0xe60000c0 + (offset - 12) * 2]
        if [word(address + i * 4) for i in range(6)] != expected:
            raise ValueError('Original actor position field conversion changed')
    expected_binding = {0x3af0: 0x2404000a, 0x3af4: 0x24050014,
                        0x5280: 0x3c050001, 0x5284: 0x24a5eaf8,
                        0x52c8: 0x8c500004, 0x52d4: 0x8c420000, 0x52d8: 0x12020039}
    if any(struct.unpack_from('<I', module, at)[0] != value for at, value in expected_binding.items()):
        raise ValueError('Original area/event/actor-reference relationship changed')
    event_path_bytes = b'event/evd/r100s03.evd\0'
    if (local[0x3afc]['target_offset'] != 0x5210 or local[0x5280]['target_offset'] != 0xeaf8
            or module[0xeaf8:0xeaf8+len(event_path_bytes)] != event_path_bytes):
        raise ValueError('Original first-house event binding changed')
    symbols = {r['offset']: metadata['symbols'][r['symbol_index']]['name'] for r in metadata['relocations']}
    if (symbols.get(0x3b08) != 'SceAtDataSet_exec__FUi9SCE_LEVELUiPvT3Uc'
            or symbols.get(0x528c) != 'EvtReadExec__8EventMgrPCcUcUi' or symbols.get(0x52d4) != 'errEm'):
        raise ValueError('Original event or error-sentinel imports changed')
    # Original InitDLL 0x254358 receives the relocated entry table from
    # 0x2a56b8, then installs table[1:3] into header words 13/14. These
    # previously held compact relocation stream cursors at initial binding.
    lifecycle_checks = {0x254380: 0x0c0a95ae, 0x254390: 0x8fa40000,
                        0x2543a4: 0x8c850004, 0x2543ac: 0xae050034,
                        0x2543b0: 0x8c830008, 0x2543b4: 0xae030038,
                        0x2a5734: 0x8e420020, 0x2a5738: 0xae220000}
    if any(word(at) != value for at, value in lifecycle_checks.items()):
        raise ValueError('Original post-load lifecycle entry installation changed')
    table = struct.unpack_from('<I', module, 0x20)[0]
    entries = list(struct.unpack_from('<3I', module, table))
    if entries != [0, 0x7700, 0x7728]:
        raise ValueError('Original module lifecycle entries changed')
    return {'schema': 3, 'module_sha256': MODULE_SHA, 'elf_sha256': ELF_SHA,
            'image_name': metadata['original_image_name'], 'image_size': len(module),
            'original_header': list(struct.unpack_from('<15I', module)),
            'installed_header_entry_offsets': entries[1:3],
            'lifecycle_installation_words': {hex(at): value for at, value in lifecycle_checks.items()},
            'holder_pointer_image_offset': 0xf320, 'actor_pointer_holder_offset': 4,
            'actor_position_offset': 0xc0, 'actor_snapshot_bytes': 0x100,
            'holder_load_words': words, 'holder_local_relocations': [hi, low],
            'factory_call_image_offset': 0x3414, 'factory_address': factory,
            'error_actor_pointer_export': addresses['errEm'],
            'event_binding': {'area_id': 10, 'registration_call_image_offset': 0x3b08,
                'callback_image_offset': 0x5210, 'event_call_image_offset': 0x528c,
                'event_path': 'event/evd/r100s03.evd', 'event_path_image_offset': 0xeaf8},
            'scope': 'Original factory return reference and position layout; not proof of live actor, AI, collision or encounter readiness'}


def relocated_header(witness, base):
    if type(base) is not int or base % 4 or not 0x1000 <= base <= RAM_SIZE - witness['image_size']:
        raise ValueError('Stage module must fit inside guest RAM')
    header = list(witness['original_header'])
    for index in (1, 3, 5, 6, 7, 8, 13, 14):
        if header[index]:
            header[index] += base
    return header


def capture_encounter_guest(guest, witness, base):
    """No writes or suspension; discard indirect data when ownership changes."""
    expected = relocated_header(witness, base)
    def header_ok(data):
        words = struct.unpack('<15I', data)
        # +0x30 is the original loader's mutable module-list link.
        # Accept only the two proven complete lifecycle pairs, never a mix.
        allowed_pairs = [tuple(expected[13:15])]
        if 'installed_header_entry_offsets' in witness:
            allowed_pairs.append(tuple(base + at for at in witness['installed_header_entry_offsets']))
        return (all(words[i] == expected[i] for i in range(12))
                and tuple(words[13:15]) in allowed_pairs)
    def bounded(pointer, size):
        return pointer % 4 == 0 and 0x1000 <= pointer <= RAM_SIZE - size
    started = time.perf_counter()
    before = guest(base, 60)
    if not header_ok(before):
        raise ValueError('Selected stage module identity is not present')
    slot = base + witness['holder_pointer_image_offset']
    holder = struct.unpack('<I', guest(slot, 4))[0]
    actor_slot = holder + witness['actor_pointer_holder_offset']
    valid_holder = bounded(holder, witness['actor_pointer_holder_offset'] + 4)
    actor = struct.unpack('<I', guest(actor_slot, 4))[0] if valid_holder else None
    sentinel_address = witness['error_actor_pointer_export']
    if not bounded(sentinel_address, 4):
        raise ValueError('Error-actor export is outside guest RAM')
    sentinel = struct.unpack('<I', guest(sentinel_address, 4))[0]
    is_error = actor is not None and actor != 0 and actor == sentinel
    size = witness['actor_snapshot_bytes']
    raw = guest(actor, size) if actor is not None and not is_error and bounded(actor, size) else None
    actor_after = struct.unpack('<I', guest(actor_slot, 4))[0] if valid_holder else None
    holder_after = struct.unpack('<I', guest(slot, 4))[0]
    sentinel_after = struct.unpack('<I', guest(sentinel_address, 4))[0]
    after = guest(base, 60)
    module_stable = header_ok(after)
    stable = module_stable and holder == holder_after and actor == actor_after and sentinel == sentinel_after
    if not stable:
        raw = None
    return {'host_counter': started, 'read_finished_host_counter': time.perf_counter(),
            'stage_module_base': hex(base), 'module_header_before_hex': before.hex(),
            'module_header_after_hex': after.hex(), 'module_identity_present_after': module_stable,
            'holder_pointer': hex(holder), 'holder_pointer_after': hex(holder_after),
            'actor_pointer': hex(actor) if actor is not None else None,
            'actor_pointer_after': hex(actor_after) if actor_after is not None else None,
            'error_actor_pointer': hex(sentinel), 'error_actor_pointer_after': hex(sentinel_after),
            'actor_is_error_sentinel': is_error if stable else None,
            'reference_stable': stable, 'actor_bytes_hex': raw.hex() if raw is not None else None,
            'position_bytes_hex': raw[0xc0:0xcc].hex() if raw is not None else None,
            'scope': 'Read-only original factory reference; stable pointers are not an atomic snapshot or proof that the actor is alive or the encounter is enabled'}

"""Read-only RE4 RAM discovery and raw pPL/Key snapshots for the pinned ELF.

Only queries and reads the explicitly selected runner. No writes, suspension,
or game-state interpretation. RAM must match three original code signatures.
"""
import argparse
import ctypes
from ctypes import wintypes as wt
import hashlib
import json
import math
from pathlib import Path
import struct
import time
import re
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).absolute().parents[2]))
from tools.diagnostics.re4_encounter_witness import derive_encounter_witness, capture_encounter_guest

RAM_SIZE = 32 * 1024 * 1024
ELF_SHA = '465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'


def capture_movie_guest(guest, addresses):
    """Bounded raw cSofdec/pG observation; no movie-completion inference."""
    def bounded(pointer, size):
        return pointer % 4 == 0 and 0x1000 <= pointer <= RAM_SIZE - size
    started = time.perf_counter()
    movie = guest(addresses['Sofdec'], 0x2b0)
    pointer = struct.unpack('<I', guest(addresses['pG'], 4))[0]
    flags = guest(pointer + 0x7f50, 16) if bounded(pointer, 0x7f60) else None
    after = struct.unpack('<I', guest(addresses['pG'], 4))[0]
    if pointer != after:
        flags = None
    player = struct.unpack_from('<I', movie, 8)[0]
    player_data = guest(player, 0x60) if bounded(player, 0x60) else None
    player_after = struct.unpack('<I', guest(addresses['Sofdec'] + 8, 4))[0]
    if player != player_after:
        player_data = None
    return {'host_counter': started, 'read_finished_host_counter': time.perf_counter(),
            'sofdec_address': hex(addresses['Sofdec']), 'sofdec_bytes_hex': movie.hex(),
            'sofdec_flags_u32': struct.unpack_from('<I', movie)[0],
            'requested_file_number_u16': struct.unpack_from('<H', movie, 0x2a4)[0],
            'game_pointer': hex(pointer), 'game_pointer_after': hex(after),
            'game_movie_flags_bytes_hex': flags.hex() if flags is not None else None,
            'game_movie_bit_10000000': bool(struct.unpack_from('<I', flags)[0] & 0x10000000) if flags is not None else None,
            'movie_player_pointer': hex(player), 'movie_player_pointer_after': hex(player_after),
            'movie_player_bytes_hex': player_data.hex() if player_data is not None else None,
            'scope': 'Raw cSofdec and pG+0x7f50 reads; pointer checks do not establish atomic coherence or playback success'}


def capture_room_guest(guest, addresses):
    """Observe the argument used by original RoomData dispatch; no guest writes."""
    started = time.perf_counter()
    pointer = struct.unpack('<I', guest(addresses['pG'], 4))[0]
    head = guest(pointer + 0x7eb0, 64) if pointer % 4 == 0 and 0x1000 <= pointer <= RAM_SIZE - 0x7ef0 else None
    room_object = guest(addresses['RoomData'], 128)
    after = struct.unpack('<I', guest(addresses['pG'], 4))[0]
    stable = pointer == after
    if not stable:
        head = None
    return {'host_counter': started, 'read_finished_host_counter': time.perf_counter(),
            'game_pointer': hex(pointer), 'game_pointer_after': hex(after), 'game_pointer_stable': stable,
            'save_head_bytes_hex': head.hex() if head is not None else None,
            'room_dispatch_argument_u16': struct.unpack_from('<H', head, 8)[0] if head is not None else None,
            'room_data_bytes_hex': room_object.hex(),
            'scope': 'Original pG+0x7eb8 RoomData dispatch argument; pointer check does not establish atomic coherence'}


def capture_guest(guest, addresses):
    started = time.monotonic()
    host_counter = time.perf_counter()
    pointer = struct.unpack('<I', guest(addresses['pPL'], 4))[0]
    player = guest(pointer, 512) if pointer % 4 == 0 and 0x1000 <= pointer <= RAM_SIZE - 512 else None
    key = guest(addresses['Key'], 128)
    after = struct.unpack('<I', guest(addresses['pPL'], 4))[0]
    return {'host_ms': int(host_counter * 1000), 'host_counter': host_counter, 'monotonic': started,
            'read_finished_monotonic': time.monotonic(), 'player_pointer': hex(pointer),
            'player_pointer_after': hex(after), 'player_pointer_stable': pointer == after,
            'player_bytes_hex': player.hex() if player is not None and pointer == after else None,
            'key_bytes_hex': key.hex()}


def wait_for_replay(run, tick, timeout):
    pattern = re.compile(rb'\[pad trace\] stage=replay .*? ee_tick=(\d+)')
    deadline = time.monotonic() + timeout
    with (run / 'stderr.txt').open('rb') as stream:
        pending = b''
        while time.monotonic() < deadline:
            data = stream.read(65536)
            if data:
                pending += data
                lines = pending.split(b'\n')
                pending = lines.pop()
                for line in lines:
                    match = pattern.search(line)
                    if match and int(match[1]) == tick:
                        return line.decode('utf-8', errors='replace')
                if len(pending) > 65536:
                    raise RuntimeError('Unbounded diagnostic log line')
            else:
                if (run / 'report.json').exists():
                    raise RuntimeError('Game ended before replay trigger')
                time.sleep(0.1)
    raise RuntimeError('Replay trigger deadline expired')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rdram-base', type=lambda s: int(s, 0))
    parser.add_argument('--samples', type=int, default=1)
    parser.add_argument('--interval', type=float, default=0.25)
    parser.add_argument('--wait-replay-tick', type=int)
    parser.add_argument('--wait-timeout', type=float, default=620)
    parser.add_argument('--room-exports', type=Path)
    parser.add_argument('--movie-witness', type=Path)
    parser.add_argument('--encounter-witness', type=Path)
    parser.add_argument('--stage-module-base', type=lambda s: int(s, 0))
    args = parser.parse_args()
    if bool(args.encounter_witness) != (args.stage_module_base is not None):
        parser.error('Encounter observation needs both its verified witness and the current stage module base')
    if (not 1 <= args.samples <= 240 or not math.isfinite(args.interval)
            or not 0.05 <= args.interval <= 2 or (args.samples - 1) * args.interval > 60):
        parser.error('Use 1..240 samples, interval 0.05..2 seconds, and a batch no longer than 60 seconds')
    if not math.isfinite(args.wait_timeout) or not 0 < args.wait_timeout <= 700:
        parser.error('Wait timeout must be in (0, 700] seconds')
    if args.wait_replay_tick is not None and args.wait_replay_tick < 0:
        parser.error('Replay tick must be nonnegative')
    root = Path(__file__).resolve().parents[2]
    identity = json.loads((args.run.parents[1] / 'identity.json').read_text(encoding='utf-8'))
    assert args.pid > 0 and not args.out.exists()
    assert ctypes.sizeof(ctypes.c_void_p) == 8
    exe = root / 'core/out/build/ps2xRuntime/ps2EntryRunner.exe'
    digest = hashlib.sha256()
    with exe.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    assert digest.hexdigest() == identity['runner_sha256']
    elf = (root / 'Resident Evil 4/SLUS_211.34').read_bytes()
    assert hashlib.sha256(elf).hexdigest() == ELF_SHA == identity['elf_sha256']
    encounter_witness = None
    if args.encounter_witness:
        encounter_bytes = args.encounter_witness.read_bytes()
        encounter_witness = json.loads(encounter_bytes)
        original_module = (root / 'artifacts/research/20261009/st1_0.snr2').read_bytes()
        if encounter_witness != derive_encounter_witness(original_module, elf):
            raise ValueError('Encounter evidence differs from the pinned original PS2 derivation')
    ph = struct.unpack_from('<I', elf, 28)[0]
    segment = struct.unpack_from('<8I', elf, ph)
    assert segment[0] == 1 and segment[2] == 0x100000
    signatures = {va: elf[segment[1] + va - segment[2]:segment[1] + va - segment[2] + 64]
                  for va in (0x100000, 0x105910, 0x109430)}
    assert all(len(s) == 64 for s in signatures.values())
    exports = json.loads((root / 'artifacts/verification/pad-transport-20261018/original-player-key-exports.json').read_text(encoding='utf-8'))
    assert exports['elf_sha256'] == ELF_SHA
    addresses = {row['name']: row['address'] for row in exports['imports']}
    room_addresses = None
    movie_addresses = None
    if args.movie_witness:
        movie_witness_bytes = args.movie_witness.read_bytes()
        movie_witness = json.loads(movie_witness_bytes)
        resolution = movie_witness['imports']
        if resolution['elf_sha256'] != ELF_SHA:
            raise ValueError('Movie export evidence is for a different ELF')
        movie_addresses = {row['name']: row['address'] for row in resolution['imports'] if row['name'] in ('pG', 'Sofdec')}
        if set(movie_addresses) != {'pG', 'Sofdec'} or any(type(a) is not int or a % 4 or not 0x1000 <= a <= RAM_SIZE - 0x2b0 for a in movie_addresses.values()):
            raise ValueError('Expected bounded original pG/Sofdec exports')
    if args.room_exports:
        room_exports_bytes = args.room_exports.read_bytes()
        room_exports = json.loads(room_exports_bytes)
        if room_exports['elf_sha256'] != ELF_SHA:
            raise ValueError('Room export evidence is for a different ELF')
        room_addresses = {row['name']: row['address'] for row in room_exports['imports'] if row['name'] in ('pG', 'RoomData')}
        if set(room_addresses) != {'pG', 'RoomData'} or any(type(a) is not int or not 0x1000 <= a <= RAM_SIZE - 128 for a in room_addresses.values()):
            raise ValueError('Expected bounded original pG/RoomData exports')

    class MemoryInfo(ctypes.Structure):
        _fields_ = [('base', ctypes.c_void_p), ('allocation', ctypes.c_void_p),
                    ('allocation_protect', wt.DWORD), ('partition', wt.WORD),
                    ('size', ctypes.c_size_t), ('state', wt.DWORD),
                    ('protect', wt.DWORD), ('kind', wt.DWORD)]

    assert ctypes.sizeof(MemoryInfo) == 48
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MemoryInfo), ctypes.c_size_t]
    kernel.VirtualQueryEx.restype = ctypes.c_size_t
    kernel.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, args.pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        name = ctypes.create_unicode_buffer(32768)
        count = wt.DWORD(len(name))
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        assert Path(name.value).resolve() == exe.resolve(), 'Unexpected process executable'

        def read(address, size):
            data = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t()
            if not kernel.ReadProcessMemory(handle, address, data, size, ctypes.byref(got)) or got.value != size:
                raise ctypes.WinError(ctypes.get_last_error())
            return data.raw

        def valid(base):
            try:
                return all(read(base + va, len(sig)) == sig for va, sig in signatures.items())
            except OSError:
                return False

        candidates = set()
        regions = 0
        scanned = 0
        if args.rdram_base is not None:
            assert 0 < args.rdram_base < (1 << 47) and valid(args.rdram_base), 'RAM signatures do not match'
            candidates.add(args.rdram_base)
        else:
            cursor = 0
            for _ in range(100000):
                info = MemoryInfo()
                if not kernel.VirtualQueryEx(handle, cursor, ctypes.byref(info), ctypes.sizeof(info)):
                    if ctypes.get_last_error() != 87:
                        raise ctypes.WinError(ctypes.get_last_error())
                    break
                start, end = int(info.base or 0), int(info.base or 0) + info.size
                if end <= cursor:
                    raise RuntimeError('Memory map did not advance')
                cursor = end
                if info.state != 0x1000 or info.kind != 0x20000 or info.protect & 0x101 or info.size < RAM_SIZE:
                    continue
                regions += 1
                if regions > 128:
                    raise RuntimeError('Bounded RAM search exhausted')
                size = min(info.size, 2 * 1024 * 1024)
                try:
                    data = read(start, size)
                except OSError:
                    continue
                scanned += size
                at = data.find(signatures[0x100000])
                while at >= 0:
                    base = start + at - 0x100000
                    if base >= start and base + RAM_SIZE <= end and valid(base):
                        candidates.add(base)
                    at = data.find(signatures[0x100000], at + 1)
            else:
                raise RuntimeError('Memory region limit exhausted')
        assert len(candidates) == 1, f'Expected one RAM image; found {len(candidates)}'
        base = candidates.pop()

        def guest(address, size):
            assert 0 <= address <= RAM_SIZE - size, 'Guest read out of RAM bounds'
            return read(base + address, size)

        print(f'RAM verified: {base:#x}; awaiting trigger' if args.wait_replay_tick is not None else f'RAM verified: {base:#x}', flush=True)
        trigger = wait_for_replay(args.run, args.wait_replay_tick, args.wait_timeout) if args.wait_replay_tick is not None else None
        if trigger:
            print('Replay trigger observed; collecting raw state batch.', flush=True)
        observations = []
        failure = None
        try:
            for i in range(args.samples):
                if i:
                    time.sleep(args.interval)
                if not valid(base):
                    raise RuntimeError('RAM signatures changed before observation')
                sample = capture_guest(guest, addresses)
                if room_addresses:
                    sample['room_state'] = capture_room_guest(guest, room_addresses)
                if movie_addresses:
                    sample['movie_state'] = capture_movie_guest(guest, movie_addresses)
                if encounter_witness:
                    sample['encounter_state'] = capture_encounter_guest(guest, encounter_witness, args.stage_module_base)
                content = (args.run / 'diagnostics/state.jsonl').read_text(encoding='utf-8')
                sample['last_capture_state'] = json.loads(content.rsplit('\n', 1)[0].splitlines()[-1])
                observations.append(sample)
        except (OSError, ValueError, IndexError, RuntimeError) as exc:
            failure = str(exc)
        record = {'scope': 'Read-only raw live RAM observation; object field meanings and atomic coherence are unproven',
                  'pid': args.pid, 'run': str(args.run.resolve()), 'runner_sha256': identity['runner_sha256'],
                  'elf_sha256': ELF_SHA, 'rdram_base': hex(base), 'signature_addresses': [hex(a) for a in signatures],
                  'search_regions': regions, 'search_bytes': scanned,
                  'player_export': hex(addresses['pPL']), 'key_export': hex(addresses['Key']),
                  'clock': vars(time.get_clock_info('monotonic')), 'trigger': trigger,
                  'host_clock': vars(time.get_clock_info('perf_counter')), 'timebase_version': 2,
                  'requested_samples': args.samples, 'interval': args.interval,
                  'observations': observations, 'completed': len(observations) == args.samples, 'error': failure}
        if room_addresses:
            record['room_export_evidence'] = {'path': str(args.room_exports),
                'sha256': hashlib.sha256(room_exports_bytes).hexdigest(), 'addresses': room_addresses}
        if movie_addresses:
            record['movie_export_evidence'] = {'path': str(args.movie_witness),
                'sha256': hashlib.sha256(movie_witness_bytes).hexdigest(), 'addresses': movie_addresses}
        if observations:
            record.update(observations[-1])
        if encounter_witness:
            record['encounter_evidence'] = {'path': str(args.encounter_witness),
                'sha256': hashlib.sha256(encounter_bytes).hexdigest(), 'stage_module_base': hex(args.stage_module_base)}
        with args.out.open('x', encoding='utf-8') as stream:
            json.dump(record, stream, indent=2)
        print(json.dumps({k: record.get(k) for k in ('pid', 'rdram_base', 'player_pointer', 'completed', 'error')}))
        if failure:
            raise RuntimeError('Partial batch preserved: ' + failure)
    finally:
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()

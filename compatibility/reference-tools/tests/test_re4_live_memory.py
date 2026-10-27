import struct
import unittest
from tools.diagnostics.re4_live_memory import capture_guest, capture_room_guest, capture_movie_guest, RAM_SIZE


class LiveGuestSnapshotTests(unittest.TestCase):
    def test_movie_observes_original_fields_and_preserves_raw_data(self):
        movie = bytearray(0x2b0)
        struct.pack_into('<II', movie, 0, 1, 0)
        struct.pack_into('<I', movie, 8, 0x20000)
        struct.pack_into('<H', movie, 0x2a4, 1)
        def read(address, size):
            data = {0x1000: bytes(movie), 0x1008: struct.pack('<I', 0x20000),
                    0x2000: struct.pack('<I', 0x30000),
                    0x37f50: struct.pack('<4I', 0x10000000, 0, 0, 0),
                    0x20000: b'P'*0x60}[address]
            self.assertEqual(len(data), size)
            return data
        result = capture_movie_guest(read, {'Sofdec': 0x1000, 'pG': 0x2000})
        self.assertEqual(result['requested_file_number_u16'], 1)
        self.assertTrue(result['game_movie_bit_10000000'])
        self.assertEqual(bytes.fromhex(result['sofdec_bytes_hex']), bytes(movie))
        self.assertEqual(bytes.fromhex(result['movie_player_bytes_hex']), b'P'*0x60)

    def test_movie_discards_changed_and_invalid_indirect_objects(self):
        for pointer, after in [(0x20000, 0x30000), (0, 0), (0x20001, 0x20001), (RAM_SIZE-4, RAM_SIZE-4)]:
            with self.subTest(pointer=pointer):
                movie = bytearray(0x2b0)
                struct.pack_into('<I', movie, 8, pointer)
                count = 0
                def read(address, size):
                    nonlocal count
                    if address == 0x1000: return bytes(movie)
                    if address == 0x1008: return struct.pack('<I', after)
                    if address == 0x2000:
                        count += 1
                        return struct.pack('<I', pointer if count == 1 else after)
                    if address == pointer + 0x7f50 and pointer == 0x20000: return bytes(16)
                    if address == pointer and pointer == 0x20000: return bytes(0x60)
                    raise AssertionError('Out-of-bounds/invalid read')
                result = capture_movie_guest(read, {'Sofdec': 0x1000, 'pG': 0x2000})
                self.assertIsNone(result['movie_player_bytes_hex'])
                self.assertIsNone(result['game_movie_flags_bytes_hex'])

    def test_movie_failed_read_is_not_playback_evidence(self):
        def read(address, size): raise OSError('unreadable')
        with self.assertRaises(OSError):
            capture_movie_guest(read, {'Sofdec': 0x1000, 'pG': 0x2000})

    def test_room_dispatch_argument_preserves_original_raw_bytes(self):
        raw = bytearray(64)
        struct.pack_into('<H', raw, 8, 0x100)
        calls = []
        def read(address, size):
            calls.append((address, size))
            if address == 0x100: return struct.pack('<I', 0x4000)
            if address == 0x4000 + 0x7eb0: return bytes(raw)
            if address == 0x200: return b'R' * 128
            raise AssertionError('Unexpected read')
        sample = capture_room_guest(read, {'pG': 0x100, 'RoomData': 0x200})
        self.assertEqual(sample['room_dispatch_argument_u16'], 0x100)
        self.assertEqual(bytes.fromhex(sample['save_head_bytes_hex']), bytes(raw))
        self.assertEqual(calls, [(0x100, 4), (0xbeb0, 64), (0x200, 128), (0x100, 4)])

    def test_room_pointer_change_and_invalid_pointer_discard_argument(self):
        for pointer, after in [(0x4000, 0x5000), (0, 0), (0x4001, 0x4001), (RAM_SIZE - 4, RAM_SIZE - 4)]:
            with self.subTest(pointer=pointer, after=after):
                reads = []
                def read(address, size):
                    reads.append((address, size))
                    if address == 0x100:
                        return struct.pack('<I', pointer if reads.count((0x100, 4)) == 1 else after)
                    if address == 0x200: return bytes(128)
                    if address == pointer + 0x7eb0 and pointer == 0x4000: return bytes(64)
                    raise AssertionError('Unexpected read')
                sample = capture_room_guest(read, {'pG': 0x100, 'RoomData': 0x200})
                self.assertIsNone(sample['room_dispatch_argument_u16'])
                self.assertIsNone(sample['save_head_bytes_hex'])
                if pointer != 0x4000:
                    self.assertEqual(reads, [(0x100, 4), (0x200, 128), (0x100, 4)])

    def test_room_read_failure_propagates(self):
        def read(address, size): raise OSError('read failed')
        with self.assertRaises(OSError):
            capture_room_guest(read, {'pG': 0x100, 'RoomData': 0x200})

    def reader(self, pointer, after=None):
        calls = []
        pointer_reads = 0

        def read(address, size):
            nonlocal pointer_reads
            calls.append((address, size))
            if address == 0x100:
                pointer_reads += 1
                return struct.pack('<I', pointer if pointer_reads == 1 or after is None else after)
            if address == 0x200:
                return bytes(range(128))
            if address == pointer and size == 512:
                return b'P' * 512
            raise AssertionError('Unexpected read')
        return read, calls

    def test_stable_pointer_preserves_raw_bytes_and_read_times(self):
        read, _ = self.reader(0x3000)
        sample = capture_guest(read, {'pPL': 0x100, 'Key': 0x200})
        self.assertTrue(sample['player_pointer_stable'])
        self.assertEqual(bytes.fromhex(sample['player_bytes_hex']), b'P' * 512)
        self.assertEqual(bytes.fromhex(sample['key_bytes_hex']), bytes(range(128)))
        self.assertGreaterEqual(sample['read_finished_monotonic'], sample['monotonic'])

    def test_changed_pointer_discards_object_payload(self):
        read, _ = self.reader(0x3000, 0x4000)
        sample = capture_guest(read, {'pPL': 0x100, 'Key': 0x200})
        self.assertFalse(sample['player_pointer_stable'])
        self.assertIsNone(sample['player_bytes_hex'])
        self.assertEqual(sample['player_pointer_after'], '0x4000')

    def test_null_unaligned_and_overflowing_objects_are_not_read(self):
        for pointer in (0, 0x3001, RAM_SIZE - 4, 0xffffffff):
            with self.subTest(pointer=pointer):
                read, calls = self.reader(pointer)
                sample = capture_guest(read, {'pPL': 0x100, 'Key': 0x200})
                self.assertIsNone(sample['player_bytes_hex'])
                self.assertEqual(calls, [(0x100, 4), (0x200, 128), (0x100, 4)])

    def test_read_failure_is_not_a_successful_sample(self):
        def failure(address, size):
            raise OSError('unreadable process memory')
        with self.assertRaises(OSError):
            capture_guest(failure, {'pPL': 0x100, 'Key': 0x200})

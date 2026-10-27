import struct
import unittest
from tools.diagnostics.re4_encounter_witness import (
    derive_encounter_witness, capture_encounter_guest, relocated_header, RAM_SIZE)


class EncounterWitnessTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x1000000
        self.holder = 0x20000
        self.actor = 0x30000
        self.sentinel = 0x50000
        self.witness = {'image_size': 0x20000, 'original_header': [0]*15,
            'holder_pointer_image_offset': 0xf320, 'actor_pointer_holder_offset': 4,
            'actor_snapshot_bytes': 0x100, 'error_actor_pointer_export': 0x4000}
        self.witness['original_header'][0] = 0x32524e53
        self.witness['original_header'][1] = 0x100
        self.witness['original_header'][11] = 0x20000
        self.header = struct.pack('<15I', *relocated_header(self.witness, self.base))
        self.actor_data = bytearray(0x100)
        struct.pack_into('<3f', self.actor_data, 0xc0, -77630, 860, -36500)

    def reader(self, holder_after=None, actor_after=None, final_header=None, sentinel_after=None):
        counts = {}
        def read(address, size):
            counts[address] = counts.get(address, 0) + 1
            if address == self.base:
                value = final_header if counts[address] > 1 and final_header is not None else self.header
            elif address == self.base + 0xf320:
                value = struct.pack('<I', holder_after if counts[address] > 1 and holder_after is not None else self.holder)
            elif address == self.holder + 4:
                value = struct.pack('<I', actor_after if counts[address] > 1 and actor_after is not None else self.actor)
            elif address == 0x4000:
                value = struct.pack('<I', sentinel_after if counts[address] > 1 and sentinel_after is not None else self.sentinel)
            elif address == self.actor:
                value = bytes(self.actor_data)
            else:
                raise AssertionError(f'Unexpected indirect read {address:#x}+{size:#x}')
            self.assertEqual(len(value), size)
            return value
        return read

    def test_preserves_actor_and_position_raw_bytes(self):
        result = capture_encounter_guest(self.reader(), self.witness, self.base)
        self.assertTrue(result['reference_stable'])
        self.assertEqual(bytes.fromhex(result['actor_bytes_hex']), self.actor_data)
        self.assertEqual(struct.unpack('<3f', bytes.fromhex(result['position_bytes_hex'])), (-77630, 860, -36500))

    def test_discards_actor_if_holder_or_actor_reference_changes(self):
        for changes in ({'holder_after': 0x40000}, {'actor_after': 0x50000}):
            with self.subTest(changes=changes):
                result = capture_encounter_guest(self.reader(**changes), self.witness, self.base)
                self.assertFalse(result['reference_stable'])
                self.assertIsNone(result['actor_bytes_hex'])

    def test_module_unload_discards_indirect_data(self):
        result = capture_encounter_guest(self.reader(final_header=bytes(60)), self.witness, self.base)
        self.assertFalse(result['module_identity_present_after'])
        self.assertIsNone(result['actor_bytes_hex'])

    def test_mutable_module_list_link_is_not_identity(self):
        header = bytearray(self.header)
        struct.pack_into('<I', header, 48, 0x123456)
        result = capture_encounter_guest(self.reader(final_header=bytes(header)), self.witness, self.base)
        self.assertTrue(result['reference_stable'])

    def test_original_post_load_entries_are_accepted_as_a_complete_pair(self):
        self.witness['installed_header_entry_offsets'] = [0x7700, 0x7728]
        installed = bytearray(self.header)
        struct.pack_into('<2I', installed, 52, self.base + 0x7700, self.base + 0x7728)
        result = capture_encounter_guest(self.reader(final_header=bytes(installed)), self.witness, self.base)
        self.assertTrue(result['reference_stable'])
        self.assertIsNotNone(result['actor_bytes_hex'])
        for pair in [(self.base + 0x7700, 0), (0, self.base + 0x7728),
                     (self.base + 0x7704, self.base + 0x7728)]:
            with self.subTest(pair=pair):
                struct.pack_into('<2I', installed, 52, *pair)
                result = capture_encounter_guest(self.reader(final_header=bytes(installed)), self.witness, self.base)
                self.assertFalse(result['module_identity_present_after'])
                self.assertIsNone(result['actor_bytes_hex'])

    def test_rejects_absent_module_before_reading_its_pointers(self):
        def read(address, size):
            self.assertEqual((address, size), (self.base, 60))
            return bytes(60)
        with self.assertRaises(ValueError):
            capture_encounter_guest(read, self.witness, self.base)

    def test_invalid_holder_never_dereferenced(self):
        for pointer in (0, 0x20001, RAM_SIZE - 4):
            with self.subTest(pointer=pointer):
                self.holder = pointer
                result = capture_encounter_guest(self.reader(), self.witness, self.base)
                self.assertIsNone(result['actor_pointer'])
                self.assertIsNone(result['actor_bytes_hex'])

    def test_invalid_actor_never_read(self):
        for pointer in (0, 0x30001, RAM_SIZE - 4):
            with self.subTest(pointer=pointer):
                self.actor = pointer
                result = capture_encounter_guest(self.reader(), self.witness, self.base)
                self.assertIsNone(result['actor_bytes_hex'])

    def test_error_sentinel_is_not_treated_as_an_actor_object(self):
        self.actor = self.sentinel
        result = capture_encounter_guest(self.reader(), self.witness, self.base)
        self.assertTrue(result['actor_is_error_sentinel'])
        self.assertIsNone(result['actor_bytes_hex'])

    def test_changed_error_sentinel_discards_actor_data(self):
        result = capture_encounter_guest(self.reader(sentinel_after=self.actor), self.witness, self.base)
        self.assertFalse(result['reference_stable'])
        self.assertIsNone(result['actor_is_error_sentinel'])
        self.assertIsNone(result['actor_bytes_hex'])

    def test_module_bounds_and_read_errors_fail_closed(self):
        for base in (0, 0x1000001, RAM_SIZE - 4):
            with self.assertRaises(ValueError):
                relocated_header(self.witness, base)
        def read(address, size):
            raise OSError('process ended')
        with self.assertRaises(OSError):
            capture_encounter_guest(read, self.witness, self.base)

    def test_derivation_rejects_unpinned_inputs(self):
        with self.assertRaises(ValueError):
            derive_encounter_witness(bytes(128), bytes(128))


if __name__ == '__main__':
    unittest.main()

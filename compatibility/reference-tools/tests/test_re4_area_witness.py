import struct
import unittest

from tools.diagnostics.re4_area_witness import capture_area_guest, derive_area_witness
from tools.diagnostics.re4_encounter_witness import RAM_SIZE


class AreaWitnessTests(unittest.TestCase):
    def setUp(self):
        self.root = 0x5000
        self.anchor = self.root + 0x8c
        self.node = 0x9000
        self.witness = {'root_pointer_address': 0x4000, 'anchor_offset': 0x8c,
                        'next_offset': 0, 'sentinel': 0xffffffff, 'flags_offset': 0x34,
                        'type_offset': 0x35, 'id_offset': 0x36, 'enable_mask': 1,
                        'hit_bitmap_offset': 0x10}
        self.memory = bytearray(0x10000)
        self.put(0x4000, self.root)
        self.put(self.anchor, self.node)
        self.put(self.node, 0xffffffff)
        self.memory[self.node + 0x34:self.node + 0x37] = bytes([3, 2, 10])

    def put(self, at, value):
        struct.pack_into('<I', self.memory, at, value)

    def reader(self, change=None):
        counts = {}
        def read(at, size):
            self.assertGreaterEqual(at, 0x1000)
            self.assertLessEqual(at + size, len(self.memory))
            counts[at] = counts.get(at, 0) + 1
            if change:
                change(at, size, counts[at])
            return bytes(self.memory[at:at+size])
        return read

    def test_enabled_is_distinct_from_hit(self):
        result = capture_area_guest(self.reader(), self.witness)
        self.assertEqual(result['status'], 'found')
        self.assertTrue(result['selected_node']['enabled'])
        self.assertFalse(result['hit'])
        self.memory[self.node + 0x34] = 2
        self.put(self.root + 0x10, 0x00200000)
        result = capture_area_guest(self.reader(), self.witness)
        self.assertFalse(result['selected_node']['enabled'])
        self.assertTrue(result['hit'])

    def test_below_anchor_links_are_not_area_objects(self):
        self.put(self.anchor, self.anchor - 4)
        self.put(self.anchor - 4, self.node)
        result = capture_area_guest(self.reader(), self.witness)
        self.assertEqual(result['selected_node']['pointer'], hex(self.node))
        self.assertEqual(len(result['links']), 2)

    def test_first_matching_id_wins(self):
        self.put(self.node, 0xa000)
        self.memory[0xa036] = 10
        result = capture_area_guest(self.reader(), self.witness)
        self.assertEqual(result['selected_node']['pointer'], hex(self.node))

    def test_sentinel_is_complete_absence_in_observed_prefix(self):
        self.memory[self.node + 0x36] = 11
        result = capture_area_guest(self.reader(), self.witness)
        self.assertEqual(result['status'], 'not_found')
        self.assertTrue(result['lookup_complete'])
        self.assertIsNone(result['selected_node'])

    def test_cycles_and_limit_are_incomplete(self):
        self.memory[self.node + 0x36] = 11
        self.put(self.node, self.node)
        for limit, status in [(128, 'cycle'), (1, 'limit')]:
            result = capture_area_guest(self.reader(), self.witness, max_links=limit)
            self.assertEqual(result['status'], status)
            self.assertFalse(result['lookup_complete'])
            self.assertIsNone(result['hit'])

    def test_invalid_links_never_dereferenced(self):
        for pointer in (0, 0x9001, RAM_SIZE):
            with self.subTest(pointer=pointer):
                self.put(self.anchor, pointer)
                result = capture_area_guest(self.reader(), self.witness)
                self.assertEqual(result['status'], 'invalid_link')
                self.assertIsNone(result['selected_node'])

    def test_invalid_root_never_dereferenced(self):
        for pointer in (0, 0x5001, RAM_SIZE - 4):
            self.put(0x4000, pointer)
            result = capture_area_guest(self.reader(), self.witness)
            self.assertEqual(result['status'], 'invalid_root')

    def test_node_near_ram_end_fails_before_object_read(self):
        self.put(self.anchor, RAM_SIZE - 4)
        result = capture_area_guest(self.reader(), self.witness)
        self.assertEqual(result['status'], 'invalid_node')

    def test_changed_root_link_flags_or_bitmap_discards_interpretations(self):
        for target in ('root', 'link', 'flags', 'bitmap'):
            with self.subTest(target=target):
                self.setUp()
                def change(at, size, count):
                    if target == 'root' and at == 0x4000 and count == 2:
                        self.put(at, 0x6000)
                    elif target == 'link' and at == self.anchor and count == 2:
                        self.put(at, 0xffffffff)
                    elif target == 'flags' and at == self.node and count == 2:
                        self.memory[at + 0x34] ^= 1
                    elif target == 'bitmap' and at == self.root + 0x10 and count == 2:
                        self.put(at, 0x00200000)
                result = capture_area_guest(self.reader(change), self.witness)
                self.assertEqual(result['status'], 'changed')
                self.assertIsNone(result['selected_node'])
                self.assertIsNone(result['hit'])

    def test_high_id_uses_next_bitmap_word(self):
        self.memory[self.node + 0x36] = 33
        self.put(self.root + 0x14, 0x40000000)
        result = capture_area_guest(self.reader(), self.witness, area_id=33)
        self.assertTrue(result['hit'])
        self.assertEqual(result['bitmap_address'], hex(self.root + 0x14))

    def test_bad_limits_or_ids_and_read_errors(self):
        for kwargs in ({'area_id': -1}, {'area_id': 256}, {'max_links': 0}, {'max_links': 513}):
            with self.assertRaises(ValueError):
                capture_area_guest(self.reader(), self.witness, **kwargs)
        def fail(at, size):
            raise OSError('process ended')
        with self.assertRaises(OSError):
            capture_area_guest(fail, self.witness)

    def test_unpinned_elf_rejected(self):
        with self.assertRaises(ValueError):
            derive_area_witness(bytes(128))


if __name__ == '__main__':
    unittest.main()

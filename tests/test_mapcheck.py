import unittest
from ps2l.mapcheck import audit, destination


class MapCheckTests(unittest.TestCase):
    def test_empty_map_or_extent_crossing_code_gap_cannot_pass(self):
        self.assertFalse(audit({0x1000:0}, [])['passed'])
        self.assertFalse(audit({0x1000:0, 0x1008:0}, [(0x1000,0x100c)])['passed'])

    def test_detects_re4_missing_likely_branch_target(self):
        words = {0x1000:0x04A20003, 0x1004:0x8C820014,
                 0x1008:0x03E00008, 0x100C:0xAC850030,
                 0x1010:0x03E00008, 0x1014:0xAC820030}
        broken = audit(words, [(0x1000, 0x1010)])
        self.assertFalse(broken['passed'])
        self.assertEqual(broken['unmapped_targets'][0]['target'], '0x1010')
        self.assertTrue(audit(words, [(0x1000, 0x1018)])['passed'])

    def test_missing_nonzero_return_slot_is_an_error(self):
        result = audit({0x1000:0x03E00008, 0x1004:0xAC820030}, [(0x1000,0x1004)])
        self.assertFalse(result['passed'])
        self.assertEqual(result['unmapped_delay_slots'], [{'source':'0x1000','slot':'0x1004'}])

    def test_trap_immediate_is_not_a_branch(self):
        self.assertIsNone(destination(0x1000, 0x04480003))
        self.assertEqual(destination(0x1000, 0x0440FFFF), 0x1000)

    def test_jump_page_uses_pc_plus_four(self):
        self.assertEqual(destination(0x0FFFFFFC, 0x08000000), 0x10000000)

    def test_overlapping_or_truncated_map_is_rejected(self):
        words = {0x1000:0, 0x1004:0}
        self.assertFalse(audit(words, [(0x1000,0x1008),(0x1004,0x1008)])['passed'])
        self.assertFalse(audit(words, [(0x1000,0x1010)])['passed'])

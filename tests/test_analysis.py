"""ISA and executable-continuation regression cases with known raw words."""
from pathlib import Path
import sys
import struct
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ps2l"))
from analyze import Analysis, is_syscall, looks_like_prologue
from canary import fixture
from fingerprint import parse_elf


class SyntheticElf:
    def __init__(self, words):
        self.words = words
        start, end = min(words), max(words) + 4
        self.sections = [SimpleNamespace(addr=start, size=end - start, is_body=True)]

    def code_words(self):
        return min(self.words), self.words

    def section_at(self, addr):
        return next((s for s in self.sections if s.addr <= addr < s.addr + s.size), None)


class EncodingTests(unittest.TestCase):
    def test_syscall_is_special_not_andi(self):
        self.assertTrue(is_syscall(0x0000000C))
        self.assertTrue(is_syscall((0x12345 << 6) | 0x0C))
        self.assertFalse(is_syscall(0x304200FF))  # andi v0,v0,0xff
        self.assertFalse(is_syscall(0x0000000D))  # break

    def test_syscall_census_decodes_real_words(self):
        analysis = Analysis(SyntheticElf({0x1000: 0x0000000C, 0x1004: 0x304200FF,
                                          0x1008: (7 << 6) | 0x0C}))
        analysis._census_syscalls()
        self.assertEqual(analysis.syscall_sites, [(0x1000, 0), (0x1008, 7)])

    def test_regimm_branch_and_mmi_are_distinct(self):
        self.assertEqual(Analysis._pc_relative_target(0x1000, 0x04400003), 0x1010)  # bltz v0
        self.assertIsNone(Analysis._pc_relative_target(0x1000, 0x70000003))  # MMI
        self.assertIsNone(Analysis._pc_relative_target(0x1000, 0x04480003))  # tgei

    def test_ra_load_does_not_claim_a_saved_register(self):
        self.assertFalse(looks_like_prologue({0x1000: 0xDFBF0010, 0x1004: 0}, 0x1000))
        self.assertTrue(looks_like_prologue({0x1000: 0xFFBF0010, 0x1004: 0}, 0x1000))

    def test_fingerprint_counts_syscall_code_fields_not_andi(self):
        data = bytearray(fixture())
        struct.pack_into('<3I', data, 0x100, 0x304200FF, 0x0000000C,
                         (0x12345 << 6) | 0x0C)
        info = parse_elf(bytes(data), Path('synthetic.elf'))
        self.assertEqual(info['syscalls'], 2)
        self.assertEqual(info['syscall_imms'], {0: 1, 0x12345: 1})


class OwnershipTests(unittest.TestCase):
    def test_interval_index_matches_linear_oracle_including_overlaps(self):
        a = Analysis(SyntheticElf({0x1000: 0}))
        a.funcs = {0x1000: 32, 0x1008: 4, 0x1030: 8}
        for addr in range(0xFFC, 0x1040):
            expected = next((s for s in sorted(a.funcs)
                             if s <= addr < s + a.funcs[s]), None)
            self.assertEqual(a._owner_of(addr), expected)

    def test_trim_invalidates_cached_ownership(self):
        a = Analysis(SyntheticElf({0x1000: 0, 0x1004: 0, 0x1008: 0}))
        a.funcs = {0x1000: 12, 0x1004: 8}
        self.assertEqual(a._owner_of(0x1008), 0x1000)
        a._trim()
        self.assertEqual(a._owner_of(0x1008), 0x1004)


class ContinuationTests(unittest.TestCase):
    def test_re4_regimm_likely_branch_keeps_both_returns_and_slots(self):
        a = Analysis(SyntheticElf({0x1000: 0x04A20003, 0x1004: 0x8C820014,
                                   0x1008: 0x03E00008, 0x100C: 0xAC850030,
                                   0x1010: 0x03E00008, 0x1014: 0xAC820030}))
        a._walk(0x1000, 'entry')
        self.assertEqual(a.funcs[0x1000], 24)
        self.assertEqual(a._owner_of(0x1010), 0x1000)
        self.assertEqual(a._owner_of(0x1014), 0x1000)

    def test_terminal_leaf_keeps_nonzero_delay_slot(self):
        a = Analysis(SyntheticElf({0x1000: 0x03E00008, 0x1004: 0xAC820030}))
        a._walk(0x1000, 'entry')
        self.assertEqual(a.funcs[0x1000], 8)

    def test_follow_keeps_slot_when_backward_branch_reaches_visited_code(self):
        a = Analysis(SyntheticElf({0x1000:0x24020001, 0x1004:0x1440FFFE,
                                   0x1008:0x2442FFFF}))
        self.assertEqual(a._follow(0x1000), 0x1008)

    def test_end_extension_keeps_delay_slot_of_a_clipped_branch(self):
        a = Analysis(SyntheticElf({0x1000:0x1440FFFF, 0x1004:0x2442FFFF,
                                   0x1008:0x03E00008, 0x100C:0}))
        a.funcs = {0x1000:4, 0x1008:8}
        a.kind = {0x1000:'entry', 0x1008:'entry'}
        a._extend_ends_to_call_returns()
        self.assertEqual(a.funcs[0x1000], 8)
        self.assertEqual(a.funcs[0x1008], 8)

    def test_ordinary_instruction_has_sequential_successor(self):
        self.assertEqual(Analysis._fallthrough(0x1000, 0x00501024), 0x1004)

    def test_returns_jumps_and_delay_slots_do_not_fall_through(self):
        for word in (0x03E00008, 0x08000400, 0x10000002, 0x42000018, 0x0000000D):
            self.assertIsNone(Analysis._fallthrough(0x1000, word))
        a = Analysis(SyntheticElf({0x1000: 0x03E00008, 0x1004: 0, 0x1008: 0x24020001}))
        a.funcs = {0x1000: 8}
        a._close_fallthrough_holes()
        self.assertNotIn(0x1008, a.funcs)

    def test_call_and_conditional_branch_resume_after_slot(self):
        self.assertEqual(Analysis._fallthrough(0x1000, 0x0C000500), 0x1008)
        self.assertEqual(Analysis._fallthrough(0x1000, 0x14400002), 0x1008)

    def test_clipped_and_continues_into_executable_hole(self):
        a = Analysis(SyntheticElf({0x1000: 0x00501024, 0x1004: 0x24020007,
                                   0x1008: 0x03E00008, 0x100C: 0}))
        a.funcs = {0x1000: 4}
        a._close_fallthrough_holes()
        self.assertEqual(a.kind[0x1004], "fallthrough")
        self.assertEqual(a.fallthrough_added, 1)
        self.assertIsNotNone(a._owner_of(0x1004))

    def test_continuation_does_not_cross_section_or_replace_entry(self):
        a = Analysis(SyntheticElf({0x1000: 0x24020007, 0x1004: 0x03E00008, 0x1008: 0}))
        a.funcs = {0x1000: 4, 0x1004: 8}
        a._close_fallthrough_holes()
        self.assertEqual(a.fallthrough_added, 0)
        b = Analysis(SyntheticElf({0x1000: 0x24020007}))
        b.funcs = {0x1000: 4}
        b._close_fallthrough_holes()
        self.assertEqual(b.funcs, {0x1000: 4})


if __name__ == "__main__":
    unittest.main()

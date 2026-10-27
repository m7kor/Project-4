"""Concrete instruction words from retail IRX/ELF and control-flow boundaries."""
import unittest
from tools.bios_mine.mipsdec import decode


class MiningDecoderTests(unittest.TestCase):
    def test_retail_cdvd_dma_instructions(self):
        for word, mnemonic, arguments in (
            (0x946200A6, "lhu", ["$v0", "166($v1)"]),
            (0x946200A4, "lhu", ["$v0", "164($v1)"]),
            (0xAC7700A8, "sw", ["$s7", "168($v1)"]),
            (0x02E02821, "addu", ["$a1", "$s7", "$zero"]),
            (0x00452825, "or", ["$a1", "$v0", "$a1"]),
            (0x8C635568, "lw", ["$v1", "21864($v1)"]),
        ):
            with self.subTest(word=hex(word)):
                result = decode(word)
                self.assertEqual(result["mnem"], mnemonic)
                self.assertEqual(result["args"], arguments)

    def test_immediate_arithmetic_includes_source_register(self):
        self.assertEqual(decode(0x27BDFFF0)["args"], ["$sp", "$sp", "-16"])
        self.assertEqual(decode(0x34A50200)["args"], ["$a1", "$a1", "0x200"])

    def test_register_jumps_have_unknown_targets_without_register_state(self):
        for word in (0x03E00008, 0x0040F809):
            result = decode(word, 0x1000)
            self.assertTrue(result["is_jump"])
            self.assertTrue(result["has_delay"])
            self.assertIsNone(result["target"])
            self.assertEqual(result["target_kind"], "reg")

    def test_jump_at_page_boundary_uses_delay_slot_address(self):
        self.assertEqual(decode(0x08000004, 0x0FFFFFFC)["target"], 0x10000010)

    def test_branch_target_wraps_to_32_bits(self):
        self.assertEqual(decode(0x1000FFFF, 0)["target"], 0)
        self.assertEqual(decode(0x1000FFFE, 0)["target"], 0xFFFFFFFC)

    def test_regimm_traps_are_not_branches(self):
        result = decode(0x04880001, 0x1000)  # tgei a0,1
        self.assertEqual(result["mnem"], "tgei")
        self.assertFalse(result["has_delay"])
        self.assertFalse(result["is_branch"])
        self.assertIsNone(result["target"])

    def test_likely_branch_names(self):
        self.assertEqual(decode(0x04830001)["mnem"], "bgezl")
        self.assertEqual(decode(0x04920001)["mnem"], "bltzall")

    def test_ee_shift_and_load_quad_have_correct_operands(self):
        self.assertEqual(decode(0x0002113C)["mnem"], "dsll32")
        self.assertEqual(decode(0x0002113C)["args"], ["$v0", "$v0", "4"])
        self.assertEqual(decode(0x7BA40000)["mnem"], "lq")
        self.assertEqual(decode(0x7FA40000)["mnem"], "sq")

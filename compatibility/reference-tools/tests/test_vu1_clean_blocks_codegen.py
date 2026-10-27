import unittest
from pathlib import Path

from tools.diagnostics.vu1_clean_blocks_codegen import arithmetic_body, scheduling_body, clean_masks, generate
from tools.diagnostics.vu1_table_preservation import load


def instruction(*, upper=0x28, reads=(), write=(0, 0), lower=(0, 0), acc_read=0, acc_write=0):
    return {'upper': upper, 'lower': 0, 'i_bit': False,
            'lo': {'write': lower}, 'hi': {'write': write, 'reads': reads,
                                          'acc_read': acc_read, 'acc_write': acc_write}}


class CleanBlockGenerationTests(unittest.TestCase):
    def test_partial_write_does_not_certify_unwritten_lane(self):
        writer = instruction(write=(1, 0xe))
        read_w = instruction(upper=0x28 | (1 << 16), reads=[(1, 1)])
        read_xyz = instruction(upper=0x28 | (1 << 11), reads=[(1, 0xe)])
        self.assertEqual(clean_masks([writer, read_w, read_xyz]), [0, 0, 1])

    def test_raw_lower_write_and_float_to_int_invalidate_facts(self):
        writer = instruction(write=(1, 15))
        raw = instruction(lower=(1, 15))
        reader = instruction(upper=0x28 | (1 << 11), reads=[(1, 15)])
        self.assertEqual(clean_masks([writer, raw, reader]), [0, 0, 0])
        # special opcode 0x14 is FTOI0: its output is raw integer bits.
        ftoi = instruction(upper=0x3c | (0x14 << 4), write=(1, 15))
        self.assertEqual(clean_masks([writer, ftoi, reader]), [0, 0, 0])

    def test_accumulator_lanes_and_untrusted_entry_vf0(self):
        writer = instruction(acc_write=0xe)
        read_w = instruction(acc_read=1)
        read_xyz = instruction(acc_read=0xe)
        self.assertEqual(clean_masks([writer, read_w, read_xyz]), [0, 0, 4])
        zero = instruction(upper=0, reads=[(0, 15)])
        self.assertEqual(clean_masks([zero, zero]), [0, 3])

    def test_simultaneous_raw_destination_never_creates_a_clean_fact(self):
        writer = instruction(write=(1, 15), lower=(1, 15))
        reader = instruction(upper=0x28 | (1 << 11), reads=[(1, 15)])
        self.assertEqual(clean_masks([writer, reader]), [0, 0])

    def test_specialization_and_reference_share_semantic_source(self):
        root = Path(__file__).resolve().parents[1]
        directory = root / 'core/ps2xRuntime/src/lib/vu'
        upper = (directory / 'ps2_vu1_upper.cpp').read_text()
        step = (directory / 'ps2_vu1_step.inl').read_text()
        self.assertIn('#include "../ps2_vu1_upper_body.inl"', arithmetic_body(upper))
        self.assertIn('#include "../ps2_vu1_step_body.inl"', scheduling_body(step))
        with self.assertRaises(ValueError):
            arithmetic_body(upper.replace('ps2_vu1_upper_body.inl', 'unshared.inl'))
        with self.assertRaises(ValueError):
            scheduling_body(step.replace('ps2_vu1_step_body.inl', 'unshared.inl'))

    def test_real_generation_keeps_original_tables_and_is_deterministic(self):
        root = Path(__file__).resolve().parents[1]
        base = root / 'artifacts/tool-audit/20261016/vu-clean-blocks-before/vu1_compiled_programs.inc'
        if not base.exists():
            self.skipTest('Local captured-code fixture is not distributed')
        upper = (root / 'core/ps2xRuntime/src/lib/vu/ps2_vu1_upper.cpp').read_text()
        step = (root / 'core/ps2xRuntime/src/lib/vu/ps2_vu1_step.inl').read_text()
        regions = {'770ea85198e8e87f': [[0x1d0, 0x4a0], [0x1040, 0x1410]]}
        output, report = generate(base.read_text(), upper, step, regions, 16)
        self.assertEqual((output, report), generate(base.read_text(), upper, step, regions, 16))
        self.assertTrue(any(mask for block in report for mask in block['masks']))
        # Compare complete original constexpr literals and all 12,288 entries
        # through the independent table-preservation reader.
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / 'generated.inc'
            candidate.write_text(output)
            self.assertEqual(load(base), load(candidate))
        for invalid in ({}, {'missing': [[0, 8]]}, {'770ea85198e8e87f': [[1, 8]]},
                        {'770ea85198e8e87f': [[0, 16], [8, 24]]}):
            with self.assertRaises(ValueError):
                generate(base.read_text(), upper, step, invalid, 16)


if __name__ == '__main__':
    unittest.main()

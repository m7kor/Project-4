import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('vu_codegen', Path(__file__).resolve().parents[1] / 'tools/vu1_fusion_codegen.py')
codegen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codegen)


class SharedRegionTests(unittest.TestCase):
    def test_outside_region_keeps_target_identity(self):
        source = ['a', 'b', 'c', 'd', 'e', 'f']
        target = ['x', 'b', 'c', 'y', 'e', 'z']
        self.assertEqual(codegen.shared_region_images({'base': source, 'other': target},
                         {'base': [[8, 24], [32, 40]]}), {'other': 'base'})

    def test_one_changed_pair_rejects_entire_alias(self):
        self.assertEqual(codegen.shared_region_images({'base': ['a', 'b', 'c'], 'other': ['a', 'changed-flags', 'c']},
                         {'base': [[0, 24]]}), {})

    def test_matching_only_one_region_is_insufficient(self):
        self.assertEqual(codegen.shared_region_images({'base': ['a', 'b', 'c'], 'other': ['a', 'b', 'x']},
                         {'base': [[0, 8], [16, 24]]}), {})

    def test_shifted_instructions_cannot_alias(self):
        self.assertEqual(codegen.shared_region_images({'base': ['a', 'b', 'c'], 'other': ['x', 'a', 'b']},
                         {'base': [[0, 16]]}), {})

    def test_bounds_and_alignment_are_checked(self):
        for span in ([-8, 8], [0, 32], [1, 16], [16, 8]):
            with self.subTest(span=span), self.assertRaises(ValueError):
                codegen.shared_region_images({'base': ['a', 'b', 'c'], 'other': ['a', 'b', 'c']}, {'base': [span]})


if __name__ == '__main__':
    unittest.main()

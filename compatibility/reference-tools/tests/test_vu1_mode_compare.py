import unittest
from tools.diagnostics.vu1_mode_compare import equivalent, parse_result


VALID = ('snapshots=2 vu1_cycles=100 best=0.01 s ns/cycle=100 result=abc\n'
         'compiled=2/2 status_hashed=yes\n'
         'gif_packets=4 gif_result=def\n'
         'code_image_updates=2 code_cache_publication=yes\n')


class VuModeCompareTests(unittest.TestCase):
    def test_complete_result(self):
        result = parse_result(VALID)
        self.assertEqual(result['cycles'], 100)
        self.assertEqual(result['gif_packets'], 4)

    def test_missing_or_ambiguous_output_rejected(self):
        for data in (VALID.split('gif_packets')[0], VALID + VALID,
                     VALID.replace('status_hashed=yes', 'status_hashed=no'),
                     VALID.replace('compiled=2/2', 'compiled=2/3'),
                     VALID.replace('compiled=2/2', 'compiled=3/2'),
                     VALID.replace('code_cache_publication=yes', 'code_cache_publication=no'),
                     VALID.split('code_image_updates')[0]):
            with self.assertRaises(ValueError):
                parse_result(data)

    def test_every_observable_field_compared(self):
        result = parse_result(VALID)
        for key in ('cycles', 'state_hash', 'gif_packets', 'gif_hash', 'snapshots'):
            altered = dict(result, **{key: 'different'})
            self.assertFalse(equivalent([result, altered]))
        self.assertTrue(equivalent([result, dict(result, compiled=0)]))


if __name__ == '__main__':
    unittest.main()

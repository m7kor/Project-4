import copy
import math
import struct
import unittest
from tools.diagnostics.re4_player_motion_report import summarize


def batch(angles):
    samples = []
    for i, degrees in enumerate(angles):
        raw = bytearray(512)
        yaw = math.radians(degrees)
        matrix = [math.cos(yaw), 0, -math.sin(yaw), 0, 0, 1, 0, 0,
                  math.sin(yaw), 0, math.cos(yaw), 0, i * 3, 0, i * 4, 1]
        struct.pack_into('<16f', raw, 0x10, *matrix)
        struct.pack_into('<3f', raw, 0xc0, i * 3, 0, i * 4)
        struct.pack_into('<f', raw, 0xd4, yaw)
        samples.append({'player_pointer_stable': True, 'player_pointer': '0x1000',
                        'player_pointer_after': '0x1000', 'player_bytes_hex': raw.hex(), 'monotonic': float(i)})
    return {'completed': True, 'error': None, 'observations': samples}


class MotionReportTests(unittest.TestCase):
    def test_wrap_crossings_preserve_turn_direction_and_displacement(self):
        result = summarize(batch([170, -170, -90, 0, 90, 170]))
        self.assertAlmostEqual(result['unwrapped_delta_degrees'], 360, places=4)
        self.assertEqual(result['net_displacement_guest_units'], 25)
        self.assertEqual(result['max_matrix_translation_error'], 0)
        self.assertIn('missed full rotations', result['unwrap_assumption'])

    def test_incomplete_changed_identity_and_bad_times_are_rejected(self):
        original = batch([0, 10])
        for mutate in [lambda b: b.update(completed=False), lambda b: b.update(error='read failed'),
                       lambda b: b['observations'][1].update(player_pointer_after='0x2000'),
                       lambda b: b['observations'][1].update(monotonic=0),
                       lambda b: b['observations'][1].update(player_bytes_hex=''),
                       lambda b: b['observations'][1].update(monotonic=float('nan'))]:
            candidate = copy.deepcopy(original)
            mutate(candidate)
            with self.assertRaises(ValueError):
                summarize(candidate)

    def test_trig_difference_is_reported_without_hiding_it_behind_a_gate(self):
        source = batch([0, 0])
        raw = bytearray.fromhex(source['observations'][1]['player_bytes_hex'])
        struct.pack_into('<f', raw, 0x10, 0.5)
        source['observations'][1]['player_bytes_hex'] = raw.hex()
        result = summarize(source)
        self.assertEqual(result['max_matrix_trig_error'], 0.5)


if __name__ == '__main__':
    unittest.main()

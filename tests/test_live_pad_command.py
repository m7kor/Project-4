import unittest
from tools.diagnostics.live_pad_command import command_text, observed_tick


class LiveCommandTests(unittest.TestCase):
    def test_bounded_native_format_and_overflow(self):
        result = command_text(1, 100, 2, 180, 49151, [255, 0, 12, 34])
        self.assertEqual(result.splitlines()[1], '1,102,282,49151,255,0,12,34')
        for duration in (0, 181):
            with self.assertRaises(ValueError):
                command_text(1, 100, 2, duration, 65535, [128] * 4)
        for sequence, tick, delay, axes in [(0, 0, 2, [128] * 4), (1, 2**64 - 1, 2, [128] * 4),
                                             (1, 0, 121, [128] * 4), (1, 0, 2, [256] * 4)]:
            with self.assertRaises(ValueError):
                command_text(sequence, tick, delay, 1, 65535, axes)

    def test_tick_uses_guest_events_and_recovers_from_partial_state_line(self):
        states = '{"ee_vsync_tick": 100}\n{"ee_vsync_tick": '
        log = '[pad trace] stage=host ee_tick=999\n[pad live] rejected reason=interval sequence=0 tick=120\n'
        self.assertEqual(observed_tick(states, log), 120)
        self.assertEqual(observed_tick(states, '[pad trace] stage=live ee_tick=125\n'), 125)
        with self.assertRaises(ValueError):
            observed_tick('', '[pad wire] host_ms=100')

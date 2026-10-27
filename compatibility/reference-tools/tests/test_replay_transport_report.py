import unittest
from tools.diagnostics.replay_transport_report import report


SOURCE = '[pad trace] stage=replay ms=10 focused=-1 host=0 buttons=65535 lx=255 ly=128 rx=128 ry=128 host_ms=100 ee_tick=9620\n'
WIRE = '[pad wire] host_ms=101 command=66 mode=115 bytes=9 buttons=65535 lx=255 ly=128 rx=128 ry=128\n'


class ReplayTransportTests(unittest.TestCase):
    def test_live_commands_are_distinct_from_startup_replay(self):
        result = report(SOURCE + WIRE + SOURCE.replace('stage=replay', 'stage=live') + WIRE)
        self.assertEqual(result['matching_reply_count'], 2)
        self.assertEqual([event['source'] for event in result['events']], ['replay', 'live'])
    def test_matching_reply_keeps_guest_tick_and_axes(self):
        result = report(SOURCE + WIRE)
        self.assertEqual(result['active_axis_matches'], 1)
        self.assertEqual(result['events'][0]['ee_tick'], 9620)
        self.assertEqual(result['events'][0]['delay_ms'], 1)

    def test_wrong_axis_and_old_or_late_reply_are_not_evidence(self):
        for wire in (WIRE.replace('lx=255', 'lx=128'), WIRE.replace('host_ms=101', 'host_ms=99'),
                     WIRE.replace('host_ms=101', 'host_ms=1101')):
            with self.subTest(wire=wire):
                self.assertEqual(report(SOURCE + wire)['matching_reply_count'], 0)

    def test_reply_before_source_and_physical_input_cannot_prove_replay(self):
        self.assertEqual(report(WIRE + SOURCE)['matching_reply_count'], 0)
        self.assertEqual(report(SOURCE.replace('stage=replay', 'stage=host') + WIRE)['source_events'], 0)

    def test_short_and_digital_polls_are_classified_without_axis_acceptance(self):
        for wire, status in ((WIRE.replace('bytes=9', 'bytes=5'), 'short_poll'),
                             (WIRE.replace('mode=115', 'mode=65'), 'non_analog_mode')):
            result = report(SOURCE + wire)
            self.assertEqual(result['matching_reply_count'], 0)
            self.assertEqual(result['events'][0]['status'], status)

    def test_pressure_mode_is_valid_and_duplicate_reply_counts_once(self):
        wire = WIRE.replace('mode=115 bytes=9', 'mode=121 bytes=21')
        self.assertEqual(report(SOURCE + wire + wire)['matching_reply_count'], 1)

    def test_new_input_does_not_inherit_prior_reply(self):
        changed = SOURCE.replace('lx=255', 'lx=0').replace('host_ms=100', 'host_ms=102').replace('ee_tick=9620', 'ee_tick=9800')
        result = report(SOURCE + WIRE + changed)
        self.assertEqual(result['matching_reply_count'], 1)
        self.assertEqual(result['events'][1]['status'], 'no_matching_reply')

    def test_invalid_input_is_rejected_and_empty_log_proves_nothing(self):
        with self.assertRaises(ValueError):
            report(SOURCE.replace('lx=255', 'lx=256'))
        self.assertEqual(report('')['active_axis_matches'], 0)

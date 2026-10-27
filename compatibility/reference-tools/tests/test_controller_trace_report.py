import unittest
from tools.diagnostics.controller_trace_report import report


class ControllerTraceTests(unittest.TestCase):
    def test_neutral_guest_reads_do_not_prove_controller_working(self):
        result = report('[pad trace] stage=host ms=0 focused=1 host=0 buttons=65535 lx=128 ly=128 rx=128 ry=128\n'
                        '[pad trace] stage=guest ms=20 focused=-1 host=0 buttons=65535 lx=128 ly=128 rx=128 ry=128')
        self.assertTrue(result['controller_detected'])
        self.assertFalse(result['physical_to_guest_observed'])

    def test_matching_actuation_must_follow_host_publication(self):
        result = report('[pad trace] stage=guest ms=5 focused=-1 host=0 buttons=49151 lx=128 ly=128 rx=128 ry=128\n'
                        '[pad trace] stage=host ms=10 focused=1 host=0 buttons=49151 lx=128 ly=128 rx=128 ry=128\n'
                        '[pad trace] stage=guest ms=20 focused=-1 host=0 buttons=49151 lx=128 ly=128 rx=128 ry=128')
        self.assertEqual(len(result['matching_actuated_packets']), 1)
        self.assertTrue(result['physical_to_guest_observed'])

    def test_unfocused_input_not_physical_success(self):
        result = report('[pad trace] stage=host ms=0 focused=0 host=0 buttons=49151 lx=128 ly=128 rx=128 ry=128\n'
                        '[pad trace] stage=guest ms=10 focused=-1 host=0 buttons=49151 lx=128 ly=128 rx=128 ry=128')
        self.assertTrue(result['focus_loss_observed'])
        self.assertFalse(result['physical_to_guest_observed'])

import unittest
from tools.diagnostics.tracy_roundtrip import verify_trace


TRACE = {'traceEvents': [{'ph': 'X', 'name': 'replay', 'ts': 25, 'dur': 100}]}
CSV = 'name,ns_since_start,exec_time_ns\nreplay,0,100000\n'


class TracyRoundtripTests(unittest.TestCase):
    def test_microseconds_to_nanoseconds(self):
        self.assertEqual(verify_trace(TRACE, CSV)['max_error_ns'], 0)

    def test_missing_duplicate_and_wrong_units(self):
        for data in ('name,ns_since_start,exec_time_ns\n', CSV + 'replay,0,100000\n',
                     CSV.replace('100000', '100'), CSV.replace('replay,0', 'replay,500')):
            with self.assertRaises(ValueError):
                verify_trace(TRACE, data)

    def test_empty_or_invalid_measurements(self):
        for value in (0, -1, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                verify_trace({'traceEvents': [dict(TRACE['traceEvents'][0], dur=value)]}, CSV)
        with self.assertRaises(ValueError):
            verify_trace({'traceEvents': []}, CSV)


if __name__ == '__main__':
    unittest.main()

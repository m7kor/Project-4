import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('adma_read_report', Path(__file__).resolve().parents[1] / 'tools/audio/adma_read_report.py')
adma = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adma)


class AdmaReadTests(unittest.TestCase):
    def analyze(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reads.raw'
            path.write_bytes(data)
            return adma.summarize(path)

    def record(self, core=1, dest=0x2400, payload=b'\0' * 512):
        return adma.HEADER.pack(0x524d4441, 1, len(payload), core, 393216, 48000, dest, 0x2000, 0, 1024) + payload

    def test_copy_channels_and_zero_edges(self):
        x = [0] * 96 + [100] * 160
        data = self.record(payload=struct.pack('<256h', *x)) + self.record(dest=0x2600)
        report = self.analyze(data)
        self.assertEqual(report['records'][0]['leading_zero_samples'], 96)
        self.assertEqual(report['records'][0]['copy_seconds'], 1)
        self.assertEqual(report['groups']['1_right']['all_zero_copies'], 1)
        self.assertEqual(report['groups']['1_left']['all_zero_copies'], 0)

    def test_internal_and_boundary_steps_are_separate(self):
        x = [1000] * 96 + [-4000] * 160
        data = self.record(payload=struct.pack('<256h', *x)) + self.record(payload=struct.pack('<256h', *([3000] * 256)))
        group = self.analyze(data)['groups']['1_left']
        self.assertEqual(group['largest_internal_steps'][0]['max_internal_step_offset'], 96)
        self.assertEqual(group['largest_internal_steps'][0]['max_internal_step'], 5000)
        self.assertEqual(group['max_copy_order_boundary_step'], 7000)

    def test_reject_truncation_and_malformed_headers(self):
        for data in (b'', b'ADMR', self.record()[:-1], self.record(core=2), self.record(dest=0x2800),
                     adma.HEADER.pack(0x524d4441, 1, 0xffffffff, 0, 0, 0, 0x2000, 0, 0, 0)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                self.analyze(data)


if __name__ == '__main__':
    unittest.main()

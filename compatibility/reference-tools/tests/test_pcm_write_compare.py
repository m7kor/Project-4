import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pcm_write_compare', Path(__file__).resolve().parents[1] / 'tools/audio/pcm_write_compare.py')
pcm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pcm)


class PcmWriteCompareTests(unittest.TestCase):
    def compare(self, writes, reads, allow_incomplete_tail=False):
        with tempfile.TemporaryDirectory() as directory:
            w, r = Path(directory) / 'writes', Path(directory) / 'reads'
            w.write_bytes(writes)
            r.write_bytes(reads)
            return pcm.compare(w, r, allow_incomplete_tail)

    def read(self, cycle, payload):
        return pcm.READ.pack(0x524d4441, 1, len(payload), 1, cycle, 48000, 0x2400, 0x2000, 0, 1024) + payload

    def test_detect_old_head_and_recent_tail(self):
        header = pcm.WRITE_HEADER.pack(0x5750434d, 1, 0x2000, 512)
        payload = struct.pack('<256h', *([1000] * 96 + [-4000] * 160))
        records = b''.join(pcm.WRITE.pack(100 if i < 192 else 900, 0x2000 + i, 4,
                                         int.from_bytes(payload[i:i + 4], 'little')) for i in range(0, 512, 4))
        result = self.compare(header + records, self.read(1000, payload))
        row = result['records'][0]
        self.assertEqual(result['fully_observed_exact_reads'], 1)
        self.assertEqual(row['write_span_cycles'], 800)
        self.assertEqual(row['first_96_mean_age_cycles'], 900)
        self.assertEqual(row['last_160_mean_age_cycles'], 100)

    def test_mismatch_is_not_an_exact_reconstruction(self):
        header = pcm.WRITE_HEADER.pack(0x5750434d, 1, 0x2000, 4)
        result = self.compare(header + pcm.WRITE.pack(1, 0x2000, 4, 0), self.read(2, b'\1\0\0\0'))
        self.assertEqual(result['exact_reconstructions'], 0)
        self.assertEqual(result['records'][0]['first_mismatch_byte'], 0)

    def test_reject_bad_and_truncated_producer_records(self):
        header = pcm.WRITE_HEADER.pack(0x5750434d, 1, 0x2000, 4)
        for writes in (b'', header + b'x', header + pcm.WRITE.pack(1, 0x2000, 5, 0),
                       header + pcm.WRITE.pack(2, 0x2000, 4, 0) + pcm.WRITE.pack(1, 0x2000, 4, 0)):
            with self.subTest(writes=writes), self.assertRaises(ValueError):
                self.compare(writes, self.read(3, b'\0' * 4))

    def test_explicitly_allow_only_incomplete_final_write(self):
        header = pcm.WRITE_HEADER.pack(0x5750434d, 1, 0x2000, 4)
        result = self.compare(header + pcm.WRITE.pack(1, 0x2000, 4, 0) + b'xyz',
                              self.read(2, b'\0' * 4), True)
        self.assertEqual(result['incomplete_write_tail_bytes'], 3)
        self.assertEqual(result['exact_reconstructions'], 1)
        with self.assertRaises(ValueError):
            self.compare(header + pcm.WRITE.pack(1, 0x2000, 5, 0), self.read(2, b'\0' * 4), True)


if __name__ == '__main__':
    unittest.main()

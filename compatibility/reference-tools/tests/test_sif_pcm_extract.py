import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('sif_pcm_extract', Path(__file__).resolve().parents[1] / 'tools/audio/sif_pcm_extract.py')
sif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sif)


class SifPcmExtractTests(unittest.TestCase):
    def record(self, seq, dest, data, descriptor=0):
        return sif.HEADER.pack(0x50464953, 1, seq, 0x30ee00 if descriptor & 1 else 0x100000, dest, len(data), descriptor, 0) + data

    def descriptor(self, entries):
        return (struct.pack('<4I', len(entries), 0, 0, 0) + b''.join(struct.pack('<4I', *e) for e in entries)).ljust(0x880, b'\0')

    def extract(self, data, ids=(0x50008, 0x5001c)):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sif.raw'; path.write_bytes(data)
            return sif.extract(path, ids)

    def test_descriptor_lengths_exclude_padding_and_separate_channels(self):
        entries = [(0x100, 0x50008, 0x1000, 6), (0x100, 0x5001c, 0x2000, 4)]
        data = self.record(1, 0x1000, b'abcdefPAD!') + self.record(2, 0x2000, b'ghijPAD!')
        data += self.record(3, 0x3000, self.descriptor(entries), 1)
        streams, report = self.extract(data)
        self.assertEqual(streams[0x50008], b'abcdef')
        self.assertEqual(streams[0x5001c], b'ghij')
        self.assertEqual(report['streams']['0x50008']['frames'], 3)

    def test_reject_missing_bytes_broken_packet_and_odd_pcm(self):
        for data in (b'', b'SIFP', self.record(1, 0x1000, b'1234')[:-1],
                     self.record(1, 0x3000, self.descriptor([(0x100, 0x50008, 0x1000, 4)]), 1),
                     self.record(1, 0x1000, b'1234') + self.record(2, 0x3000, self.descriptor([(0x100, 0x50008, 0x1000, 3)]), 1)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                self.extract(data, (0x50008,))

    def test_transport_pair_detects_changed_byte(self):
        data = self.record(1, 0x1000, b'abcd', 2) + self.record(2, 0x1000, b'abXd')
        data += self.record(3, 0x3000, self.descriptor([(0x100, 0x50008, 0x1000, 4)]), 1)
        streams, report = self.extract(data, (0x50008,))
        self.assertEqual(streams[0x50008], b'abXd')
        self.assertEqual(report['transport']['paired_transfers'], 1)
        self.assertEqual(report['transport']['exact_transfers'], 0)
        self.assertEqual(report['transport']['mismatched_bytes'], 1)


if __name__ == '__main__':
    unittest.main()

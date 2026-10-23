import struct
import unittest
from tools.diagnostics.snr2_observed_identity import parse_observation, match_image, unique_image


class ObservedSnr2IdentityTests(unittest.TestCase):
    def fixture(self):
        data = bytearray(128)
        header = [0x32524e53,0,0,0,0,80,60,68,0,0,128,128,0,0,0]
        struct.pack_into('<15I', data, 0, *header)
        data[80:92] = b'fixture.elf\0'
        base = 0x10000
        loaded = header.copy()
        for i in (5,6,7): loaded[i] += base
        loaded[12] = 0x76543210
        line = ('[native-module:untranslated] name=fixture.elf base=0x10000 '
                'target=0x1003c size=0x80 header=' + ','.join(f'{w:x}' for w in loaded))
        return bytes(data), line

    def test_full_immutable_header_and_name_match_with_mutable_loader_link(self):
        data, line = self.fixture()
        observed = parse_observation(line)
        match = match_image(data, observed)
        self.assertTrue(match['header_and_name_match'])
        self.assertFalse(match['runtime_full_image_hash_verified'])
        self.assertFalse(match['fields'][12]['checked'])
        self.assertEqual(match['fields'][12]['observed'], 0x76543210)

    def test_wrong_name_ctor_and_each_immutable_header_field_do_not_match(self):
        data, line = self.fixture()
        observed = parse_observation(line)
        for i in range(15):
            if i == 12: continue
            changed = {**observed, 'header': observed['header'].copy()}
            changed['header'][i] ^= 1
            self.assertIsNone(match_image(data, changed))
        self.assertIsNone(match_image(data, {**observed, 'name': 'different.elf'}))
        self.assertIsNone(match_image(data, {**observed, 'target': observed['target']+4}))

    def test_duplicate_same_image_is_allowed_but_different_content_is_ambiguous(self):
        data, line = self.fixture()
        observed = parse_observation(line)
        match = match_image(data, observed)
        self.assertEqual(unique_image([match, match]), match['source_image_sha256'])
        other = bytearray(data)
        other[100] ^= 1
        with self.assertRaises(ValueError):
            unique_image([match, match_image(bytes(other), observed)])
        with self.assertRaises(ValueError): unique_image([])

    def test_malformed_unreadable_overflow_and_wrong_constructor_are_rejected(self):
        _, line = self.fixture()
        for changed in (line.replace('fixture.elf', '<unreadable>'),
                        line.replace('base=0x10000', 'base=0xfffffff0'),
                        line.replace('target=0x1003c', 'target=0x10040'),
                        line.replace('size=0x80', 'size=0x81'),
                        line + ',100000000', 'bad observation'):
            with self.assertRaises(ValueError): parse_observation(changed)


if __name__ == '__main__':
    unittest.main()

import unittest
from tools.bios_mine.gif_trace import decode


def tag(nloop, flg=0, nreg=1, regs=14):
    return (nloop | (flg << 58) | (nreg << 60)).to_bytes(8, 'little') + regs.to_bytes(8, 'little')


class GifTraceTests(unittest.TestCase):
    def test_prefix_is_not_packet_corruption(self):
        data = tag(2) + bytes(16)
        self.assertEqual(decode(data, 48)['status'], 'prefix-truncated')
        self.assertEqual(decode(data, 32)['status'], 'short-packet')

    def test_reglist_odd_slot_padding_preserves_next_tag(self):
        data = tag(1, flg=1, regs=6) + (123).to_bytes(8, 'little') + bytes(8) + tag(0)
        result = decode(data, len(data))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([t['offset'] for t in result['tags']], [0, 32])
        self.assertEqual(result['tags'][0]['writes'][0]['register'], 6)

    def test_nreg_zero_means_sixteen(self):
        data = tag(1, nreg=0, regs=0xffffffffffffffff) + bytes(256)
        result = decode(data, len(data))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['tags'][0]['writes']), 16)

    def test_packed_rgba_and_ad_layouts_are_distinct(self):
        rgba = (1 | (2 << 32)).to_bytes(8, 'little') + (3 | (128 << 32)).to_bytes(8, 'little')
        ad = (0x11223344).to_bytes(8, 'little') + (0x4c).to_bytes(8, 'little')
        data = tag(1, nreg=2, regs=0xe1) + rgba + ad
        writes = decode(data, len(data))['tags'][0]['writes']
        self.assertEqual(writes[0]['rgba'], [1, 2, 3, 128])
        self.assertEqual(writes[1]['register'], 0x4c)
        self.assertEqual(writes[1]['lo'], '0x11223344')

    def test_image2_size_ignores_nreg(self):
        data = tag(2, flg=3, nreg=0) + bytes(32)
        result = decode(data, len(data))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['tags'][0]['payload_bytes'], 32)
        self.assertEqual(result['tags'][0]['writes'], [])


if __name__ == '__main__':
    unittest.main()

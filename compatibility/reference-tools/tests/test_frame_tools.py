import tempfile
import unittest
from pathlib import Path

from ps2l.diffview import Image, load_image, save_ppm
from ps2l.framecheck import audit_frames
from ps2l.run import summarize_diagnostics

try:
    from PIL import Image as PillowImage
except ImportError:
    PillowImage = None


@unittest.skipIf(PillowImage is None, 'PNG support requires optional Pillow')
class PngComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'frame.png'

    def test_png_and_ppm_decode_to_identical_stored_pixels(self):
        pixels = bytes([0, 0, 0, 255, 1, 17])
        PillowImage.frombytes('RGB', (2, 1), pixels).save(self.path)
        ppm = self.path.with_suffix('.ppm')
        save_ppm(ppm, Image(2, 1, pixels))
        self.assertEqual(load_image(self.path), load_image(ppm))

    def test_nonopaque_png_is_rejected(self):
        PillowImage.new('RGBA', (1, 1), (255, 0, 0, 0)).save(self.path)
        with self.assertRaisesRegex(ValueError, 'non-opaque'):
            load_image(self.path)

    def test_opaque_rgba_is_accepted_without_changing_rgb(self):
        PillowImage.new('RGBA', (1, 1), (12, 34, 56, 255)).save(self.path)
        self.assertEqual(load_image(self.path).rgb, bytes([12, 34, 56]))

    def test_palette_png_is_rejected_instead_of_silent_conversion(self):
        PillowImage.new('P', (1, 1)).save(self.path)
        with self.assertRaisesRegex(ValueError, '8-bit RGB'):
            load_image(self.path)


class FrameAuditTests(unittest.TestCase):
    def test_capture_order_crosses_decimal_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in (9960, 120, 16200, 10080):
                save_ppm(root / f'frame-{index}.ppm', Image(1, 1, b'\1\0\0'))
                (root / f'frame-{index}.png').touch()
            (root / 'frame-unknown.png').touch()
            summary = summarize_diagnostics(root)
            self.assertEqual(summary['latest_captured_frame_file'], 'frame-16200.png')
            self.assertEqual(summary['captured_frame_files'][:4],
                             ['frame-120.png', 'frame-9960.png', 'frame-10080.png', 'frame-16200.png'])
            audit = audit_frames(root)
            self.assertEqual([f['file'] for f in audit['frames']],
                             ['frame-120.ppm', 'frame-9960.ppm', 'frame-10080.ppm', 'frame-16200.ppm'])

    def test_black_frames_and_missing_frames_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(audit_frames(root)['complete'])
            self.assertFalse(audit_frames(root)['all_black'])
            save_ppm(root / 'frame-1.ppm', Image(1, 1, b'\0\0\0'))
            save_ppm(root / 'frame-2.ppm', Image(1, 1, b'\0\0\0'))
            result = audit_frames(root)
            self.assertTrue(result['complete'] and result['all_black'] and result['all_identical'])
            save_ppm(root / 'frame-3.ppm', Image(1, 1, b'\1\0\0'))
            result = audit_frames(root)
            self.assertFalse(result['all_black'] or result['all_identical'])
            self.assertEqual(result['unique_pixel_frames'], 2)
            (root / 'frame-4.ppm').write_bytes(b'corrupt')
            self.assertFalse(audit_frames(root)['complete'])

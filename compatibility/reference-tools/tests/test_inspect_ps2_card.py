import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path
from tools.inspect_ps2_card import inspect_card, main


class CardInspectionTests(unittest.TestCase):
    def test_report_refuses_existing_output_and_card_hardlink(self):
        with tempfile.TemporaryDirectory() as folder:
            card = Path(folder) / 'card.ps2'
            card.write_bytes(b'preserve card bytes')
            report = Path(folder) / 'report.json'
            report.write_text('preserve report')
            with patch('sys.argv', ['inspect', str(card), '--out', str(report)]):
                with self.assertRaises(FileExistsError):
                    main()
            self.assertEqual(report.read_text(), 'preserve report')
            report.unlink()
            os.link(card, report)
            with patch('sys.argv', ['inspect', str(card), '--out', str(report)]):
                with self.assertRaises(FileExistsError):
                    main()
            self.assertEqual(card.read_bytes(), b'preserve card bytes')

    def test_raw_blank_card_is_not_reported_formatted_and_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "card.ps2"
            original = b"\xff" * (528 * 16384)
            path.write_bytes(original)
            report = inspect_card(path)
            self.assertEqual(report["pages"], 16384)
            self.assertEqual(report["spare_bytes_per_page"], 16)
            self.assertEqual(report["erased_pages"], 16384)
            self.assertTrue(report["all_bytes_erased"])
            self.assertFalse(report["format_signature_present"])
            self.assertEqual(path.read_bytes(), original)

    def test_header_does_not_certify_filesystem_or_ecc(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "card.ps2"
            original = bytearray(b"\xff" * (8 * 1024 * 1024))
            signature = b"Sony PS2 Memory Card Format"
            original[:len(signature)] = signature
            path.write_bytes(original)
            report = inspect_card(path)
            self.assertEqual(report["storage_kind"], "data-only")
            self.assertTrue(report["format_signature_present"])
            self.assertEqual(report["filesystem_integrity"], "not-checked")
            self.assertEqual(report["ecc_integrity"], "not-checked")
            self.assertEqual(path.read_bytes(), original)
            path.write_bytes(b"truncated")
            report = inspect_card(path)
            self.assertEqual(report["storage_kind"], "unsupported-size")
            self.assertIsNone(report["pages"])

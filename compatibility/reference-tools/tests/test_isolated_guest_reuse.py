import hashlib
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools.diagnostics.isolated_guest_reuse import checked_private_guest


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrivateGuestReuseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.guest = self.root / 'artifacts/runs/prior/guest'
        (self.guest / 'data').mkdir(parents=True)
        (self.guest / 'saves').mkdir()
        (self.guest / 'saves/private-card.ps2').write_bytes(b'private progress, different from user card')
        rows = []
        for name in ('SLUS_211.34', 'SYSTEM.CNF', 'ioprp.img', 'modules.dat', 'data/asset.afs'):
            path = self.guest / name
            path.write_bytes(name.encode())
            rows.append({'path': name, 'sha256': digest(path)})
        self.manifest = {'files': rows}
        self.run = self.guest.parent / 'captures/run1'
        self.run.mkdir(parents=True)
        (self.run / 'report.json').write_text(json.dumps({'exit_code':124, 'process_exit_observed_unix_ns':1}))
        (self.guest.parent / 'identity.json').write_text(json.dumps({'run':str(self.run)}))

    def check(self):
        return checked_private_guest(self.root, self.guest, self.manifest, digest)

    def test_valid_private_guest_keeps_progress_and_all_input_bytes(self):
        before = {str(p): p.read_bytes() for p in self.guest.rglob('*') if p.is_file()}
        guest, hashes = self.check()
        self.assertEqual(guest, self.guest.resolve())
        self.assertEqual(len(hashes), 5)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.guest.rglob('*') if p.is_file()})

    def test_user_package_is_not_a_reusable_guest(self):
        package = self.root / 'Resident Evil 4'
        package.mkdir()
        with self.assertRaises(ValueError):
            checked_private_guest(self.root, package, self.manifest, digest)

    def test_windows_reparse_root_is_rejected_before_traversal(self):
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)):
            with self.assertRaises(ValueError):
                self.check()

    def test_modified_input_is_not_silently_accepted(self):
        (self.guest / 'data/asset.afs').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.check()

    def test_extra_data_file_is_rejected(self):
        (self.guest / 'data/extra.afs').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            self.check()

    def test_missing_process_exit_is_not_terminal(self):
        (self.run / 'report.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.check()

    def test_report_cannot_escape_original_capture_directory(self):
        other = self.root / 'elsewhere'
        other.mkdir()
        (self.guest.parent / 'identity.json').write_text(json.dumps({'run':str(other)}))
        with self.assertRaises(ValueError):
            self.check()


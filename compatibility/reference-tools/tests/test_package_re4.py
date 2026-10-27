"""Packaging must preserve live destination saves and conflicting game assets."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import package_re4


class LocalPackageTests(unittest.TestCase):
    def _directory(self):
        # Exercise atomic replacement on the workspace filesystem used by the
        # real package, rather than the sandbox's virtualized Windows temp.
        parent = Path(__file__).resolve().parents[1] / 'artifacts/tests'
        parent.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix='re4-package-', dir=parent)

    def setup_root(self, root):
        resolver = patch.object(package_re4, 'runtime_dependencies', return_value=[])
        resolver.start()
        self.addCleanup(resolver.stop)
        source = root / 'game/Resident Evil 4 (USA)'
        source.mkdir(parents=True)
        data = b'original game'
        (source / 'SLUS_211.34').write_bytes(data)
        audit = root / 'artifacts/research/20261007/game-file-preservation-auto-controller.json'
        audit.parent.mkdir(parents=True)
        audit.write_text(json.dumps({'files': [{'path': 'SLUS_211.34', 'sha256': hashlib.sha256(data).hexdigest()}]}))
        for name in ('core/out/build/ps2xRuntime/ps2EntryRunner.exe', 'core/LICENSE',
                     'core/ps2xRuntime/resources/controllers/LICENSE', 'core/deps/raylib/LICENSE',
                     'core/deps/raylib/src/external/glfw/LICENSE.md', 'core/deps/fmt/LICENSE',
                     'dependencies/pcsx2/3rdparty/soundtouch/COPYING.TXT', 'integrations/kzspu2/COPYING.GPLv3',
                     'docs/licenses/runtime-libraries/FFmpeg-LGPL-2.1.txt'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        return source, root / 'Resident Evil 4'

    def test_repackaging_keeps_newer_destination_save(self):
        with self._directory() as directory:
            root = Path(directory)
            source, target = self.setup_root(root)
            saved = source / 'saves/mc0/save.dat'
            saved.parent.mkdir(parents=True)
            saved.write_bytes(b'old source save')
            with patch.object(package_re4, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()):
                package_re4.package()
                current = target / 'saves/mc0/save.dat'
                current.write_bytes(b'new gameplay progress')
                package_re4.package()
            self.assertEqual(current.read_bytes(), b'new gameplay progress')
            self.assertEqual(saved.read_bytes(), b'old source save')
            manifest = json.loads((target / 'package-manifest.json').read_text())
            record = next(r for r in manifest['files'] if Path(r['path']) == Path('saves/mc0/save.dat'))
            self.assertEqual(record['sha256'], hashlib.sha256(current.read_bytes()).hexdigest())

    def test_conflicting_asset_is_not_overwritten(self):
        with self._directory() as directory:
            root = Path(directory)
            source, target = self.setup_root(root)
            target.mkdir()
            (target / 'SLUS_211.34').write_bytes(b'existing different file')
            with patch.object(package_re4, 'ROOT', root), self.assertRaises(RuntimeError):
                package_re4.package()
            self.assertEqual((target / 'SLUS_211.34').read_bytes(), b'existing different file')
            self.assertEqual((source / 'SLUS_211.34').read_bytes(), b'original game')


class RuntimeDependencyTests(unittest.TestCase):
    _directory = LocalPackageTests._directory

    def test_transitive_dependencies_and_cycle(self):
        with self._directory() as directory:
            root = Path(directory)
            exe = root / 'game.exe'
            exe.write_bytes(b'fixture')
            for name in ('avcodec.dll', 'avutil.dll'):
                (root / name).write_bytes(b'fixture')
            outputs = {'game.exe': '  Name: avcodec.dll\n  Name: api-ms-win-crt-runtime-l1-1-0.dll\n',
                       'avcodec.dll': '  Name: avutil.dll\n',
                       'avutil.dll': '  Name: avcodec.dll\n'}
            def inspect(command, **kwargs):
                return type('Result', (), {'stdout': outputs[Path(command[-1]).name]})()
            with patch.object(package_re4.subprocess, 'run', side_effect=inspect):
                result = package_re4.runtime_dependencies(exe, 'inspector', root / 'system')
            self.assertEqual([p.name for p in result], ['avcodec.dll', 'avutil.dll'])

    def test_missing_dependency_rejected(self):
        with self._directory() as directory:
            root = Path(directory)
            exe = root / 'game.exe'
            exe.write_bytes(b'fixture')
            result = type('Result', (), {'stdout': '  Name: missing.dll\n'})()
            with patch.object(package_re4.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(RuntimeError, 'missing.dll'):
                    package_re4.runtime_dependencies(exe, 'inspector', root / 'system')

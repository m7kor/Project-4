from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ps2l import build


class NativeSourceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "recomp/native/SLUS_211.34/re4-native-modules.cpp"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("installer")
        self.generated = self.root / "recomp/generated/SLUS_211.34"
        self.root_patch = patch.object(build, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_default_and_legacy_installer_use_durable_source(self):
        for cached in (None, "", str(self.root / "artifacts/research/20261009/re4-native-modules.cpp")):
            with patch.object(build, "_cached_flag", return_value=cached):
                self.assertEqual(build._native_module_flags(self.generated, None),
                                 [f"PS2_NATIVE_MODULE_SOURCE={self.source.as_posix()}"])

    def test_other_game_does_not_receive_re4_installer(self):
        with patch.object(build, "_cached_flag", return_value=None):
            self.assertEqual(build._native_module_flags(self.root / "other-game", None), [])

    def test_custom_cached_installer_is_preserved(self):
        with patch.object(build, "_cached_flag", return_value=str(self.root / "custom.cpp")):
            self.assertEqual(build._native_module_flags(self.generated, None), [])

    def test_explicit_installer_requires_real_source(self):
        self.assertEqual(build._native_module_flags(self.root / "other-game", self.source),
                         [f"PS2_NATIVE_MODULE_SOURCE={self.source.resolve().as_posix()}"])
        with self.assertRaises(ValueError):
            build._native_module_flags(self.generated, self.root / "missing.cpp")

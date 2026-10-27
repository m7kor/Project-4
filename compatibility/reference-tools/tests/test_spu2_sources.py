import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('spu2_sources', Path(__file__).resolve().parents[1] / 'tools/research/prepare_spu2_sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Spu2SourceSelectionTests(unittest.TestCase):
    def test_rejects_archive_path_escapes(self):
        for path in ('/common/test.h', '../common/test.h', 'common/../../outside.h', 'C:/common/test.h', 'common\\test.h'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.wanted(path)

    def test_keeps_audio_dependency_closure_and_not_other_engines(self):
        for path in ('pcsx2/SPU2/Dma.cpp', 'pcsx2/GS/GSVector4i.h', 'common/Pcsx2Defs.h', '3rdparty/fmt/include/fmt/format.h', 'COPYING.GPLv3'):
            self.assertTrue(module.wanted(path), path)
        for path in ('pcsx2/GS/Renderers/OpenGL/GSRendererOGL.cpp', 'pcsx2/GS/GS.cpp', 'bin/game.iso', 'resources/icons/logo.png', '3rdparty/foo/build/tool.exe'):
            self.assertFalse(module.wanted(path), path)


if __name__ == '__main__':
    unittest.main()

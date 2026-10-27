import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("gs_texture_inspect", Path(__file__).resolve().parents[1] / "tools/diagnostics/gs_texture_inspect.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TextureCaptureTests(unittest.TestCase):
    def fixture(self, path):
        (path / "draw.json").write_text(json.dumps({"schema": 1, "width": 2, "height": 1, "tex0": {"psm": 20}}))
        (path / "vram.bin").write_bytes(bytes(4 * 1024 * 1024))
        (path / "clut-u16le.bin").write_bytes(bytes(1024))
        (path / "texture-rgba.bin").write_bytes(bytes([0,0,0,0,255,255,255,128]))
        (path / "texture-indices.bin").write_bytes(bytes([0,15]))

    def test_preserves_alpha_and_counts_stored_indices(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root); self.fixture(path)
            report, rgba, indices = module.inspect(path)
            self.assertEqual(report["index_histogram"], {0:1, 15:1})
            self.assertEqual(report["distinct_rgba"], 2)
            self.assertEqual(rgba[-1], 128)
            self.assertEqual(indices, bytes([0,15]))

    def test_rejects_truncated_data_and_invalid_indices(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root); self.fixture(path)
            (path / "texture-indices.bin").write_bytes(bytes([0,16]))
            with self.assertRaises(ValueError): module.inspect(path)
            (path / "texture-indices.bin").write_bytes(bytes([0]))
            with self.assertRaises(ValueError): module.inspect(path)
            self.fixture(path)
            (path / "vram.bin").write_bytes(bytes(10))
            with self.assertRaises(ValueError): module.inspect(path)

    def test_rejects_oversized_dimensions(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root); self.fixture(path)
            (path / "draw.json").write_text(json.dumps({"schema":1,"width":1025,"height":1}))
            with self.assertRaises(ValueError): module.inspect(path)

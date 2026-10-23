import struct
import tempfile
try:
    import tomllib
except ImportError:
    import tomli as tomllib
import unittest
from pathlib import Path
from tools.diagnostics.snr2_native_plan import build_plan, write_plan


class Snr2NativePlanTests(unittest.TestCase):
    def fixture(self):
        data = bytearray(0x400)
        header = [0x32524E53, 0, 0, 0, 0, 0, 0x100, 0, 0, 0, 128, len(data), 0, 0x300, 0]
        struct.pack_into('<15I', data, 0, *header)
        struct.pack_into('<4I', data, 0x100, 0x3C080004, 0x2508AF30, 0x03E00008, 0)
        stream = bytes([1]) + struct.pack('<I', 0x100) + bytes([4]) + bytes(5)
        data[0x300:0x300 + len(stream)] = stream
        return data

    def test_relocation_sites_are_selected_only_inside_reviewed_bodies(self):
        plan = build_plan(self.fixture(), [(0x100, 0x110)], 'module_test')
        self.assertEqual(plan['instruction_relocations'], [{'offset': 0x100, 'type': 5}, {'offset': 0x104, 'type': 6}])
        self.assertEqual(build_plan(self.fixture(), [(0x108, 0x110)], 'module_test')['instruction_relocations'], [])

    def test_ranges_opcode_and_missing_delay_slot_reject(self):
        for bodies in ([], [(0x100, 0x10C)], [(0x100, 0x110), (0x104, 0x110)], [(0, 16)], [(0x100, 0x404)]):
            with self.assertRaises(ValueError):
                build_plan(self.fixture(), bodies, 'module_test')
        data = self.fixture()
        struct.pack_into('<I', data, 0x100, 0x24080000)
        with self.assertRaises(ValueError):
            build_plan(data, [(0x100, 0x110)], 'module_test')

    def test_toml_preserves_original_image_and_empty_relocation_array(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / 'module.snr2'
            data = bytes(self.fixture())
            image.write_bytes(data)
            output = image.with_suffix('.toml')
            write_plan(image, [(0x108, 0x110)], 'module_test', output)
            plan = tomllib.loads(output.read_text())
            self.assertEqual(plan['instruction_relocations'], [])
            self.assertEqual(plan['bodies'][0]['start'], 0x108)
            self.assertEqual(image.read_bytes(), data)
            with self.assertRaises(ValueError):
                write_plan(image, [(0x100, 0x110)], 'module_test', image)


if __name__ == '__main__':
    unittest.main()

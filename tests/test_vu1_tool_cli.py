from pathlib import Path
import os
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / 'core/out/build/ps2xTest'
BENCH = BIN / ('ps2x_vu1_bench.exe' if os.name == 'nt' else 'ps2x_vu1_bench')
CODEGEN = BIN / ('ps2x_vu1_codegen.exe' if os.name == 'nt' else 'ps2x_vu1_codegen')


@unittest.skipUnless(BENCH.is_file() and CODEGEN.is_file(), 'build optional VU1 tools to run CLI checks')
class Vu1CliTests(unittest.TestCase):
    def run_tool(self, tool, *args):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PS2X_')}
        return subprocess.run([str(tool), *map(str, args)], env=env, capture_output=True, text=True, timeout=30)

    def test_benchmark_rejects_invalid_options(self):
        for options in (('--no-status', '--repeat', '0'), ('--limit', '-1'), ('--repeat',), ('--wat', '1')):
            with self.subTest(options=options):
                self.assertEqual(self.run_tool(BENCH, ROOT, *options).returncode, 2)

    def test_benchmark_rejects_unbounded_snapshot_before_allocating(self):
        with tempfile.TemporaryDirectory() as directory:
            header = struct.pack('<8IQ', 0x53315556, 1, 0, 0, 0, 664, 0xffffffff, 0xffffffff, 0)
            (Path(directory) / 'vu1snap_00000.bin').write_bytes(header)
            result = self.run_tool(BENCH, directory, '--no-status', '--repeat', '1')
            self.assertEqual(result.returncode, 1)
            self.assertIn('invalid snapshot', result.stderr)

    def test_empty_or_invalid_capture_keeps_existing_generated_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'existing.inc'
            output.write_text('keep me', encoding='utf-8')
            self.assertEqual(self.run_tool(CODEGEN, root, output).returncode, 1)
            self.assertEqual(output.read_text(encoding='utf-8'), 'keep me')
            (root / 'vu1_bad.bin').write_bytes(b'bad')
            self.assertEqual(self.run_tool(CODEGEN, root, output).returncode, 1)
            self.assertEqual(output.read_text(encoding='utf-8'), 'keep me')

    def test_codegen_uses_image_bytes_and_deduplicates_renamed_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = bytes(0x4000)
            for name in ('vu1_0000000000000000.bin', 'vu1_renamed.bin'):
                (root / name).write_bytes(data)
            digest = 0xcbf29ce484222325
            for byte in data:
                digest = ((digest ^ byte) * 0x100000001b3) & 0xffffffffffffffff
            output = root / 'generated.inc'
            result = self.run_tool(CODEGEN, root, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding='utf-8')
            self.assertIn(f'case 0x{digest:016x}ull:', text)
            self.assertEqual(text.count('case 0x'), 1)
            self.assertNotIn('t_renamed', text)

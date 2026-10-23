import unittest
import contextlib
import io
import json
from pathlib import Path
import tempfile
from ps2l.canary import fixture
from ps2l.entrycheck import audit, registration, main


class ObservedEntryTests(unittest.TestCase):
    def test_covered_interior_pc_is_not_automatically_registered(self):
        result = audit({0x1000: 1, 0x1010: 2}, [(0x1000, 0x1020)], {0x1000: 'owner'},
                       '[guest-branch:missing-target] target=0x1010', {})
        self.assertFalse(result['passed'])
        self.assertEqual(result['targets'][0]['status'], 'unregistered-interior-entry')

    def test_registered_interior_pc_requires_executable_resume_label(self):
        trace = '[guest-branch:missing-target] also target=0x1010\n' * 2
        source = '// Address: 0x1000 - 0x1020\ncase 0x1010u: goto resume;\n'
        args = ({0x1010: 2}, [(0x1000, 0x1020)], {0x1010: 'owner'}, trace)
        self.assertFalse(audit(*args, {'owner': source})['passed'])
        result = audit(*args, {'owner': source + 'resume:\n'})
        self.assertTrue(result['passed'])
        self.assertEqual(result['targets'][0]['trace_lines'], [1, 2])

    def test_dispatch_to_wrong_body_is_rejected(self):
        result = audit({0x1010: 2}, [(0x1000, 0x1020)], {0x1010: 'wrong'},
                       '[guest-branch:missing-target] target=0x1010',
                       {'wrong': '// Address: 0x2000 - 0x2020'})
        self.assertEqual(result['targets'][0]['status'], 'registered-body-does-not-own-target')
        self.assertFalse(result['passed'])

    def test_missing_evidence_unaligned_and_absent_code_are_not_success(self):
        self.assertFalse(audit({}, [], {}, 'no faults captured', {})['passed'])
        for target, expected in [('0x1001', 'unaligned-target'), ('0x1000', 'target-not-in-elf-code')]:
            result = audit({}, [], {}, '[guest-branch:missing-target] target=' + target, {})
            self.assertEqual(result['targets'][0]['status'], expected)
            self.assertFalse(result['passed'])

    def test_dense_and_sparse_addresses_are_derived_from_actual_table(self):
        source = '''g_ps2RecompiledFunctionTableBase = 0x1000u;
g_ps2RecompiledFunctionTable[4] = owner; // 0x1010
g_ps2RecompiledFunctionSparseCount = 1u;
g_ps2RecompiledFunctionSparseAddress[1u] = {0x80075000u};
g_ps2RecompiledFunctionSparseTarget[1u] = {kernel};'''
        self.assertEqual(registration(source), {0x1010: 'owner', 0x80075000: 'kernel'})
        with self.assertRaises(ValueError):
            registration(source.replace('// 0x1010', '// 0x1014'))
        with self.assertRaises(ValueError):
            registration(source.replace('SparseCount = 1u', 'SparseCount = 2u'))
        with self.assertRaises(ValueError):
            registration('')

    def test_capture_from_a_different_elf_is_rejected_before_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            elf = root / 'game.elf'
            elf.write_bytes(fixture())
            capture = root / 'capture'
            capture.mkdir()
            (capture / 'report.json').write_text(json.dumps({'elf_sha256': 'stale'}))
            report = root / 'audit.json'
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([str(elf), str(root / 'missing.csv'), str(capture),
                             str(root / 'generated'), '--out', str(report)])
            self.assertEqual(code, 1)
            result = json.loads(report.read_text())
            self.assertFalse(result['passed'])
            self.assertIn('ELF identity differs', result['error'])


if __name__ == '__main__':
    unittest.main()

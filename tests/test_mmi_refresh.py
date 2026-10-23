import struct
import unittest
from tools.diagnostics.refresh_mmi_permutations import refresh


class MmiRefreshTests(unittest.TestCase):
    source = ('// 0x1000: 0x700957c9  prot3w $t2, $t1\n'
              'ctx->pc = 0x1000u;\n'
              'SET_GPR_VEC(ctx, 10, _mm_shuffle_epi32(GPR_VEC(ctx, 9), _MM_SHUFFLE(0,3,2,1)));\n'
              '// 0x1004: 0x00000000 nop\nctx->pc = 0x1004u;\n')

    def test_exact_statement_only_and_idempotence(self):
        fixed, observations, count = refresh(self.source)
        self.assertEqual(count, 1)
        self.assertEqual(fixed, self.source.replace(
            '_mm_shuffle_epi32(GPR_VEC(ctx, 9), _MM_SHUFFLE(0,3,2,1))', 'PS2_PROT3W(GPR_VEC(ctx, 9))'))
        self.assertEqual(observations[0]['rt'], 9)
        self.assertEqual(refresh(fixed)[2], 0)

    def test_original_word_is_checked(self):
        ram = bytearray(0x1008)
        with self.assertRaises(ValueError): refresh(self.source, ram)
        struct.pack_into('<I', ram, 0x1000, 0x700957C9)
        self.assertEqual(refresh(self.source, ram)[2], 1)

    def test_register_mismatch_is_rejected(self):
        with self.assertRaises(ValueError): refresh(self.source.replace('GPR_VEC(ctx, 9)', 'GPR_VEC(ctx, 8)'))

    def test_opcode_mismatch_is_rejected(self):
        with self.assertRaises(ValueError): refresh(self.source.replace('0x700957c9', '0x700957ca'))

    def test_duplicate_statement_is_rejected(self):
        old = 'SET_GPR_VEC(ctx, 10, _mm_shuffle_epi32(GPR_VEC(ctx, 9), _MM_SHUFFLE(0,3,2,1)));'
        with self.assertRaises(ValueError): refresh(self.source.replace(old, old+'\n'+old))

    def test_other_shuffle_is_preserved(self):
        other = '// 0x1008: 0x00000000 nop\n_mm_shuffle_epi32(value, _MM_SHUFFLE(0,3,2,1));\n'
        self.assertTrue(refresh(self.source+other)[0].endswith(other))

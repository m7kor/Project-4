import unittest

from tools.diagnostics.patch_ee_float_semantics import rewrite


def cop1(fd, fs, ft, funct):
    return (0x11 << 26) | (0x10 << 21) | (ft << 16) | (fs << 11) | (fd << 6) | funct


def vu_special(fs, fsf, ft, ftf, funct):
    return (0x25 << 25) | (ftf << 23) | (fsf << 21) | (ft << 16) | (fs << 11) | funct


def shuf(reg, field):
    return f'_mm_cvtss_f32(_mm_shuffle_ps(ctx->vu0_vf[{reg}], ctx->vu0_vf[{reg}], _MM_SHUFFLE(0,0,0,{field})))'


class RewriteTest(unittest.TestCase):
    def test_div(self):
        old = ('if (ctx->f[3] == 0.0f) { ctx->fcr31 |= 0x100000; /* DZ flag */ ctx->f[2] = copysignf(INFINITY, '
               'ctx->f[1] * 0.0f); } else ctx->f[2] = ctx->f[1] / ctx->f[3];')
        self.assertEqual(rewrite(cop1(2, 1, 3, 3), old), 'ctx->f[2] = ps2FpuDivide(ctx->fcr31, ctx->f[1], ctx->f[3]);')
        with self.assertRaises(ValueError):
            rewrite(cop1(2, 3, 1, 3), old)

    def test_sqrt(self):
        self.assertEqual(rewrite(cop1(1, 0, 12, 4), 'ctx->f[1] = FPU_SQRT_S(ctx->f[12]);'),
                         'ctx->f[1] = ps2FpuSqrt(ctx->fcr31, ctx->f[12]);')
        with self.assertRaises(ValueError):
            rewrite(cop1(1, 0, 12, 3), 'ctx->f[1] = FPU_SQRT_S(ctx->f[12]);')

    def test_vdiv(self):
        old = (f'{{ float fs = {shuf(0, 3)}; float ft = {shuf(30, 3)}; '
               'ctx->vu0_q = (ft != 0.0f) ? (fs / ft) : 0.0f; }')
        self.assertIn('ps2VuDivide(ctx->vu0_status, fs, ft)', rewrite(0x4bfe03bc, old))

    def test_vrsqrt_keeps_fs(self):
        old = f'{{ float ft = {shuf(1, 0)}; ctx->vu0_q = (ft > 0.0f) ? (1.0f / sqrtf(ft)) : 0.0f; }}'
        new = rewrite(0x4a6103be, old)
        self.assertIn(shuf(0, 3), new)
        self.assertIn('ps2VuRsqrt(ctx->vu0_status, fs, ft)', new)

    def test_vsqrt(self):
        old = f'{{ float ft = {shuf(22, 0)}; ctx->vu0_q = sqrtf(std::max(0.0f, ft)); }}'
        self.assertEqual(rewrite(vu_special(0, 0, 22, 0, 0x3BD), old),
                         f'{{ float ft = {shuf(22, 0)}; ctx->vu0_q = ps2VuSqrt(ctx->vu0_status, ft); }}')

    def test_other_statement_untouched(self):
        self.assertIsNone(rewrite(cop1(2, 1, 3, 3), 'ctx->pc = 0x100570u;'))


if __name__ == '__main__':
    unittest.main()

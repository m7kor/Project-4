import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('replay_ee_adx', Path(__file__).resolve().parents[1] / 'tools/audio/replay_ee_adx.py')
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class IntegerDecoderReplayTests(unittest.TestCase):
    def cpu(self, words, registers=None):
        ram = bytearray(1024)
        for i, word in enumerate(words):
            struct.pack_into('<I', ram, i * 4, word)
        regs = [[hex(0), hex(0)] for _ in range(32)]
        for reg, value in (registers or {}).items():
            regs[reg][0] = hex(value & replay.MASK64)
        return replay.IntegerEE(ram, {'gpr_hex': regs, 'hi_lo_hex': ['0'] * 4, 'target': 0})

    def test_taken_branch_executes_delay_then_skips_fallthrough(self):
        cpu = self.cpu([0x10000002, 0x24020007, 0x24020009, 0x2403000b])
        for _ in range(3): cpu.step()
        self.assertEqual((cpu.r[2], cpu.r[3], cpu.pc), (7, 11, 16))

    def test_signed_multiply_has_r5900_destination_and_separate_mult1(self):
        # mult $a0,$v0,$v1; mult1 $a1,$v0,$v1
        cpu = self.cpu([(2 << 21) | (3 << 16) | (4 << 11) | 24,
                        (28 << 26) | (2 << 21) | (3 << 16) | (5 << 11) | 24], {2: -3, 3: 7})
        cpu.step()
        self.assertEqual((replay.signed(cpu.r[4], 64), replay.signed(cpu.lo, 64), cpu.hi), (-21, -21, replay.MASK64))
        cpu.lo = 123
        cpu.step()
        self.assertEqual((replay.signed(cpu.r[5], 64), cpu.lo, replay.signed(cpu.lo1, 64)), (-21, 123, -21))

    def test_madd_wraps_64_bits_and_uses_low32_of_hi_lo(self):
        cpu = self.cpu([(28 << 26) | (2 << 21) | (3 << 16) | (4 << 11)], {2: 1, 3: 1})
        cpu.hi = cpu.lo = replay.MASK64
        cpu.step()
        self.assertEqual((cpu.hi, cpu.lo, cpu.r[4]), (0, 0, 0))

    def test_zero_register_and_signed_loads(self):
        cpu = self.cpu([0x2400ffff, (33 << 26) | (2 << 16) | 64, (37 << 26) | (3 << 16) | 64])
        cpu.put(64, 2, 0x8001)
        for _ in range(3): cpu.step()
        self.assertEqual((cpu.r[0], replay.signed(cpu.r[2], 64), cpu.r[3]), (0, -32767, 32769))

    def test_rejects_unknown_instruction_and_device_memory(self):
        cpu = self.cpu([0x44000000])
        with self.assertRaisesRegex(ValueError, 'unsupported opcode'): cpu.step()
        with self.assertRaisesRegex(ValueError, 'unsupported memory'): cpu.get(0x10000000, 4)

    def test_signed_division_truncates_and_handles_overflow_and_zero(self):
        q, r = replay.IntegerEE.divide(-17, 5)
        self.assertEqual((replay.signed(q, 64), replay.signed(r, 64)), (-3, -2))
        self.assertEqual(replay.IntegerEE.divide(17, 0), (replay.MASK64, 17))
        self.assertEqual(replay.IntegerEE.divide(-(1 << 31), -1), ((-(1 << 31)) & replay.MASK64, 0))

    def test_branch_likely_annuls_delay_when_not_taken(self):
        cpu = self.cpu([(20 << 26) | (2 << 21) | 1, 0x24030007, 0x24040009], {2: 1})
        cpu.step(); cpu.step()
        self.assertEqual((cpu.r[3], cpu.r[4], cpu.pc), (0, 9, 12))

    def test_quadword_copy_preserves_both_register_halves(self):
        cpu = self.cpu([(30 << 26) | (2 << 16) | 67, (31 << 26) | (2 << 16) | 99])
        payload = bytes(range(16))
        cpu.ram[64:80] = payload
        cpu.step(); cpu.step()
        self.assertEqual(cpu.ram[96:112], payload)

    def test_bgtz_tests_signed_64_bits_and_executes_delay(self):
        for value, target in ((1, 12), (0, 8), (-1, 8), (1 << 32, 12)):
            with self.subTest(value=value):
                cpu = self.cpu([(7 << 26) | (2 << 21) | 2, 0x24030007], {2: value})
                cpu.step(); cpu.step()
                self.assertEqual((cpu.r[3], cpu.pc), (7, target))

    def test_unaligned_doubleword_pair_all_offsets(self):
        for offset in range(8):
            with self.subTest(offset=offset):
                cpu = self.cpu([(26 << 26) | (2 << 16) | (71+offset),
                                (27 << 26) | (2 << 16) | (64+offset),
                                (44 << 26) | (2 << 16) | (103+offset),
                                (45 << 26) | (2 << 16) | (96+offset)], {2: -1})
                cpu.ram[64:80] = bytes(range(16))
                cpu.ram[96:120] = b'\xaa' * 24
                for _ in range(4): cpu.step()
                self.assertEqual(cpu.ram[96+offset:104+offset], bytes(range(offset, offset+8)))
                self.assertEqual(cpu.ram[96:96+offset], b'\xaa' * offset)
                self.assertEqual(cpu.ram[104+offset:120], b'\xaa' * (16-offset))

    def test_signed_byte_and_bltzl_annul(self):
        cpu = self.cpu([(32 << 26) | (2 << 16) | 64,
                        (1 << 26) | (2 << 21) | (2 << 16) | 2,
                        0x24030007, 0x24030009])
        cpu.ram[64] = 0xff
        cpu.step(); cpu.step(); cpu.step()
        self.assertEqual((replay.signed(cpu.r[2], 64), cpu.r[3], cpu.pc), (-1, 7, 16))


if __name__ == '__main__':
    unittest.main()

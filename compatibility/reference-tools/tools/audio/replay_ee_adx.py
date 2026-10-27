"""Replay the integer-only RE4 ADX call using original EE machine instructions.

Consumes PS2X_CAPTURE_CALL_PREFIX snapshots. This deliberately limited interpreter
rejects unsupported instructions/devices; it is not a general PS2 emulator.
Output is pre-IOP mono PCM at an assumed 48000 Hz, not speaker audio.
"""
import argparse
import json
from pathlib import Path
import struct
import wave

MASK64 = (1 << 64) - 1


def signed(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


class IntegerEE:
    def __init__(self, ram, metadata):
        self.ram = bytearray(ram)
        self.r = [int(pair[0], 16) for pair in metadata['gpr_hex']]
        self.r_upper = [int(pair[1], 16) for pair in metadata['gpr_hex']]
        self.hi, self.lo, self.hi1, self.lo1 = [int(v, 16) for v in metadata['hi_lo_hex']]
        self.pc = metadata['target']
        self.delayed = None
        self.instructions = 0

    def get(self, address, size):
        address &= 0x1fffffff
        if address + size > len(self.ram):
            raise ValueError(f'unsupported memory read 0x{address:x}')
        return int.from_bytes(self.ram[address:address + size], 'little')

    def put(self, address, size, value):
        address &= 0x1fffffff
        if address + size > len(self.ram):
            raise ValueError(f'unsupported memory write 0x{address:x}')
        self.ram[address:address + size] = (value & ((1 << (size * 8)) - 1)).to_bytes(size, 'little')

    def set(self, reg, value, bits=64):
        if reg:
            self.r[reg] = signed(value, bits) & MASK64

    def step(self):
        pc = self.pc
        word = self.get(pc, 4)
        op, rs, rt, rd, sa, fn = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31, (word >> 6) & 31, word & 63
        imm = word & 65535
        simm = signed(imm, 16)
        a, b = self.r[rs], self.r[rt]
        next_pc, old_delay = pc + 4, self.delayed
        self.delayed = None
        supported = True
        if op == 0:
            if fn == 0: self.set(rd, b << sa, 32)
            elif fn == 2: self.set(rd, (b & 0xffffffff) >> sa, 32)
            elif fn == 3: self.set(rd, signed(b, 32) >> sa, 32)
            elif fn == 8: self.delayed = a & 0xffffffff
            elif fn == 9:
                self.set(rd, pc + 8)
                self.delayed = a & 0xffffffff
            elif fn == 10:
                if b == 0: self.set(rd, a)
            elif fn == 11:
                if b != 0: self.set(rd, a)
            elif fn == 16: self.set(rd, self.hi)
            elif fn == 18: self.set(rd, self.lo)
            elif fn == 19: self.lo = a
            elif fn == 24:
                result = signed(a, 32) * signed(b, 32)
                self.lo, self.hi = signed(result, 32) & MASK64, signed(result >> 32, 32) & MASK64
                self.set(rd, result, 32)
            elif fn == 26: self.lo, self.hi = self.divide(a, b)
            elif fn == 33: self.set(rd, a + b, 32)
            elif fn == 35: self.set(rd, a - b, 32)
            elif fn == 36: self.set(rd, a & b)
            elif fn == 37: self.set(rd, a | b)
            elif fn == 38: self.set(rd, a ^ b)
            elif fn == 42: self.set(rd, int(signed(a, 64) < signed(b, 64)))
            elif fn == 43: self.set(rd, int(a < b))
            elif fn == 45: self.set(rd, a + b)
            else: supported = False
        elif op == 28 and fn in (16, 18, 26):
            if fn == 16: self.set(rd, self.hi1)
            elif fn == 18: self.set(rd, self.lo1)
            else: self.lo1, self.hi1 = self.divide(a, b)
        elif op == 28 and fn in (0, 24):
            if fn == 0:
                acc = ((self.hi & 0xffffffff) << 32) | (self.lo & 0xffffffff)
                result = (acc + signed(a, 32) * signed(b, 32)) & MASK64
                self.lo, self.hi = signed(result, 32) & MASK64, signed(result >> 32, 32) & MASK64
            else:
                result = signed(a, 32) * signed(b, 32)
                self.lo1, self.hi1 = signed(result, 32) & MASK64, signed(result >> 32, 32) & MASK64
            self.set(rd, result, 32)
        elif op in (2, 3):
            if op == 3: self.set(31, pc + 8)
            self.delayed = ((pc + 4) & 0xf0000000) | ((word & 0x3ffffff) << 2)
        elif op in (1, 4, 5, 6, 7, 20, 21, 22, 23):
            if op == 1:
                if rt not in (0, 1, 2, 3): supported = False
                condition = signed(a, 64) >= 0 if rt & 1 else signed(a, 64) < 0
            elif op in (4, 20): condition = a == b
            elif op in (5, 21): condition = a != b
            elif op in (6, 22): condition = signed(a, 64) <= 0
            else: condition = signed(a, 64) > 0
            if (op >= 20 or (op == 1 and rt in (2, 3))) and not condition:
                next_pc = pc + 8
            else:
                self.delayed = pc + 4 + simm * 4 if condition else pc + 8
        elif op == 9: self.set(rt, a + simm, 32)
        elif op == 10: self.set(rt, int(signed(a, 64) < simm))
        elif op == 11: self.set(rt, int(a < (simm & MASK64)))
        elif op == 12: self.set(rt, a & imm)
        elif op == 13: self.set(rt, a | imm)
        elif op == 14: self.set(rt, a ^ imm)
        elif op == 15: self.set(rt, imm << 16, 32)
        elif op in (32, 33, 35, 36, 37, 55):
            size = {32: 1, 33: 2, 35: 4, 36: 1, 37: 2, 55: 8}[op]
            value = self.get(a + simm, size)
            if op in (36, 37): self.set(rt, value)
            else: self.set(rt, value, size * 8)
        elif op in (26, 27, 44, 45):
            address = (a + simm) & 0xffffffff
            offset, base = address & 7, address & ~7
            memory = bytearray(self.get(base, 8).to_bytes(8, 'little'))
            register = bytearray(b.to_bytes(8, 'little'))
            if op == 26:  # LDL: memory prefix to register suffix
                register[7-offset:] = memory[:offset+1]
            elif op == 27:  # LDR: memory suffix to register prefix
                register[:8-offset] = memory[offset:]
            elif op == 44: memory[:offset+1] = register[7-offset:]
            else: memory[offset:] = register[:8-offset]
            if op in (26, 27): self.set(rt, int.from_bytes(register, 'little'))
            else: self.put(base, 8, int.from_bytes(memory, 'little'))
        elif op in (30, 31):
            address = (a + simm) & ~15
            if op == 30:
                value = self.get(address, 16)
                if rt:
                    self.r[rt], self.r_upper[rt] = value & MASK64, value >> 64
            else:
                self.put(address, 16, b | (self.r_upper[rt] << 64))
        elif op in (40, 41, 43, 63):
            self.put(a + simm, {40: 1, 41: 2, 43: 4, 63: 8}[op], b)
        else: supported = False
        if not supported:
            raise ValueError(f'unsupported opcode 0x{word:08x} at 0x{pc:x}')
        if old_delay is not None and self.delayed is not None:
            raise ValueError('branch in delay slot is unsupported')
        self.pc = old_delay if old_delay is not None else next_pc
        self.instructions += 1

    @staticmethod
    def divide(a, b):
        a, b = signed(a, 32), signed(b, 32)
        if b == 0:
            return (1 if a < 0 else MASK64), a & MASK64
        if a == -(1 << 31) and b == -1:
            return a & MASK64, 0
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0): q = -q
        return q & MASK64, (a - q * b) & MASK64


def replay(prefix, out, limit=10000000):
    prefix, out = Path(prefix), Path(out)
    metadata = json.loads(Path(str(prefix) + '.json').read_text())
    ram = Path(str(prefix) + '.ram.bin').read_bytes()
    if metadata['schema'] != 1 or metadata['ram_bytes'] != len(ram) or len(metadata['gpr_hex']) != 32:
        raise ValueError('invalid snapshot')
    if metadata['target'] != 0x19b1f8:
        raise ValueError('this extraction layout is only verified for RE4 call 0x19b1f8')
    cpu = IntegerEE(ram, metadata)
    return_pc = cpu.r[31] & 0xffffffff
    input_address = cpu.r[4] & 0x1fffffff
    blocks = signed(cpu.r[5], 32)
    frames = (blocks // 2) * 32
    addresses = [cpu.r[6] & 0x1fffffff, cpu.r[8] & 0x1fffffff]
    if blocks <= 0 or blocks > 65536 or any(p + frames * 2 > len(ram) for p in addresses):
        raise ValueError('invalid ADX call bounds')
    while cpu.pc != return_pc:
        if cpu.instructions >= limit:
            raise ValueError('instruction limit reached')
        cpu.step()
    outputs = []
    for channel, address in enumerate(addresses):
        path = Path(str(out) + f'-ch{channel}.wav')
        if path.exists():
            raise FileExistsError(path)
        with wave.open(str(path), 'wb') as sink:
            sink.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            sink.writeframes(cpu.ram[address:address + frames * 2])
        outputs.append(str(path))
    result = {'schema': 1, 'snapshot': str(prefix), 'target': metadata['target'],
              'instructions': cpu.instructions, 'input_address': input_address, 'blocks': blocks,
              'frames_per_channel': frames, 'output_addresses': addresses, 'return_value': signed(cpu.r[2], 32),
              'outputs': outputs, 'sample_rate_assumption': 48000,
              'scope': 'Original integer instructions; no scheduler, devices, FPU or VU. Not speaker audio.'}
    Path(str(out) + '.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.prefix, args.out), indent=2))

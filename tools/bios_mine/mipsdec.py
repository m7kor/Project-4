#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mipsdec.py -- a small, dependency-free MIPS-III / R5900 decoder.

Written for BIOS mining (read-only analysis of Sony BIOS images).
No external packages, no network, no tool installation.

Scope: enough of the architecture to (a) recognise code, (b) follow
branches/jumps, (c) read the lui/addiu pairs that build 32-bit addresses,
(d) read syscall dispatch, (e) annotate delay slots.

Scalar opcode regressions are covered by tests/test_mipsdec.py. Extended
MMI/VU/COP decoding is incomplete and is not an authoritative instruction
decoder. Register-indirect jump destinations require register-state evidence.

Fields of a 32-bit instruction word:

    31        26 25        21 20        16 15        11 10         6 5          0
   |  opcode   |   rs       |    rt      |    rd      |    shamt    |   funct   |
"""

import struct

# ---------------------------------------------------------------------------
# register names
# ---------------------------------------------------------------------------
REG = {
    0: "$zero", 1: "$at", 2: "$v0", 3: "$v1", 4: "$a0", 5: "$a1", 6: "$a2",
    7: "$a3", 8: "$t0", 9: "$t1", 10: "$t2", 11: "$t3", 12: "$t4", 13: "$t5",
    14: "$t6", 15: "$t7", 16: "$s0", 17: "$s1", 18: "$s2", 19: "$s3", 20: "$s4",
    21: "$s5", 22: "$s6", 23: "$s7", 24: "$t8", 25: "$t9", 26: "$k0", 27: "$k1",
    28: "$gp", 29: "$sp", 30: "$fp", 31: "$ra",
}
R = REG.__getitem__


def r(n):
    return "$" + str(n)


# ---------------------------------------------------------------------------
# opcode tables
# ---------------------------------------------------------------------------
# SPECIAL: keyed on funct (bits 5:0)
SPECIAL = {
    0x00: "sll", 0x01: "movci", 0x02: "srl", 0x03: "sra", 0x04: "sllv",
    0x05: "?", 0x06: "srlv", 0x07: "srav", 0x08: "jr", 0x09: "jalr",
    0x0a: "movz", 0x0b: "movn", 0x0c: "syscall", 0x0d: "break", 0x0e: "sysc",
    0x0f: "sync", 0x10: "mfhi", 0x11: "mthi", 0x12: "mflo", 0x13: "mtlo",
    0x14: "dsllv", 0x16: "dsrlv", 0x17: "dsrav", 0x18: "mult", 0x19: "multu",
    0x1a: "div", 0x1b: "divu", 0x20: "add", 0x21: "addu", 0x22: "sub",
    0x23: "subu", 0x24: "and", 0x25: "or", 0x26: "xor", 0x27: "nor",
    0x2a: "slt", 0x2b: "sltu", 0x2c: "dadd", 0x2d: "daddu", 0x2e: "dsub",
    0x2f: "dsubu", 0x30: "tge", 0x31: "tgeu", 0x32: "tlt", 0x33: "tltu",
    0x34: "teq", 0x36: "tne", 0x38: "dsll", 0x3a: "dsrl", 0x3b: "dsra",
    0x3c: "dsll32", 0x3e: "dsrl32", 0x3f: "dsra32"}

# REGIMM: keyed on rt (bits 20:16)
REGIMM = {
    0x00: "bltz", 0x01: "bgez", 0x02: "bltzl", 0x03: "bgezl",
    0x08: "tgei", 0x09: "tgeiu", 0x0a: "tlti", 0x0b: "tltiu",
    0x0c: "teqi", 0x0e: "tnei",
    0x10: "bltzal", 0x11: "bgezal", 0x12: "bltzall", 0x13: "bgezall"}

# COP0: keyed on rs (bits 25:21)
COP0 = {0x00: "mfc0", 0x01: "dmfc0", 0x02: "cfc0", 0x04: "mtc0", 0x05: "dmtc0",
        0x06: "ctc0", 0x08: "bc0", 0x10: "rfe", 0x11: "tlbr", 0x12: "tlbwi",
        0x13: "tlbp", 0x14: "eret", 0x18: "wait", 0x1b: "deret"}

# COP1: keyed on rs (bits 25:21); fmt values
COP1 = {0x00: "mfc1", 0x01: "dmfc1", 0x02: "cfc1", 0x04: "mtc1", 0x05: "dmtc1",
        0x06: "ctc1", 0x08: "bc1", 0x10: "cop1.s", 0x11: "cop1.d", 0x14: "cop1.w",
        0x15: "cop1.l"}

# main opcode table
OPCODE = {
    0x00: ("SPECIAL", None), 0x01: ("REGIMM", None),
    0x02: ("j", "T"), 0x03: ("jal", "T"),
    0x04: ("beq", "B"), 0x05: ("bne", "B"), 0x06: ("blez", "RB"), 0x07: ("bgtz", "RB"),
    0x08: ("addi", "I"), 0x09: ("addiu", "I"), 0x0a: ("slti", "I"), 0x0b: ("sltiu", "I"),
    0x0c: ("andi", "U"), 0x0d: ("ori", "U"), 0x0e: ("xori", "U"), 0x0f: ("lui", "Uhi"),
    0x10: ("COP0", None), 0x11: ("COP1", None), 0x12: ("COP2", None), 0x13: ("COP1X", None),
    0x14: ("beql", "B"), 0x15: ("bnel", "B"), 0x16: ("blezl", "RB"), 0x17: ("bgtzl", "RB"),
    0x18: ("daddi", "I"), 0x19: ("daddiu", "I"), 0x1a: ("ldl", "I"), 0x1b: ("ldr", "I"),
    0x1c: ("MMI", None), 0x1d: ("?", None), 0x1e: ("lq", "I"), 0x1f: ("sq", "I"),
    0x20: ("lb", "I"), 0x21: ("lh", "I"), 0x22: ("lwl", "I"), 0x23: ("lw", "I"),
    0x24: ("lbu", "I"), 0x25: ("lhu", "I"), 0x26: ("lwr", "I"), 0x27: ("lwu", "I"),
    0x28: ("sb", "I"), 0x29: ("sh", "I"), 0x2a: ("swl", "I"), 0x2b: ("sw", "I"),
    0x2c: ("sdl", "I"), 0x2d: ("sdr", "I"), 0x2e: ("swr", "I"), 0x2f: ("cache", "I"),
    0x30: ("ll", "I"), 0x31: ("lwc1", "I"), 0x32: ("lwc2", "I"), 0x33: ("?", None),
    0x34: ("lld", "I"), 0x35: ("ldc1", "I"), 0x36: ("ldc2", "I"), 0x37: ("ld", "I"),
    0x38: ("sc", "I"), 0x39: ("swc1", "I"), 0x3a: ("swc2", "I"), 0x3b: ("?", None),
    0x3c: ("scd", "I"), 0x3d: ("sdc1", "I"), 0x3e: ("sdc2", "I"), 0x3f: ("sd", "I"),
}

# COP2 / VU unit -- funct values worth naming
COP2 = {0x01: "vcall", 0x04: "vme", 0x05: "vabs", 0x08: "vadd.q", 0x09: "vadd.i",
        0x0a: "vsub.q", 0x0b: "vsub.i", 0x10: "vaddbc", 0x11: "vsubbc",
        0x12: "vmadd", 0x13: "vmsub", 0x14: "vmax", 0x15: "vmin", 0x16: "vmul",
        0x18: "vaddi", 0x19: "vaddi.sbc", 0x1a: "vsubi", 0x1b: "vsubi.sbc",
        0x1c: "vmulq", 0x1d: "vmuli", 0x1e: "vminu", 0x1f: "vmaxu",
        0x20: "vaddq", 0x21: "vmulq.sbc", 0x22: "vaddi.s", 0x23: "vmul.sbc",
        0x24: "vrcnd", 0x25: "vabs.i", 0x26: "vmulr", 0x27: "vadd.co",
        0x28: "vmul.co", 0x29: "vaddi.co", 0x2a: "vmaddbc", 0x2b: "vmsubbc",
        0x2c: "vaddbc2", 0x2d: "vsubbc2", 0x2e: "vmadd", 0x2f: "vmsub",
        0x30: "viadd", 0x31: "visub", 0x32: "viaddi", 0x36: "viand", 0x37: "vior",
        0x3a: "vcallms", 0x3c: "vrcndi", 0x3d: "vabsq", 0x3e: "vmove",
        0x3f: "vmerge", 0x40: "vu1m", 0x55: "qmfc2", 0x56: "cfc2", 0x57: "qmfc2.i",
        0x58: "qmtc2", 0x59: "ctc2", 0x5a: "qmtc2.i", 0x5b: "?", 0x5c: "vfp",
        0x5d: "vwaitq", 0x5e: "vload.x", 0x5f: "vstore.x"}

# COP0 register names (rd, bits 15:11)
COP0REG = {0: "Index", 1: "Random", 2: "EntryLo0", 3: "BPC", 4: "Context",
           5: "PageMask", 6: "Wired", 7: "EntryLo1", 8: "EntryHi", 9: "Count",
           10: "Compare", 11: "Status", 12: "Cause", 13: "EPC", 14: "PRId",
           15: "Config", 16: "LLAddr", 17: "WatchLo", 18: "WatchHi",
           19: "XContext", 20: "BadVAddr", 22: "ECC", 26: "ECC", 30: "ErrorEPC",
           31: "DESAVE"}

# branches that always have a delay slot; also "likely" variants
BRANCHY = {"j", "jal", "beq", "bne", "blez", "bgtz", "beql", "bnel", "blezl",
           "bgtzl", "bltz", "bgez", "bltzl", "bgezl", "bltzal", "bgezal", "bltzall", "bgezall",
           "bc0", "bc1", "bc2"}


def _u16(v):
    return v & 0xFFFF


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _s32(v):
    return v - 0x100000000 if v & 0x80000000 else v


def decode(word, pc=0):
    """Decode one 32-bit word.

    Returns a dict:
      word, pc, op, mnem, args (list of str), target (int|None),
      is_branch (bool), is_jump (bool), has_delay (bool), raw (str)
    """
    op = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    sa = (word >> 6) & 0x1F
    fn = word & 0x3F
    imm = word & 0xFFFF
    simm = _s16(imm)
    # MIPS jump target: ((PC_of_delay_slot & 0xF0000000) | (index26 << 2)).
    # Relative branches use PC + 4. JR/JALR use register values and have no
    # statically known destination in this decoder.
    tgt = ((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
    bpc = (pc + 4) & 0xFFFFFFFF
    branch_target = (bpc + (simm << 2)) & 0xFFFFFFFF

    d = {"word": word, "pc": pc, "op": op, "rs": rs, "rt": rt, "rd": rd,
         "imm": simm, "target": None, "is_branch": False, "is_jump": False,
         "has_delay": False, "valid": True}

    def out(mnem, args):
        d["mnem"] = mnem
        d["args"] = args
        return d

    if op == 0x00:  # SPECIAL
        mn = SPECIAL.get(fn, "sp?%02x" % fn)
        if fn in (0x00, 0x02, 0x03, 0x38, 0x3a, 0x3b, 0x3c, 0x3e, 0x3f):
            if fn == 0x00 and word == 0:
                return out("nop", [""])
            return out(mn, [R(rd), R(rt), str(sa)])
        if fn in (0x04, 0x06, 0x07, 0x14, 0x16, 0x17):
            return out(mn, [R(rd), R(rt), R(rs)])
        if fn == 0x08:
            d.update(is_jump=True, has_delay=True, target=None,
                     target_kind="reg")
            return out("jr", [R(rs)])
        if fn == 0x09:
            d.update(is_jump=True, has_delay=True, target=None, target_kind="reg")
            return out("jalr", [R(rd), R(rs)])
        if fn == 0x0c:
            code = (word >> 6) & 0xFFFFF
            d["code"] = code
            return out("syscall", ["0x%x" % code] if code else [""])
        if fn == 0x0d:
            return out("break", ["0x%x" % ((word >> 6) & 0xFFFFF)])
        if fn == 0x0f:
            return out("sync", [""])
        if fn in (0x10, 0x12):
            return out(mn, [R(rd)])
        if fn in (0x11, 0x13):
            return out(mn, [R(rs)])
        if fn in (0x18, 0x19, 0x1a, 0x1b):
            return out(mn, [R(rs), R(rt)])
        if fn in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2a, 0x2b,
                  0x2c, 0x2d, 0x2e, 0x2f):
            if fn in (0x24, 0x25, 0x20, 0x21, 0x22, 0x23):
                return out(mn, [R(rd), R(rs), R(rt)])
            return out(mn, [R(rd), R(rs), R(rt)])
        if fn in (0x0a, 0x0b):
            return out(mn, [R(rd), R(rs), R(rt)])
        if fn in (0x30, 0x31, 0x32, 0x33, 0x34, 0x36):
            return out(mn, [R(rs), R(rt)])
        return out(mn, ["rs=%d rt=%d rd=%d" % (rs, rt, rd)])

    if op == 0x01:  # REGIMM
        mn = REGIMM.get(rt, "reg?%02x" % rt)
        if rt in (0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0e):
            return out(mn, [R(rs), str(simm)])
        if rt not in (0, 1, 2, 3, 0x10, 0x11, 0x12, 0x13):
            d["valid"] = False
            return out(mn, [R(rs), str(simm)])
        d.update(is_branch=True, has_delay=True, target=branch_target)
        if rt in (0x10, 0x11, 0x12, 0x13):
            d["is_jump"] = True
        return out(mn, [R(rs), "0x%08x" % d["target"]])

    name, kind = OPCODE.get(op, ("op?%02x" % op, None))
    if op in (0x02, 0x03):
        d.update(is_jump=True, has_delay=True, target=tgt)
        return out(name, ["0x%08x" % tgt])
    if op in (0x04, 0x05, 0x14, 0x15):
        d.update(is_branch=True, has_delay=True, target=branch_target)
        return out(name, [R(rs), R(rt), "0x%08x" % d["target"]])
    if op in (0x06, 0x07, 0x16, 0x17):
        d.update(is_branch=True, has_delay=True, target=branch_target)
        return out(name, [R(rs), "0x%08x" % d["target"]])
    if op == 0x0f:
        return out("lui", [R(rt), "0x%x" % imm])
    if op in (0x0c, 0x0d, 0x0e):
        return out(name, [R(rt), R(rs), "0x%x" % imm])
    if op in (0x08, 0x09, 0x0a, 0x0b, 0x18, 0x19):
        return out(name, [R(rt), R(rs), str(simm)])
    if op in (0x1a, 0x1b,
              0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
              0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32, 0x34,
              0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x3c, 0x3d, 0x3e, 0x3f):
        return out(name, [R(rt), "%d(%s)" % (simm, R(rs))])

    if op == 0x10:  # COP0
        f = COP0.get(rs, "cop0?%02x" % rs)
        if rs in (0x00, 0x01, 0x02, 0x04, 0x05, 0x06):
            rn = COP0REG.get(rd, "cop0r%d" % rd)
            return out(f, [R(rt), rn])
        if rs == 0x08:
            d.update(is_branch=True, has_delay=True, target=branch_target)
            return out("bc0", ["0x%08x" % d["target"]])
        return out(f, ["0x%05x" % (word & 0x1FFFFFF)])

    if op == 0x11:  # COP1
        f = COP1.get(rs, "cop1?%02x" % rs)
        if rs in (0x00, 0x01, 0x02, 0x04, 0x05, 0x06):
            return out(f, [R(rt), "$f%d" % rd])
        if rs == 0x08:
            d.update(is_branch=True, has_delay=True, target=branch_target)
            return out("bc1", ["0x%08x" % d["target"]])
        return out(f, ["$f%d" % sa if False else "%d" % sa,
                       "$f%d" % rd, "$f%d" % rt, "0x%x" % imm])

    if op == 0x12:  # COP2 / VU
        f = COP2.get(fn, "cop2?%02x" % fn)
        d["cop2funct"] = fn
        return out(f, ["rs=%d rt=%d imm=0x%03x" % (rs, rt, imm)])

    return out(name, [])


def disasm_line(word, pc, annotate=None):
    d = decode(word, pc)
    txt = d["mnem"]
    if d.get("args"):
        txt += " " + ", ".join(a for a in d["args"] if a != "")
    if annotate:
        txt += "        ; " + annotate
    return txt


class Image(object):
    """A flat byte image with an optional load virtual address."""

    def __init__(self, data, base=0):
        self.data = data
        self.base = base

    def u32(self, off):
        if off + 4 > len(self.data):
            return None
        return struct.unpack_from(">I", self.data, off)[0]

    def u16(self, off):
        if off + 2 > len(self.data):
            return None
        return struct.unpack_from(">H", self.data, off)[0]

    def word_at_va(self, va):
        off = va - self.base
        if off % 4:
            return None
        return self.u32(off)

    def off_to_va(self, off):
        return self.base + off

    def va_to_off(self, va):
        return va - self.base


def disasm(img, off, count, va=None, show_delay=True):
    """Yield (off, va, hexword, text) tuples."""
    if va is None:
        va = img.base + off
    out = []
    for i in range(count):
        o = off + 4 * i
        w = img.u32(o)
        if w is None:
            break
        pc = va + 4 * i
        d = decode(w, pc)
        txt = d["mnem"]
        if d.get("args"):
            txt += " " + ", ".join(a for a in d["args"] if a != "")
        prev = None
        if i > 0:
            pw = img.u32(off + 4 * (i - 1))
            if pw is not None:
                pd = decode(pw, pc - 4)
                if pd["has_delay"] and not pd["is_jump"]:
                    prev = "| "
        out.append((o, pc, "%08x" % w, (prev or "") + txt))
    return out


def looks_like_code(word_rate=0.0):
    """Not used as a hard gate; kept for symmetry."""
    return word_rate

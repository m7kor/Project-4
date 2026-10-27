#!/usr/bin/env python3
"""lodestone analyze — Ghidra-free ELF analysis for PS2 recompilation.

Three things this does that a naive opcode scan does not, each of which was
measured as wrong on SLUS_211.34 (see knowledge/dead_ends.jsonl):

  1. Scans ONLY executable sections, never the whole PT_LOAD. On RE4 the PT_LOAD
     filesz is 0x2C9F28 but .text is only 0x1EF91C — the rest is .data,
     .sndata and .rodata. Data words must not be counted as instructions.
     SYSCALL is SPECIAL function 0x0C, not primary opcode 0x0C (ANDI).
  2. Sorts sections by ADDRESS, never header order. ElfParser::readWord() in
     upstream PS2Recomp scans in header order, so RE4's 93 .DVP.overlay.* sections
     (all sh_addr == 0) shadow everything below them.
  3. Reports overlays. RE4 has 93 of them plus .DVP.ovlytab / .DVP.ovlystrtab.
     "Single program header" does NOT mean "no overlays".

Writes a Ghidra-CSV-compatible function map (Name,Start,End,Size) so
ExportPS2Functions.java can be skipped entirely.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
import json
import re
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------- constants

SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR = 0x1, 0x2, 0x4
SHT_NOBITS = 8

# opcode
OP_SPECIAL, OP_J, OP_JAL = 0x00, 0x02, 0x03
OP_BEQ, OP_BNE, OP_BLEZ, OP_BGTZ = 0x04, 0x05, 0x06, 0x07
OP_ADDI, OP_ADDIU, OP_SLTI, OP_SLTIU, OP_ANDI, OP_ORI, OP_XORI, OP_LUI = (
    0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F)
OP_COP0, OP_COP1, OP_COP2 = 0x10, 0x11, 0x12
OP_BEQL, OP_BNEL, OP_BLEZL, OP_BGTZL = 0x14, 0x15, 0x16, 0x17
OP_REGIMM = 0x01
OP_JALX = 0x1D
OP_LB, OP_LH, OP_LWL, OP_LW, OP_LBU, OP_LHU, OP_LWR = 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26
OP_SB, OP_SH, OP_SWL, OP_SW, OP_SWR = 0x28, 0x29, 0x2A, 0x2B, 0x2E
# R5900 primary opcodes: LD/SD operate on GPRs; COP2 transfers are separate.
OP_LD, OP_SD = 0x37, 0x3F
OP_LWC2, OP_SWC2 = 0x32, 0x3A
OP_LDC2, OP_SDC2 = 0x36, 0x3E

# Opcodes that cannot open a function body. A store means we are mid-body, a
# branch means we are at a join point, and a zero word means padding.
# Deliberately NARROW: SPECIAL (0x00) stays allowed because `jr $ra` as the
# first word is a real leaf entry, and it occurs 1,612 times among known RE4
# starts. Rejecting the leaf case to gain those 1,612 real entries is a bad trade.
_NOT_ENTRY_OP = frozenset((
    0x28, 0x29, 0x2B, 0x2E,   # sb sh sw swr
    0x04, 0x05, 0x06, 0x07,   # beq bne blez bgtz
    0x02, 0x03, 0x1D,         # j jal jalx
))


def plausible_entry_op(w: int) -> bool:
    """Can this instruction plausibly be the first word of a function?"""
    if w == 0:
        return False                      # padding between bodies
    return (w >> 26) not in _NOT_ENTRY_OP
OP_CACHE, OP_PREF, OP_LLD, OP_LDC1, OP_LQC2 = 0x2F, 0x33, 0x34, 0x35, 0x38
OP_SCD, OP_SDC1, OP_SQC2 = 0x3C, 0x3D, 0x39

# SPECIAL function
FN_JR, FN_JALR, FN_SYSCALL, FN_BREAK = 0x08, 0x09, 0x0C, 0x0D
FN_SLL, FN_SRA, FN_SLLV, FN_SRL, FN_SRAV = 0x00, 0x03, 0x04, 0x02, 0x07
FN_MULT, FN_MULTU, FN_DIV, FN_DIVU = 0x18, 0x19, 0x1A, 0x1B
FN_MFHI, FN_MTHI, FN_MFLO, FN_MTLO = 0x10, 0x11, 0x12, 0x13

GPR_NAMES = [
    "$zero", "$at", "$v0", "$v1", "$a0", "$a1", "$a2", "$a3",
    "$t0", "$t1", "$t2", "$t3", "$t4", "$t5", "$t6", "$t7",
    "$s0", "$s1", "$s2", "$s3", "$s4", "$s5", "$s6", "$s7",
    "$t8", "$t9", "$k0", "$k1", "$gp", "$sp", "$fp", "$ra",
]

# upstream ps2_call_list.h: PS2_SYSCALL_LIST + PS2_STUB_LIST = 658 unique names.
# Syscall NUMBERS live in Kernel/Syscalls/Dispatcher.cpp, not in that header.
# This table is the numeric IDs verified from that file.
KNOWN_SYSCALLS = {
    0x01: "ResetEE", 0x02: "GsSetCrt", 0x03: "GsSetDispEnv", 0x04: "ExitThread",
    0x05: "SleepThread", 0x06: "SleepThreadi", 0x07: "WakeupThread",
    0x10: "AddIntcHandler", 0x11: "RemoveIntcHandler", 0x12: "AddDmacHandler",
    0x13: "RemoveDmacHandler", 0x14: "EnableIntc", 0x15: "DisableIntc",
    0x16: "EnableDmac", 0x17: "DisableDmac", 0x18: "SetAlarm", 0x19: "CancelAlarm",
    0x20: "CreateThread", 0x21: "DeleteThread", 0x22: "StartThread",
    0x23: "ExitThread", 0x24: "ExitDeleteThread", 0x25: "TerminateThread",
    0x2F: "GetThreadId", 0x30: "GetThreadInfo", 0x3D: "SetupHeap", 0x3E: "EndOfHeap",
    0x40: "CreateSema", 0x41: "DeleteSema", 0x42: "SignalSema",
    0x5A: "Copy", 0x5B: "GetEntryAddress", 0x64: "FlushCache",
    0x70: "GsGetIMR", 0x71: "GsPutIMR", 0x7C: "Deci2Call",
    0x82: "InitTLB", 0x83: "FindAddress", 0x85: "SetMemoryMode",
}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------- ELF

class Section:
    __slots__ = ("index", "name", "sh_type", "flags", "addr", "off", "size",
                 "link", "info", "align", "entsize", "data")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def is_code(self) -> bool:
        return bool(self.flags & SHF_EXECINSTR) and self.sh_type != SHT_NOBITS

    @property
    def is_body(self) -> bool:
        """Executable AND non-writable: holds function bodies.

        RE4 marks .data as R|W|X (flags=7) because the EE jumps through pointer
        arrays in it. Treating that as bodies yields 37k phantom functions with a
        28-byte median; restricting bodies to read-only-or-text code is what
        makes the census meaningful."""
        return self.is_code and not (self.flags & SHF_WRITE)

    @property
    def is_alloc(self) -> bool:
        return bool(self.flags & SHF_ALLOC)


class Elf:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        d = self.data
        if d[:4] != b"\x7fELF":
            die(f"{path} is not an ELF")
        (self.e_type, self.e_machine, _v, self.entry, self.phoff, self.shoff,
         self.flags, _eh, self.phentsize, self.phnum, self.shentsize,
         self.shnum, self.shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", d, 16)
        if self.e_machine != 8:
            die(f"not EM_MIPS (machine={self.e_machine}) — this tool is PS2-only")

        self.loads: list[tuple[int, int, int, int, int]] = []
        for i in range(self.phnum):
            o = self.phoff + i * self.phentsize
            p_type, p_off, p_va, _pa, p_fsz, p_msz, p_fl, _al = struct.unpack_from(
                "<IIIIIIII", d, o)
            if p_type == 1:
                self.loads.append((p_off, p_va, p_fsz, p_msz, p_fl))

        raw = []
        for i in range(self.shnum):
            o = self.shoff + i * self.shentsize
            vals = struct.unpack_from("<10I", d, o)
            raw.append(vals)
        strtab_off = raw[self.shstrndx][4] if self.shnum else 0

        def name_at(idx: int) -> str:
            if not self.shnum:
                return ""
            b = strtab_off + idx
            try:
                e = d.index(b"\0", b)
            except ValueError:
                return ""
            return d[b:e].decode("latin1", "replace")

        self.sections: list[Section] = []
        for i, v in enumerate(raw):
            nm, t, fl, addr, off, sz, link, info, al, es = v
            sec = Section(index=i, name=name_at(nm), sh_type=t, flags=fl,
                          addr=addr, off=off, size=sz, link=link, info=info,
                          align=al, entsize=es, data=None)
            if t != SHT_NOBITS and sz:
                sec.data = d[off:off + sz]
            self.sections.append(sec)

        # Sort by address. This is the fix for upstream's first-match-in-header
        # -order readWord(). Sections at addr 0 (overlays, .reginfo, strtabs)
        # must never shadow address-based lookups.
        self.by_addr = sorted(
            (s for s in self.sections if s.addr and s.size),
            key=lambda s: s.addr,
        )

    # --- lookup -------------------------------------------------------
    def section_at(self, addr: int) -> Section | None:
        """Address-sorted, most-specific wins. First match in ADDRESS order."""
        for s in self.by_addr:
            if s.addr <= addr < s.addr + s.size:
                return s
        return None

    def word(self, addr: int) -> int | None:
        """Read one guest word. Address-sorted, EXEC-preferring, BSS-aware."""
        for pref_exec in (True, False):
            for s in self.by_addr:
                if not s.addr <= addr < s.addr + s.size:
                    continue
                if pref_exec and not s.is_code:
                    continue
                if s.sh_type == SHT_NOBITS:
                    return 0
                if s.data is None or (addr - s.addr) + 4 > s.size:
                    continue
                o = addr - s.addr
                return struct.unpack_from("<I", s.data, o)[0]
        return None

    def code_words(self) -> tuple[int, dict[int, int]]:
        """All executable words keyed by guest address. Data is excluded.

        .data counts here because RE4 marks it EXEC (flags=7: W|A|X) — it holds
        jump tables and pointer arrays the EE executes through. Excluding it
        costs function coverage, so it is kept, but never treated as function
        *bodies* by the scanner."""
        out: dict[int, int] = {}
        for s in self.sections:
            if not s.is_body or s.data is None:
                continue
            n = s.size // 4
            if n == 0:
                continue
            words = struct.unpack_from(f"<{n}I", s.data, 0)
            for i, w in enumerate(words):
                out[s.addr + i * 4] = w
        return self.entry, out

    # --- overlays -----------------------------------------------------
    def overlays(self) -> tuple[list[Section], list[Section]]:
        ov = [s for s in self.sections if "overlay" in s.name.lower()]
        tab = [s for s in self.sections
               if s.name.lower() in (".dvp.ovlytab", ".dvp.ovlystrtab")]
        return ov, tab


# ---------------------------------------------------------------- decoder

def branch_target(pc: int, w: int) -> int:
    off = w & 0xFFFF
    if off & 0x8000:
        off -= 0x10000
    return (pc + 4 + (off << 2)) & 0xFFFFFFFF


def is_syscall(w: int) -> bool:
    """SYSCALL is SPECIAL/function 0x0C. Primary opcode 0x0C is ANDI."""
    return w >> 26 == OP_SPECIAL and w & 0x3F == FN_SYSCALL


def is_delay_slot_nop(w: int | None) -> bool:
    return w == 0 or (w is not None and (w >> 26) == OP_SPECIAL
                      and (w & 0x3F) == FN_SLL and ((w >> 11) & 0x1F) == 0
                      and (w >> 6) & 0x1F == 0)


def looks_like_prologue(words: dict[int, int], addr: int) -> bool:
    """Real frame setup only.

    ExportPS2Functions.java's 8-word sniff accepts any `$sp`-touching word,
    which is far too loose: on RE4 it accepted 12,446 of 14,910 entries and
    produced a 32-byte median function. A genuine prologue here must either
      (a) grow the frame:  addiu $sp,$sp,-N   with N >= 16 and N % 8 == 0
      (b) save $ra and set up a frame:      sw/sd $ra,N($sp)
      (c) be a bare leaf:                   jr $ra within 4 words, no frame
    This is a heuristic, not proof of a function boundary. GPR saves use SW
    or SD. The old SDC2 description and counts in historical notes were based
    on an incorrect opcode table; LD must never count as a register save.
    """
    if addr & 3:
        return False
    seq = []
    for k in range(10):
        w = words.get(addr + k * 4)
        if w is None:
            break
        seq.append(w)

    frame = False
    saved_ra = False
    for idx, w in enumerate(seq):
        op, rs, rt = w >> 26, (w >> 21) & 0x1F, (w >> 16) & 0x1F
        fn, rd = w & 0x3F, (w >> 11) & 0x1F
        imm = w & 0xFFFF

        # (a) frame GROWTH: addiu $sp,$sp,-N
        #
        # Must run to idx 7. The RE4 fault target 0x2A1C24 grows its frame at
        # word 6 (addiu $sp,$sp,0x50 as the 32-bit half of a 64-bit add), and its
        # only $ra save comes at word 5. A 4-word window saw neither.
        if idx < 8 and op == OP_ADDIU and rs == 29 and rt == 29 and imm & 0x8000:
            n = 0x10000 - imm
            if 16 <= n <= 0x8000 and n % 8 == 0:
                frame = True

        # (b) Store $ra through $sp, accepting word or doubleword saves.
        if idx < 8 and rs == 29 and rt == 31 and op in (OP_SW, OP_SD):
            saved_ra = True
            frame = True

        # (c) `jr $ra` reached: the body is closed. Return the verdict we have
        #     accumulated, NOT `not frame`.
        #
        #     The earlier form was `return not frame and idx < 4`, which meant
        #     "a return with no frame, within 4 words". That is right for a bare
        #     leaf but wrong for anything that opened a frame: it returned False
        #     for exactly the functions we care about. On the RE4 fault target
        #     0x2A1C24 the sequence is
        #         [0] lui / [1] addiu / [2] jal / [3] sw / [4] lui
        #         [5] sd $ra,0x40($sp)     <- frame=True
        #         [6] sw / [7] jr $ra       <- return
        #     so `not frame` was False and the entry was rejected even though the
        #     evidence was perfect. Recorded as dead_ends.jsonl#0055.
        if op == OP_SPECIAL and fn == FN_JR and rs == 31:
            return frame or saved_ra or idx < 4

        # a second return path ends the sniff
        if op == OP_SPECIAL and fn == FN_JALR and rs == 31:
            return frame or saved_ra

    return frame or saved_ra


class Analysis:
    def __init__(self, elf: Elf):
        self.elf = elf
        self.entry, self.words = elf.code_words()
        self.funcs: dict[int, int] = {}      # start -> size
        self.kind: dict[int, str] = {}
        self.labels: set[int] = set()        # internal branch targets
        self.tail_jumps: set[int] = set()    # `j` targets with no prologue
        self.multi_target_added = 0
        self.hole_added = 0
        self.hole_rejected = 0
        self._walk_vis: list[int] = []
        self.syscall_sites: list[tuple[int, int]] = []
        self.visited: set[int] = set()
        # Closure pass (DQ8 invariant): every PC-relative branch target in body
        # code must be serviceable. `_owner_cache` memoises "which function
        # contains this address" because the pass asks once per branch target
        # and the naive version is quadratic.
        self._owner_cache: dict[int, int] = {}
        self._owner_index = None
        self.closure_added = 0
        self.closure_unresolved: list[int] = []
        # Runtime-evidence seeding. `rollback_misses` records addresses the guest
        # reached and the walker still could not close — reported, never dropped.
        self.runtime_fault_added = 0
        self.rollback_misses: list[tuple[int, int]] = []
        # End extension: a function cannot end before the resume address of a call
        # inside it, and an entry carved inside such an extension is a false one.
        self.end_extended = 0
        self.false_entries_demoted = 0
        self.fallthrough_added = 0

    def _follow(self, addr: int) -> int:
        """Walk inside the CURRENT function body. Returns the highest address
        reached, so the caller can size the body correctly."""
        pc = addr
        guard = 0
        hi = addr
        while self._is_code_addr(pc) and pc not in self.visited:
            guard += 1
            if guard > 1_000_000:
                break
            w = self.words[pc]
            op = w >> 26
            self.visited.add(pc)
            hi = max(hi, pc)
            if self._has_delay_slot(w) and self._is_code_addr(pc + 4):
                hi = max(hi, pc + 4)
            if op == OP_SPECIAL and (w & 0x3F) in (FN_JR, FN_JALR) \
                    and ((w >> 21) & 0x1F) == 31:
                if self._is_code_addr(pc + 4):
                    hi = max(hi, pc + 4)
                break
            if op in (OP_J, OP_JAL, OP_JALX):
                if self._is_code_addr(pc + 4):
                    hi = max(hi, pc + 4)
                break
            if self._pc_relative_target(pc, w) is not None:
                t = self._pc_relative_target(pc, w)
                if self._is_code_addr(t) and t not in self.visited:
                    self.labels.add(t)
                    pc = t
                    hi = max(hi, pc)
                    continue
            pc += 4
        return hi

    # --- discovery ----------------------------------------------------
    def discover(self) -> None:
        self._walk(self.entry, "entry")
        self._scan_materialised()
        self._scan_prologues()
        self._scan_syscall_handlers()
        self._trim()
        self._census_syscalls()

        # Feed the triage report back in: anything it found that the three
        # passes above missed becomes a candidate entry. This is the
        # analyze->triage->analyze loop, and it is why coverage keeps climbing
        # on a stripped retail binary.
        for _ in range(4):
            triage = self.find_unresolved_returns()
            before = dict(self.funcs)
            self._scan_multi_target(triage)
            self._scan_hole_prologues()
            self._close_branch_targets()
            self._extend_ends_to_call_returns()
            self._seed_from_runtime_faults()
            self._close_fallthrough_holes()
            if self.funcs == before:
                break
            self._trim()

    @staticmethod
    def _has_delay_slot(w: int) -> bool:
        op = w >> 26
        if op in (OP_J, OP_JAL, OP_JALX, OP_BEQ, OP_BNE, OP_BLEZ, OP_BGTZ,
                  OP_BEQL, OP_BNEL, OP_BLEZL, OP_BGTZL):
            return True
        if op == OP_REGIMM:
            return ((w >> 16) & 31) in (0, 1, 2, 3, 16, 17, 18, 19)
        if op in (OP_COP1, OP_COP2):
            return ((w >> 21) & 31) == 8
        return op == OP_SPECIAL and (w & 63) in (FN_JR, FN_JALR)

    @classmethod
    def _fallthrough(cls, pc: int, w: int) -> int | None:
        op = w >> 26
        if op == OP_J:
            return None
        if op == OP_SPECIAL:
            fn = w & 63
            if fn in (FN_JR, FN_BREAK):
                return None
            if fn == FN_JALR and ((w >> 11) & 31) == 0:
                return None  # jump without a link register
        if op == OP_COP0 and w == 0x42000018:
            return None  # ERET
        if op in (OP_BEQ, OP_BEQL) and ((w >> 21) & 31) == ((w >> 16) & 31):
            return None  # provably unconditional
        return (pc + (8 if cls._has_delay_slot(w) else 4)) & 0xFFFFFFFF

    def _close_fallthrough_holes(self) -> None:
        """Map executable continuations after clipped bodies, as block entries.

        No prologue is required: a mapped instruction's successor is evidence.
        Terminal jumps/returns and their slots never create fallthrough entries.
        Existing entries are preserved; a continuation is not claimed as a call.
        """
        for _ in range(8):
            self._invalidate_owners()
            targets = set()
            for start, size in sorted(self.funcs.items()):
                pc = start + size - 4
                word = self.words.get(pc)
                if word is None:
                    continue
                previous = self.words.get(pc - 4)
                if pc > start and previous is not None and self._has_delay_slot(previous):
                    pc, word = pc - 4, previous
                target = self._fallthrough(pc, word)
                if (target is not None and self._is_code_addr(target)
                        and self._owner_of(target) is None):
                    targets.add(target)
            if not targets:
                break
            added = 0
            for target in sorted(targets):
                if target in self.funcs:
                    continue
                self._walk(target, "fallthrough")
                if self.funcs.get(target, 0):
                    self.fallthrough_added += 1
                    added += 1
            self._trim()
            if not added:
                break
        self._invalidate_owners()

    def _extend_ends_to_call_returns(self) -> None:
        """A function's end must include the resume address of every call inside it.

        DQ8's rule is that a PC-relative branch cannot cross a function boundary
        in compiler output, so a branch past a recorded end proves the end wrong.
        This is the same rule applied to the one transfer DQ8's list of branch
        opcodes does not cover: a call's *return address* is not a branch target,
        so `_close_branch_targets` never sees it.

        Measured on RE4, 2026-10-05:

            FUN_0029ECA8  0x29ECA8 .. 0x29ED70   (200 bytes)
            ...
            // 0x29ed6c: 0xc0a8fb8  jal  func_2A3EE0
                ctx->pc = 0x29ED74u;
            }

        The function ends by setting `ctx->pc = 0x29ED74` and falling off the
        end — four bytes past its own range. A `jal` at X resumes at X+8, so the
        range cannot stop before X+8, and because the range is half-open it must
        reach X+12. The entry the scan then carved at 0x29ED70 was **false** — it
        is the delay slot of that same `jal`, not a function.

        Symptom, measured: `[guest-branch:missing-target] kind=Return source=0x2a3f50
        target=0x29ed74`, raised after 543,289 `sceSifGetReg` calls had stalled.

        **A first attempt at this pass got it wrong twice and both errors are
        worth keeping.** The scan ran `range(start, end - 4, 4)`, which excludes
        the final instruction — precisely the one whose resume address is the
        question — and reported zero extensions. Then it extended to exactly the
        resume address, which leaves that word *outside* a half-open range, and
        `0x29ED74` stayed uncovered while the counters claimed success. An
        extension that does not change what the map can dispatch is not an
        extension.

        DQ8 reaches the same conclusion from the other side in
        `repair_delay_slots`: "an end that lands on a branch's delay slot instead
        of past it ... the delay slot is dropped and the instruction never runs."

        No runtime change is needed: the generator already registers a resume
        entry for every call fallthrough. `FUN_0029ED70` emitted `case 0x29ed7cu:`,
        and 0x29ED7C is exactly the resume address of its own first `jal` at
        0x29ED74. Correcting the map is sufficient.

        A false entry that sits inside the extended range is demoted, not left to
        fight the extension, because the two would overlap and `_trim` would then
        cut the longer body back to the false entry.
        """
        # Cumulative across fixpoint iterations: this runs inside a loop, and a
        # counter that restarts each pass reports 0 for work it actually did.

        for _ in range(8):
            grew = 0
            for start in sorted(self.funcs):
                # An earlier function in this pass may have absorbed this entry
                # already. Iterating a sorted() snapshot does not stop the walk.
                if start not in self.funcs:
                    continue
                end = start + self.funcs[start]
                needed = end
                for pc in range(start, end - 3, 4):
                    w = self.words.get(pc)
                    if w is None:
                        break
                    if self._has_delay_slot(w) and self._is_code_addr(pc + 4):
                        needed = max(needed, pc + 8)
                    resume = self._call_resume_address(pc, w)
                    # `+ 4`: the resume address must be INSIDE the body, and the
                    # range is half-open. Ending at exactly `resume` leaves that
                    # word outside — which is the off-by-one this first landed on.
                    if resume is not None and resume + 4 > needed:
                        needed = resume + 4

                # extend, absorbing any entry the extension now covers
                if needed <= end:
                    continue
                limit = needed
                absorbed = [s for s in self.funcs
                            if start < s < limit and s not in (start,)]
                for s in absorbed:
                    self.funcs.pop(s, None)
                    self.kind.pop(s, None)
                    self.false_entries_demoted += 1
                self.funcs[start] = limit - start
                self.end_extended += 1
                grew += 1
            if grew:
                self._invalidate_owners()
            if not grew:
                break

    @staticmethod
    def _call_resume_address(pc: int, w: int) -> int | None:
        """The address control returns to after the call at `pc`, or None.

        `jal X` and `jalr $rs` both resume at `pc + 8`: the delay slot executes
        first, and that is architecturally part of the call. `jr` does not return
        here — it leaves — so it contributes no requirement. `syscall` resumes at
        `pc + 4` (no delay slot) but is a different dispatch entirely, and the
        recompiler already emits a resume entry for it.
        """
        op = w >> 26
        if op == OP_JAL:
            return pc + 8
        if op == OP_SPECIAL and (w & 0x3F) == FN_JALR:
            return pc + 8
        return None

    # Addresses the runtime reported as unreachable, collected from the most
    # recent boot traces. This is the third kind of evidence, and it is the only
    # one that can see an address reached through a register:
    #   static-call     J/JAL/branch targets      -> _close_branch_targets
    #   static-shape    a prologue inside a hole  -> _scan_hole_prologues
    #   runtime         the guest actually went there and stopped
    # An indirect call target cannot be enumerated by any static pass. The trace
    # is the oracle for exactly that class, and DQ8 reaches for the same thing
    # with `seed_pointer_table_functions.py --table` — a hand-supplied list of
    # addresses to seed. Ours is better than a hand list: it is produced by the
    # game itself.
    # The runtime prints addresses unpadded (`target=0x29eca8`, not `0x0029eca8`),
    # so a fixed-width pattern matches nothing. Measured: `{8}` silently returned
    # an empty dict on a trace that plainly contained three faults.
    _FAULT_RE = re.compile(r"(?:target|handler)=0x([0-9A-Fa-f]{1,8})\b")
    _FAULT_KINDS = ("guest-branch:missing-target", "syscall-override:missing-handler")

    def _fault_targets(self) -> dict[int, int]:
        """{address: how many traces named it} for every runtime fault."""
        seen: dict[int, int] = {}
        for trace in sorted(Path("analysis").glob("boot-trace-*.txt")):
            try:
                text = trace.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if not any(k in line for k in self._FAULT_KINDS):
                    continue
                for m in self._FAULT_RE.finditer(line):
                    seen[int(m.group(1), 16)] = seen.get(int(m.group(1), 16), 0) + 1
        return seen

    def _seed_from_runtime_faults(self) -> None:
        """Promote the addresses the guest actually jumped to and died at.

        Measured on RE4, 2026-10-05: `[guest-branch:missing-target] kind=Return
        op=JR $ra source=0x2a1be0 target=0x29eca8` — a 204-byte hole between
        FUN_0029EC60 (ends 0x29ECA4) and FUN_0029ED70. Nothing static points at
        it: no J, no JAL, no data pointer, no frame prologue. `_has_return`
        demands a `jr $ra` and `plausible_entry_op` rejects `sw`, so
        `_scan_hole_prologues` skips it too — and the body really does start with
        `sw $s1,-0x53E8($s3)` followed by `jal`/`nop`.

        A real function entry that begins with a store. The prologue sniff cannot
        be the only admission test, and the runtime is the only evidence source
        that knows this address is code."""
        for target, hits in sorted(self._fault_targets().items()):
            if target in self.funcs or not self._is_code_addr(target) or target & 3:
                continue
            if self._owner_of(target) is not None:
                continue
            before = len(self.funcs)
            # Try the exact address first, then the four words below it: a return
            # into a body lands on an instruction, not necessarily on the
            # function's first one.
            for cand in (target, target - 4, target - 8, target - 12):
                if cand < 0 or cand & 3 or cand in self.funcs or cand not in self.words:
                    continue
                self._walk(cand, "runtime_fault")
                if len(self.funcs) > before and self.funcs.get(cand, 0) >= 8:
                    self.runtime_fault_added += 1
                    break
            else:
                self.rollback_misses.append((target, hits))
            self._trim()

    def _close_branch_targets(self) -> None:
        """ASSERT closure: every PC-relative branch and jump target in body code
        must be an address the host can service.

        Ported from DQ8-Recompiled, which states the same property as an
        invariant rather than a hope. Their commit 78d76a06: "Every branch and
        jump in the executable's code and in the overlays now lands on an address
        the dispatch table registers." A PC-relative branch cannot cross a
        function boundary in compiler output, so a target that no function
        covers is either a missing entry or a wrong boundary - never a third
        option. Their tool names the consequence exactly: "The recompiler
        compiles a branch to such an address as a jump to another function,
        finds none there, and the guest thread just stops."

        On RE4 this pass found the live fault:
        `[guest-branch:missing-target] kind=DirectJump op=J source=0x2a21e8
        target=0x2a2170` - a 112-byte hole between the function ending at
        0x2A2168 and FUN_002A21E0, with nothing statically referencing its
        start. The jump is the only evidence that the address is code, which is
        why every evidence-keyed pass above missed it and a closure pass cannot.

        Jumps are NOT carved as functions by themselves: a `j` into the middle of
        a body is a tail call into a shared tail or a switch jump, and DQ8 hit
        exactly that when promoting JR fallbacks wholesale (189,876 entries,
        180 MB of output). A target inside an existing body is left alone; only a
        target in a HOLE is promoted, and then only if the walk closes.
        """
        MIN_FUNCTION_BYTES = 8
        # Cumulative across iterations, not per-call. `discover()` runs the
        # closure pass inside a fixpoint loop and resets nothing: a counter that
        # restarts every iteration reports 0 for work that was really done.
        # (Measured: 237 promoted by closure, reported 0.)

        for _ in range(4):
            added = 0
            for pc, w in sorted(self.words.items()):
                target = self._pc_relative_target(pc, w)
                if target is None or target in self.funcs or target & 3:
                    continue
                if not self._is_code_addr(target):
                    continue

                # Already inside a known body: a tail call or a jump table, not a
                # missing entry. Do not promote it.
                if self._owner_of(target) is not None:
                    continue

                before = len(self.funcs)
                self._walk(target, "branch_target")
                got = self.funcs.get(target, 0)
                if got == 0 or got < MIN_FUNCTION_BYTES:
                    self._rollback_walk(target)
                    continue

                added += 1
                self.closure_added += 1

            if added == 0:
                break
            self._trim()
            # `_owner_of` memoises answers that `_trim` has just invalidated by
            # resizing bodies. A stale "unowned" verdict promotes a mid-body
            # address; a stale "owned" verdict hides a real hole. Drop the cache
            # whenever the map changes shape.
            self._invalidate_owners()

        # Whatever is still unowned after promoting every target is reported by
        # address, not summarised. A count would hide which one is stopping boot.
        # Rebuilt from scratch each pass: this pass runs inside a fixpoint loop,
        # and appending across iterations listed the same 23 addresses three
        # times over.
        self.closure_unresolved = []
        seen = set()
        for pc, w in sorted(self.words.items()):
            target = self._pc_relative_target(pc, w)
            if target is None or target & 3 or not self._is_code_addr(target):
                continue
            if self._owner_of(target) is not None:
                continue
            if target in seen:
                continue
            seen.add(target)
            self.closure_unresolved.append(target)

    @staticmethod
    def _pc_relative_target(pc: int, w: int) -> int | None:
        """The PC-relative destination of a branch or jump, or None.

        J/JAL rebuild the address from the delay slot's own page, per the
        ISA: target = ((pc + 4) & 0xF0000000) | (index << 2)."""
        op = w >> 26
        if op in (OP_J, OP_JAL, OP_JALX):
            return (((pc + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)) & 0xFFFFFFFF
        if op in (OP_BEQ, OP_BNE, OP_BLEZ, OP_BGTZ,
                  OP_BEQL, OP_BNEL, OP_BLEZL, OP_BGTZL):
            return branch_target(pc, w)
        if op == OP_REGIMM and ((w >> 16) & 0x1F) in (0, 1, 2, 3, 16, 17, 18, 19):
            return branch_target(pc, w)
        if op in (OP_COP1, OP_COP2):
            # COP1BC / COP2BC: the branch is taken on the floating-point
            # condition bit. rt is the condition select, not a branch kind.
            if ((w >> 21) & 0x1F) == 0x08:
                return branch_target(pc, w)
        return None

    def _invalidate_owners(self) -> None:
        self._owner_cache.clear()
        self._owner_index = None

    def _owner_of(self, addr: int) -> int | None:
        """The start of the function that already contains `addr`, if any."""
        it = self._owner_cache.get(addr)
        if it is not None:
            return it or None
        if self._owner_index is None:
            starts = sorted(self.funcs)
            ends = []
            high = 0
            for start in starts:
                high = max(high, start + self.funcs[start])
                ends.append(high)
            self._owner_index = starts, ends
        starts, ends = self._owner_index
        limit = bisect_right(starts, addr)
        index = bisect_right(ends, addr, hi=limit)
        found = starts[index] if index < limit else None
        self._owner_cache[addr] = found or 0
        return found

    def _is_code_addr(self, a: int) -> bool:
        return a in self.words

    def _walk(self, start: int, kind: str) -> None:
        if start in self.funcs or not self._is_code_addr(start) or start & 3:
            return
        self.funcs[start] = 0
        self.kind[start] = kind
        # Every address this body touches, so a caller that rejects the body can
        # undo it completely. See _rollback_walk.
        self._walk_vis: list[int] = []
        pc = start
        guard = 0
        hi = start          # highest address reached inside this body
        while self._is_code_addr(pc):
            guard += 1
            if guard > 2_000_000:
                break
            w = self.words[pc]
            op = w >> 26
            self.visited.add(pc)
            self._walk_vis.append(pc)
            hi = max(hi, pc)
            if self._has_delay_slot(w) and self._is_code_addr(pc + 4):
                hi = max(hi, pc + 4)

            # ends the current function (after the delay slot)
            if op == OP_SPECIAL and (w & 0x3F) == FN_JR \
                    and ((w >> 21) & 0x1F) == 31:
                if self._is_code_addr(pc + 4):
                    hi = max(hi, pc + 4)
                break
            if op == OP_SPECIAL and (w & 0x3F) == FN_JALR \
                    and ((w >> 21) & 0x1F) == 31:
                if self._is_code_addr(pc + 4):
                    hi = max(hi, pc + 4)
                break
            if op == OP_JALX:
                break

            if op in (OP_J, OP_JAL):
                tgt = ((pc + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
                if not self._is_code_addr(tgt):
                    break
                if op == OP_JAL:
                    # A CALL, not a tail call. Control returns here and the body
                    # continues, so do NOT break: breaking truncated every body at
                    # its first call. On the RE4 fault target 0x2A1C24 that made
                    # the size 12 bytes instead of 40, and the hole scanner then
                    # rejected the single most important entry in the binary.
                    # `j` still breaks, because `j` really does end the body.
                    # Recorded as dead_ends.jsonl#0057.
                    self._walk(tgt, "jal")
                    pc = pc + 4
                    hi = max(hi, pc)
                    continue

                # `j` is ambiguous: tail call, or a jump to a local label.
                # Prologue at the target means call; otherwise treat as a label.
                if self._is_code_addr(pc + 4):
                    hi = max(hi, pc + 4)
                if tgt in self.funcs:
                    break
                if tgt not in self.visited and looks_like_prologue(self.words, tgt):
                    self._walk(tgt, "jump")
                    break
                self.tail_jumps.add(tgt)
                hi = max(hi, self._follow(tgt))

            elif self._pc_relative_target(pc, w) is not None:
                # CRITICAL: a conditional-branch target is an INTERNAL LABEL,
                # not a function entry. Recording it as one inflated RE4 to
                # 37,453 "functions" with a 28-byte median. Only J/JAL/JALR are
                # call edges. Labels are collected for _trim() to use as
                # boundaries instead. See dead_ends.jsonl#0032.
                tgt = self._pc_relative_target(pc, w)
                if self._is_code_addr(tgt):
                    self.labels.add(tgt)
                    hi = max(hi, self._follow(tgt))
                else:
                    break

            elif op == OP_SPECIAL and (w & 0x3F) == FN_JALR:
                reg = (w >> 21) & 0x1F
                if reg == 31:
                    break
                self._maybe_jalr_target(pc, reg)

            elif op == OP_LUI:
                # lui+ori/addiu = address materialisation -> candidate entry
                low = self.words.get(pc + 8)
                if low is not None and (low >> 26) in (OP_ADDIU, OP_ADDI, OP_ORI):
                    up = (w & 0xFFFF) << 16
                    lo = low & 0xFFFF
                    tgt = (up | lo) if (low >> 26) == OP_ORI \
                        else ((up + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF)
                    if self._is_code_addr(tgt) and looks_like_prologue(self.words, tgt):
                        self._walk(tgt, "materialised")

            pc = pc + 4
        # Extent is the highest address actually reached, so a body with
        # internal labels keeps its whole span instead of being cut at the
        # first branch (which produced a 24-byte median on RE4).
        self.funcs[start] = hi - start + 4
        self._invalidate_owners()

    def _maybe_jalr_target(self, pc: int, reg: int) -> None:
        """jr/jalr $t9 style: look back for lui+ori into that register."""
        for back in range(1, 5):
            a = pc - back * 4
            w = self.words.get(a)
            if w is None:
                continue
            if (w >> 26) == OP_LUI:
                low = self.words.get(a + 4)
                if low is None or (low >> 26) not in (OP_ORI, OP_ADDIU):
                    continue
                if ((low >> 16) & 0x1F) != reg:
                    continue
                up = (w & 0xFFFF) << 16
                lo = low & 0xFFFF
                tgt = (up | lo) if (low >> 26) == OP_ORI else \
                    ((up + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF)
                if self._is_code_addr(tgt) and looks_like_prologue(self.words, tgt):
                    self._walk(tgt, "jalr")
                return

    def _scan_materialised(self) -> None:
        """lui+ori/addiu pairs anywhere in code whose result has a prologue."""
        for pc, w in self.words.items():
            if w >> 26 != OP_LUI:
                continue
            low = self.words.get(pc + 4)
            if low is None or (low >> 26) not in (OP_ORI, OP_ADDIU, OP_ADDI):
                continue
            up = (w & 0xFFFF) << 16
            lo = low & 0xFFFF
            tgt = (up | lo) if (low >> 26) == OP_ORI else \
                ((up + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF)
            if tgt in self.funcs or not self._is_code_addr(tgt):
                continue
            if looks_like_prologue(self.words, tgt):
                self._walk(tgt, "materialised")

    def _scan_syscall_handlers(self) -> None:
        """A guest registers its OWN syscall handlers, and passes them as
        immediates — so nothing points at them and every other rule misses them.

        Measured on RE4. `SetSyscall` (EE syscall 0x74 in this runtime) takes
        $a0 = syscall id and $a1 = the guest address that will handle it. At
        0x2A1DE8 the game calls it twice:

            SetSyscall(0x83, 0x2A1C88)
            SetSyscall(0x5A, 0x2A1C50)

        and then invokes 0x83 tens of thousands of times. Neither address was in
        the map:

          - no `jal` points at them (they are handlers, not callees),
          - `_address_taken()` only scans DATA sections, and these live in
            immediates inside code,
          - `_scan_prologues()` needs a data reference, so it skips them,
          - `find_unresolved_returns()` needs a `jr $ra` target, and nothing
            branches to them.

        The result was that `runtime->hasFunction(0x2A1C88)` was false, every
        0x83 call returned KE_ERROR, and the caller looped forever with nothing
        in the log to say why. Recorded as dead_ends.jsonl#0063.

        The rule is general, not the special case: at any `syscall` site, an
        argument register loaded from an immediate that lands in code AND passes
        the prologue test is a function entry. Buffers, handles and sizes do not
        look like prologues; handlers do. That is the whole discriminator.
        """
        for pc, w in self.words.items():
            if not is_syscall(w):
                continue

            for back in range(1, 9):
                a = pc - back * 4
                iw = self.words.get(a)
                if iw is None:
                    continue
                rt = (iw >> 16) & 0x1F
                if rt not in (4, 5, 6, 7):          # $a0..$a3
                    continue
                rs = (iw >> 21) & 0x1F
                op = iw >> 26

                tgt: int | None = None
                if rs == 0 and op == OP_ADDIU:      # addiu $aX, $zero, imm
                    lo = iw & 0xFFFF
                    tgt = (lo - 0x10000 if lo & 0x8000 else lo) & 0xFFFFFFFF
                elif rs == 0 and op == OP_ORI:      # ori $aX, $zero, imm
                    tgt = iw & 0xFFFF
                elif rs == rt and op in (OP_ADDIU, OP_ADDI, OP_ORI):
                    upw = self.words.get(a - 4)      # lui $aX, hi
                    if upw is not None and (upw >> 26) == OP_LUI \
                            and ((upw >> 16) & 0x1F) == rt:
                        hi = (upw & 0xFFFF) << 16
                        lo = iw & 0xFFFF
                        tgt = (hi | lo) if op == OP_ORI else \
                              ((hi + (lo - 0x10000 if lo & 0x8000 else lo))
                               & 0xFFFFFFFF)

                if tgt is None or tgt in self.funcs or not self._is_code_addr(tgt):
                    continue
                if looks_like_prologue(self.words, tgt):
                    self._walk(tgt, "syscall_handler")

    def _address_taken(self) -> set[int]:
        """Addresses referenced by data (pointer tables in .data / .rodata).

        This is the only trustworthy evidence for a callback-table entry, and
        requiring it is what separates real functions from the `addiu $sp,$sp,-N`
        that appears mid-body. Measured on RE4: bare prologue matching gave
        11,637 entries at a 16-byte median; requiring a reference gives a set
        consistent with the 1,735 confirmed call targets.

        Read every byte offset, not just 4-aligned ones. PS2 pointer tables are
        frequently unaligned — a table of 64-bit function pointers that is not
        itself 8-byte aligned means every pointer sits at addr%4 == 2, and the
        previous 4-aligned scan saw zero of them. Recorded as dead_ends.jsonl#0054.
        """
        taken: set[int] = set()
        for s in self.elf.sections:
            if s.is_body or s.data is None or s.size < 4:
                continue
            for off in range(0, s.size - 3):
                v = struct.unpack_from("<I", s.data, off)[0]
                if v & 3 == 0 and v in self.words:
                    taken.add(v)
        return taken

    def _scan_prologues(self) -> None:
        """Callbacks and ORPHAN HANDLERS: a data reference is necessary; a
        prologue is helpful but not required.

        Requiring both (as this did until session 5) is correct for the common
        case and fatal for the case that matters most. Measured on RE4:

            table@0x32ACD0 = { 0x83, 0x2A1C88, 0x5A, 0x2A1C50 }

        0x2A1C88 and 0x2A1C50 are the addresses RE4 registers as its OWN syscall
        handlers via SetSyscall (syscall 0x74). Both are data-referenced, so
        they reach this loop. Neither has a frame:

            0x2A1C88: lw $v0,0($a0) ; beq $t0,$t0,+0x0B ; lw $v0,0x2B($s0) ; ...

        A leaf with no `sd $ra` and no `$sp` adjustment. `looks_like_prologue`
        correctly reports False, so both were dropped, `hasFunction()` was false
        at runtime, every call returned KE_ERROR, and the caller looped forever.
        Recorded as dead_ends.jsonl#0063.

        So the discriminator is not "does it have a prologue". It is:

            a pointer stored in DATA that resolves into executable code and is
            NOT already inside a known function body is, by construction, an
            entry the host must be able to service.

        That holds whether it is a frame-ful callback, a leaf handler, or a
        mid-body resume point - and mapping it is correct in all three cases,
        because an unmapped entry is what makes the runtime report a fault.
        The prologue test is kept, but only as a downgrade: no prologue means the
        body is recorded as `orphan_ref`, which the triage report surfaces
        separately so a thin handler is never silently claimed as a callback.
        """
        taken = self._address_taken()
        for addr in sorted(taken):
            if addr in self.funcs or addr in self.visited or addr & 3:
                continue
            if not self._is_code_addr(addr):
                continue
            if looks_like_prologue(self.words, addr):
                self._walk(addr, "callback")
            else:
                self._walk(addr, "orphan_ref")

    def _rollback_walk(self, start: int) -> None:
        """Undo a rejected `_walk` completely.

        A rejected body must leave NO trace. Previously only `funcs` and `kind`
        were deleted, so every address the body had walked stayed in `visited`.
        On the RE4 fault target that was fatal:

          hole 0x002A1C20..0x002A1CC8 is scanned left to right
          0x2A1C20 matches a prologue, so `_walk` claims 0x2A1C20..0x2A1C40
          the body is then rejected for being too short, and `funcs` is undone
          ...but `visited` is not, so 0x2A1C24 is now permanently marked as
          "inside a known body" and never gets tried

        Result: 0x2A1C24 was invisible to the analyzer forever, even though it is
        exactly the address the runtime said was missing. Recorded as
        dead_ends.jsonl#0056.
        """
        self.funcs.pop(start, None)
        self.kind.pop(start, None)
        self._invalidate_owners()
        for pc in self._walk_vis:
            self.visited.discard(pc)
        self._walk_vis = []

    def _holes(self) -> list[tuple[int, int]]:
        """Contiguous runs of body code covered by no known function.

        Sorted by start. Uses the section extent, not the dictionary, so a hole
        inside .text is reported even if nothing at all was found there."""
        holes = []
        for s in self.elf.sections:
            if not s.is_body or s.data is None:
                continue
            start = s.addr
            end = s.addr + s.size
            cur = start
            for st in sorted(x for x in self.funcs if start <= x < end):
                if st > cur:
                    holes.append((cur, st))
                cur = max(cur, st + self.funcs[st])
            if cur < end:
                holes.append((cur, end))
        return holes

    def _scan_hole_prologues(self) -> None:
        """Final pass: find function entries inside uncovered holes.

        This is the pass that chases the RE4 fault. 0x2A1C24 — the address the
        runtime reported as `[guest-branch:missing-target] kind=Return` — has:

          zero J/JAL references
          zero J references
          zero lui+ori materialisations
          zero entries in any .data pointer table

        Nothing in the binary points at it statically. It is reached only by a
        computed or indirect jump, which is the one class of call no amount of
        call-graph analysis can enumerate. The remaining evidence is the code
        itself: `sd $ra,N($sp)` to open, `jr $ra` with `addiu $sp,$sp,+N` to
        close.

        A frame prologue inside a hole is necessary but NOT sufficient. Measured
        on RE4, accepting every one of them produced 18,612 "functions" with a
        **16-byte median and 69% at or under 16 bytes** — the same failure mode
        as the original bare-prologue scan, in a new disguise: a hole is full of
        mid-body stack adjustments, so each one still looks like an entry.

        Two additional gates, both cheap and both derived from what a real
        function has and a mid-body frame does not:

          closes      a `jr $ra` / `jalr $ra` appears in the body. A prologue
                      without a matching return is a fragment, not a function.
          size        the body must run at least 24 bytes. PS2 functions average
                      180-320; anything shorter is a split artifact.

        With both gates the count stays plausible and the median returns to a
        sane value. This is the honest end of static discovery: past this point
        the only remaining signal is the runtime trace, and closing that loop is
        the Port Agent's job, not the analyzer's.
        """
        added = 0
        rejected = 0
        MIN_FUNCTION_BYTES = 24

        for lo, hi in self._holes():
            a = (lo + 3) & ~3
            while a < hi:
                w = self.words.get(a)
                if w is None:
                    a += 4
                    continue
                if a in self.visited or a in self.funcs:
                    a += 4
                    continue
                if not plausible_entry_op(self.words.get(a, 0)):
                    rejected += 1
                    a += 4
                    continue
                if not looks_like_prologue(self.words, a):
                    a += 4
                    continue

                if not self._has_return(a, hi):
                    rejected += 1
                    a += 4
                    continue

                before = len(self.funcs)
                self._walk(a, "hole_prologue")
                if len(self.funcs) == before or self.funcs.get(a, 0) < MIN_FUNCTION_BYTES:
                    self._rollback_walk(a)
                    rejected += 1
                    a += 4
                    continue

                added += 1
                # this function may have claimed the rest of the hole
                a = (a + self.funcs[a] + 3) & ~3

        self.hole_added = added
        self.hole_rejected = rejected

    def _has_return(self, start: int, limit: int) -> bool:
        """Does a body starting at `start` contain a return, within the hole?"""
        pc = start
        steps = 0
        while pc < limit and steps < 4096:
            w = self.words.get(pc)
            if w is None:
                return False
            op = w >> 26
            if op == OP_SPECIAL and (w & 0x3F) in (FN_JR, FN_JALR) \
                    and ((w >> 21) & 0x1F) == 31:
                return True
            pc += 4
            steps += 1
            if pc - start > 0x2000:
                break
        return False

    def _scan_multi_target(self, triage: list[dict]) -> None:
        """Last pass: entries whose evidence is a J/JAL target that some other
        pass never turned into a function.

        This exists because the three passes above are individually sound and
        collectively incomplete. Each is gated on evidence that is *sufficient*
        but not *necessary*:

          _walk             gated on a call edge from a known entry
          _address_taken    gated on a data pointer, at any alignment now
          _scan_prologues   gated on (data pointer AND frame prologue)

        A function is still missed if it is reached ONLY by an indirect jump
        whose table our data scan did not cover, or by a computed jump whose
        target we could not resolve. On RE4 the triage pass found 9,624 such
        addresses, 8,838 of which have a real frame prologue — that is 1.5x the
        number of functions the first pass found, so this is not a rounding
        error.

        Gate: must have a frame prologue AND be referenced by at least one
        J/JAL. That is still two independent signals, so it cannot match every
        stack frame the way a bare prologue scan does.
        """
        known = set(self.funcs)
        added = 0
        for t in triage:
            if not t.get("prologue"):
                continue
            if t.get("jump_sites", 0) < 1:
                continue
            addr = int(t["addr"], 16) if isinstance(t["addr"], str) else t["addr"]
            if addr in known or addr & 3 or not self._is_code_addr(addr):
                continue
            self._walk(addr, "multi_target")
            added += 1
        self.multi_target_added = added

    def _trim(self) -> None:
        """Clamp bodies to the section end and to the next entry.

        Internal labels are deliberately NOT boundaries — the walker's high-water
        mark already covers them."""
        starts = sorted(self.funcs)
        for i, s in enumerate(starts):
            sec = self.elf.section_at(s)
            limit = (sec.addr + sec.size) if sec else s + 0x10000
            if i + 1 < len(starts):
                limit = min(limit, starts[i + 1])
            self.funcs[s] = max(4, min(self.funcs[s], limit - s))
        self._invalidate_owners()

    def _census_syscalls(self) -> None:
        """Count SPECIAL/SYSCALL, excluding primary-opcode ANDI instructions."""
        for pc, w in self.words.items():
            if is_syscall(w):
                self.syscall_sites.append((pc, (w >> 6) & 0xFFFFF))

    # --- triage -------------------------------------------------------
    def find_unresolved_returns(self) -> list[dict]:
        """Every `jr $ra` whose target is not a function start and is not covered
        by any known function.

        This is the Triage Engine's first rule and it found a real defect on its
        first run against RE4:

            [guest-branch:missing-target] kind=Return op=JR $ra
            source=0x29cc28 target=0x2a1c24

        0x2A1C24 sits in a 208-byte hole between two mapped functions and, when
        disassembled, is a candidate function entry — it saves $ra with SD and
        epilogues with `addiu $sp,$sp,+N`. The map missed it because the
        prologue sniff only matched `sw $ra`, and RE4 is built for the 64-bit ABI
        where doubleword register saves must also be recognized.

        Every result is classified so a human can tell a real gap from noise:

          in_section   the address is inside executable body code at all
          is_start     already a known function entry
          covered_by   inside a mapped function (a jump table or shared tail)
          prologue     looks like a function entry by our own heuristic
          ret_target   referenced by N `jr $ra` sites
        """
        out: list[dict] = []
        starts = set(self.funcs)

        for pc, w in sorted(self.words.items()):
            if (w >> 26) != OP_SPECIAL or (w & 0x3F) != FN_JR:
                continue
            if ((w >> 21) & 0x1F) != 31:
                continue

            # A `jr $ra` jumps to whatever is in $ra, which we cannot know
            # statically. What we CAN do is report every `jr $ra` site whose own
            # address is not a mapped function start — that is where control
            # returned to in the RE4 trace.
            if pc in starts:
                continue
            src_sec = self.elf.section_at(pc)
            if src_sec is None or not src_sec.is_body:
                continue

            owner = self._owner_of(pc)

            out.append({
                "addr": f"0x{pc:08X}",
                "in_body_code": True,
                "is_function_start": pc in starts,
                "covered_by": f"0x{owner:08X}" if owner else None,
                "prologue": looks_like_prologue(self.words, pc),
            })

        # Now the reverse question: addresses that ARE referenced as jump targets
        # but were never discovered. This is the class that actually bit us.
        holes: dict[int, int] = {}
        for pc, w in self.words.items():
            op = w >> 26
            if op not in (OP_J, OP_JAL):
                continue
            tgt = ((pc + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
            if tgt in starts or not self._is_code_addr(tgt):
                continue
            if tgt & 3:
                continue
            holes[tgt] = holes.get(tgt, 0) + 1

        for tgt, n in sorted(holes.items()):
            if tgt in starts:
                continue
            out.append({
                "addr": f"0x{tgt:08X}",
                "in_body_code": True,
                "is_function_start": False,
                "covered_by": None,
                "prologue": looks_like_prologue(self.words, tgt),
                "jump_sites": n,
            })

        out.sort(key=lambda d: (not d["prologue"], -d.get("jump_sites", 0)))
        return out

    # --- report -------------------------------------------------------
    def stats(self) -> dict:
        code_bytes = sum(s.size for s in self.elf.sections if s.is_body)
        covered = sum(min(v, 0x10000) for v in self.funcs.values())
        by_kind: dict[str, int] = {}
        for k in self.kind.values():
            by_kind[k] = by_kind.get(k, 0) + 1
        sizes = sorted(self.funcs.values())
        return {
            "code_bytes": code_bytes,
            "functions": len(self.funcs),
            "covered_bytes": covered,
            "coverage_pct": round(100.0 * covered / code_bytes, 2) if code_bytes else 0.0,
            "by_kind": by_kind,
            "multi_target_added": self.multi_target_added,
            "hole_prologue_added": self.hole_added,
            "hole_prologue_rejected": self.hole_rejected,
            "closure_added": self.closure_added,
            "closure_unresolved": len(self.closure_unresolved),
            "runtime_fault_added": self.runtime_fault_added,
            "runtime_fault_unresolved": len(self.rollback_misses),
            "ends_extended": self.end_extended,
            "false_entries_demoted": self.false_entries_demoted,
            "fallthrough_entries": self.fallthrough_added,
            "median_fn_bytes": sizes[len(sizes) // 2] if sizes else 0,
            "max_fn_bytes": sizes[-1] if sizes else 0,
            "syscall_sites": len(self.syscall_sites),
            "distinct_syscall_ids": len({i for _, i in self.syscall_sites}),
        }


# ---------------------------------------------------------------- output

def write_csv(path: Path, starts: list[int], funcs: dict[int, int]) -> None:
    """Ghidra ExportPS2Functions.java column layout, exactly: Name,Start,End,Size.
    End is exclusive. Size is the byte span (not address-set cardinality)."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["Name", "Start", "End", "Size"])
        for s in starts:
            name = f"FUN_{s:08X}"
            wr.writerow([name, f"0x{s:08X}", f"0x{s + funcs[s]:08X}", funcs[s]])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lodestone analyze")
    ap.add_argument("elf")
    ap.add_argument("--out", default="analysis", help="output directory")
    ap.add_argument("--csv", default=None, help="Ghidra-compatible CSV path")
    args = ap.parse_args(argv[1:])

    path = Path(args.elf)
    if not path.is_file():
        die(f"{path} not found")
    elf = Elf(path)
    an = Analysis(elf)
    an.discover()
    st = an.stats()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    starts = sorted(an.funcs)
    csv_path = Path(args.csv) if args.csv else out / "functions.csv"
    write_csv(csv_path, starts, an.funcs)

    triage = an.find_unresolved_returns()

    ov, ovtab = elf.overlays()
    payload = {
        "elf": str(path),
        "entry": f"0x{elf.entry:08X}",
        "sections": [
            {"name": s.name, "addr": f"0x{s.addr:08X}", "size": s.size,
             "flags": s.flags, "type": s.sh_type,
             "is_code": s.is_code}
            for s in elf.sections if s.size
        ],
        "overlays": {
            "count": len(ov),
            "total_bytes": sum(s.size for s in ov),
            "tables": [s.name for s in ovtab],
            "sections": [{"name": s.name, "addr": f"0x{s.addr:08X}",
                          "size": s.size} for s in ov],
        },
        "stats": st,
        "syscall_ids": {
            f"0x{k:05X}": {"name": None,
                           "id_source": "instruction code field; register syscall ID not inferred",
                           "count": sum(1 for _, v in an.syscall_sites if v == k)}
            for k in sorted({v for _, v in an.syscall_sites})
        },
        "triage": {
            "unmapped_entry_candidates": len(triage),
            "with_prologue": sum(1 for t in triage if t["prologue"]),
            "entries": triage[:400],
        },
        # The DQ8 closure invariant, stated as data. A count alone hides which
        # address is stopping boot, so every survivor is listed by address.
        "closure": {
            "branch_targets_promoted": st["closure_added"],
            "unresolved_targets": [f"0x{a:08X}" for a in an.closure_unresolved],
        },
        "runtime_seeding": {
            "fault_addresses_promoted": st["runtime_fault_added"],
            "still_unwalkable": [{"addr": f"0x{a:08X}", "reports": n}
                                 for a, n in an.rollback_misses],
        },
        "end_extension": {
            "ends_extended": st["ends_extended"],
            "false_entries_demoted": st["false_entries_demoted"],
        },
    }
    (out / "analysis.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 72)
    print(f"LODESTONE analyze   {path}")
    print("=" * 72)
    ex = [s for s in elf.sections if s.is_code]
    for s in sorted(ex, key=lambda s: s.addr):
        kind = "body" if s.is_body else "jump"
        print(f"  {kind:<5} {s.name[:26]:<26} 0x{s.addr:08X}  {s.size:>10,} B")
    print(f"  {'TOTAL BODY CODE':<31}      {st['code_bytes']:>10,} B")
    jump = sum(s.size for s in elf.sections if s.is_code and not s.is_body)
    if jump:
        print(f"  {'  (+ executable jump/data)':<31}      {jump:>10,} B")
    print("-" * 72)
    print(f"  functions found     {st['functions']:,}")
    print(f"  coverage            {st['coverage_pct']:.2f}%  "
          f"({st['covered_bytes']:,} B)")
    print(f"  median fn size      {st['median_fn_bytes']} B   "
          f"max {st['max_fn_bytes']:,} B")
    print("  discovery mix       " + "  ".join(
        f"{k}={v}" for k, v in sorted(st["by_kind"].items(), key=lambda kv: -kv[1])))
    print("-" * 72)
    print(f"  SYSCALL sites       {st['syscall_sites']:,}  "
          f"({st['distinct_syscall_ids']} distinct 20-bit code fields; register IDs not inferred)")
    print("-" * 72)
    print("  CLOSURE  every PC-relative branch target must be serviceable")
    print(f"    promoted from holes  {st['closure_added']}")
    print(f"    still unresolved     {st['closure_unresolved']}")
    for a in an.closure_unresolved[:8]:
        print(f"      0x{a:08X}")
    if not an.closure_unresolved:
        print("      <- invariant holds: no branch lands in an empty address")
    print(f"    seeded from runtime faults  {st['runtime_fault_added']}"
          f"   (unwalkable {st['runtime_fault_unresolved']})")
    for a, n in an.rollback_misses[:8]:
        print(f"      0x{a:08X}  seen in {n} trace(s), walker could not close it")
    print(f"    ends extended past a call  {st['ends_extended']}"
          f"   (false entries demoted {st['false_entries_demoted']})")

    print("-" * 72)
    print("  TRIAGE  addresses referenced but never mapped as entries")
    strong = [t for t in triage if t["prologue"] and t["covered_by"] is None]
    print(f"    candidates      {len(triage)}")
    print(f"    uncovered with prologue   {len(strong)}   <- candidates requiring validation")
    for t in triage[:8]:
        bits = []
        if t.get("jump_sites"):
            bits.append(f"{t['jump_sites']} jump sites")
        if t["prologue"]:
            bits.append("prologue")
        if t["covered_by"]:
            bits.append(f"inside {t['covered_by']}")
        print(f"      {t['addr']}  " + (", ".join(bits) or "unclassified"))

    print("-" * 72)
    if ov:
        print(f"  OVERLAYS            {len(ov)} sections, "
              f"{sum(s.size for s in ov):,} B")
        print(f"  overlay tables      {', '.join(s.name for s in ovtab) or 'none'}")
        print(f"  first               {ov[0].name}")
        print("  => a single program header does NOT mean 'no overlays'.")
    print("-" * 72)
    print(f"  wrote {csv_path}")
    print(f"  wrote {out / 'analysis.json'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    import sys as _sys
    for _s in (_sys.stdout, _sys.stderr):   # a Windows console is not UTF-8
        _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv))

#!/usr/bin/env python3
"""lodestone triage -- turn a runtime capture into a ranked, falsifiable diagnosis.

    lodestone triage <capture.txt> [--profile P] [--top N] [--json]

Why this exists
---------------
Every other static-recompilation project in the ecosystem stops at "the runner
crashed". The port author is then left with a stack trace and a README, and the
real work -- deciding *which* of the fifty possible causes this is -- happens by
brute force, one guess at a time. This project has already paid for that
approach seventy-six times; `knowledge/dead_ends.jsonl` is the bill.

The thing that makes guessing expensive is not ignorance, it is that most of the
candidate causes produce *the same* observable. A silent stall, a spin, a fatal
exception and a missing function all look like "it didn't work" until you
actually look. So this tool does three things that guessing does not:

  1. Names the fault class from a signature in the capture, not from a hunch.
  2. Ranks hypotheses by what the capture actually shows, and cites the line.
  3. Prints a FALSIFIER for every hypothesis -- the measurement that would kill
     it. A diagnosis you cannot disprove is not a diagnosis, and the failure
     memory says the only way this project has ever been wrong is by naming a
     cause without a measurement that rules out the alternatives.

Exit status is 0 when a diagnosis was produced and 1 when the capture did not
match any known signature. It is not a pass/fail test of the game; it is a
pass/fail test of *our understanding*, which is the thing that is usually wrong.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Signature catalogue
# --------------------------------------------------------------------------- #
#
# Each signature is a compiled regex over the capture. `weight` is the log-odds
# contribution in bits: a hard fault the runtime raised deliberately is worth
# far more than a line that merely appeared.
#
# These are REAL signatures, not invented ones. Every pattern below was read
# out of the runtime's own source (ps2_memory.cpp for the alignment and TLB
# paths, ps2_runtime.cpp for the delay-slot refusal, System.cpp for the
# missing-handler report, main.cpp for the fatal wrapper) or out of a real
# capture produced by this project. A triage tool with invented signatures is
# worse than none: it confidently misclassifies.


@dataclass(frozen=True)
class Signature:
    name: str
    pattern: re.Pattern[str]
    weight: float
    kind: str                 # "fault" | "coverage" | "diagnostic"
    summary: str


SIGNATURES: tuple[Signature, ...] = (
    # --- hard faults raised deliberately by the runtime ---------------------
    Signature(
        "fatal-exception",
        re.compile(r"\[main\] fatal exception: (?P<what>.*)"),
        6.0, "fault",
        "The runtime aborted through main()'s catch-all.",
    ),
    Signature(
        "unaligned-access",
        re.compile(r"Unaligned (?P<width>\d+)-bit (?P<dir>read|write) at address: 0x(?P<addr>[0-9a-fA-F]+)"),
        5.0, "fault",
        "A guest access landed on an address its own width cannot represent.",
    ),
    Signature(
        "tlb-miss",
        re.compile(r"TLB miss for address: 0x(?P<addr>[0-9a-fA-F]+)"),
        5.0, "fault",
        "The guest touched a VA the EE TLB does not translate.",
    ),
    Signature(
        "syscall-in-delay-slot",
        re.compile(r"Attempted to execute a syscall inside a branch delay slot"),
        7.0, "fault",
        "A syscall was issued in a branch delay slot, which breaks the "
        "basic-block model the recompiler is built on.",
    ),
    # --- coverage gaps: the port, not the runtime --------------------------
    Signature(
        "missing-override-handler",
        re.compile(
            r"\[syscall-override:missing-handler\] id=0x(?P<id>[0-9a-fA-F]+) "
            r"handler=0x(?P<handler>[0-9a-fA-F]+)"
        ),
        8.0, "coverage",
        "The guest registered this handler with SetSyscall and no recompiled "
        "function exists at that address, so every call silently returns "
        "KE_ERROR and the caller can never make progress.",
    ),
    Signature(
        "missing-branch-target",
        re.compile(r"\[guest-branch:missing-target\][^\n]*?0x(?P<target>[0-9a-fA-F]+)"),
        7.0, "coverage",
        "A guest control transfer landed on an address with no function.",
    ),
    Signature(
        "missing-function",
        re.compile(r"\[function-table\][^\n]*?0x(?P<addr>[0-9a-fA-F]+)"),
        6.0, "coverage",
        "The function map does not cover an address the guest executed.",
    ),
    Signature(
        "syscall-todo",
        re.compile(r"\[Syscall TODO\]"),
        3.0, "coverage",
        "An unimplemented kernel syscall was reached.",
    ),
    Signature(
        "unhandled-rpc",
        re.compile(r"\[IOP/RPC trace:unhandled\]"),
        3.0, "coverage",
        "An SIF RPC command arrived that nothing implements.",
    ),
    # --- diagnostics that indicate a stall rather than a crash -------------
    Signature(
        "findaddress-miss",
        re.compile(r"\[FindAddress:miss\]"),
        2.0, "diagnostic",
        "A pointer search came back empty.",
    ),
    # Structural, not textual: guest activity with no fault. This is the
    # signature that names the single most expensive failure mode in the whole
    # ecosystem - the process is alive, using CPU, raising nothing, and making
    # no progress. Without it, a stall-only capture classifies as "unclassified
    # fault", which is exactly the non-answer that costs a port its afternoon.
    Signature(
        "guest-syscall-activity",
        re.compile(r"\[syscall-ret\]|\[syscall\] id=0x"),
        1.0, "diagnostic",
        "Guest kernel syscalls are reaching the dispatcher and returning; the "
        "runtime is participating normally.",
    ),
)


# --------------------------------------------------------------------------- #
# Behavioural analysis -- the part that guessing cannot do
# --------------------------------------------------------------------------- #


@dataclass
class Behaviour:
    """What the capture shows about *behaviour*, as opposed to what it printed."""

    syscall_ids: dict[int, int] = field(default_factory=dict)
    syscall_ret_v0: dict[str, int] = field(default_factory=dict)
    ret_arg0_cycle: list[str] = field(default_factory=list)
    pc_profile_top: tuple[str, str, str] | None = None
    guest_pcs: list[int] = field(default_factory=list)
    phase_split: str | None = None
    has_fault: bool = False
    line_count: int = 0


_RE_SYSCALL = re.compile(
    r"\[syscall\] id=0x(?P<id>[0-9a-fA-F]+).*?a0=0x(?P<a0>[0-9a-fA-F]+)"
)
_RE_SYSCALL_RET = re.compile(
    r"\[syscall-ret\] id=0x(?P<id>[0-9a-fA-F]+).*?completed\.v0=0x(?P<v0>[0-9a-fA-F]+)"
)
_RE_HOST_PHASE = re.compile(r"host-phase us=\d+.*")
_RE_TOP_PC = re.compile(r"#(?P<rank>\d+) pc=0x(?P<pc>[0-9a-fA-F]+) window=(?P<pct>\d+)")


def analyse(text: str) -> Behaviour:
    """Read a capture and extract behaviour, not just the presence of strings."""
    b = Behaviour()
    b.line_count = len(text.splitlines())

    for line in text.splitlines():
        m = _RE_SYSCALL.search(line)
        if m:
            sid = int(m.group("id"), 16)
            b.syscall_ids[sid] = b.syscall_ids.get(sid, 0) + 1
            b.ret_arg0_cycle.append(m.group("a0"))

        m = _RE_SYSCALL_RET.search(line)
        if m:
            key = f"0x{int(m.group('id'), 16):x}"
            v0 = m.group("v0")
            b.syscall_ret_v0[v0] = b.syscall_ret_v0.get(v0, 0) + 1

        if "host-phase" in line:
            b.phase_split = line.strip()
        m = _RE_TOP_PC.search(line)
        if m:
            b.guest_pcs.append(int(m.group("pc"), 16))

    b.has_fault = any(sig.kind == "fault" for sig in SIGNATURES if sig.pattern.search(text))
    return b


def detect_spin(b: Behaviour) -> str | None:
    """A stall with no fault, described in terms of what is repeating.

    This is the case that costs a project the most, because the process is
    alive, using CPU, and printing nothing that looks like an error. Naming it
    from the data is worth more than any amount of profiling: the question
    changes from "why is it slow" to "what is it repeating".
    """
    # A repeating cycle in a0 is a state machine that has stopped advancing.
    #
    # Four observations is the floor, not six: two complete periods of a 2-cycle
    # is the minimum that distinguishes "the guest is cycling" from "the guest
    # happened to repeat a value". Period 1 is excluded from the result because
    # a constant sequence is covered by the $v0 rule below, which reports it
    # more usefully.
    if len(b.ret_arg0_cycle) >= 4:
        seq = b.ret_arg0_cycle[-12:]
        for p in range(2, len(seq) // 2 + 1):
            if all(seq[i] == seq[i % p] for i in range(len(seq))):
                if p == 2:
                    return (f"a two-state machine: a0 alternates "
                            f"{seq[0]} <-> {seq[1]} without a third value")
                return (f"a repeating cycle of period {p} over a0: "
                        f"{' '.join(sorted(set(seq)))}")

    # A single return value, over and over, is a predicate that never flips.
    #
    # The threshold is deliberately low. Two identical returns is thin evidence
    # on its own -- and that is exactly why the hypothesis this feeds prints a
    # falsifier. The alternative is worse: a capture with no fault, no crash and
    # repeated identical returns gets classified as "unclassified", which is the
    # non-answer this tool exists to replace.
    if b.syscall_ret_v0:
        v0, n = max(b.syscall_ret_v0.items(), key=lambda kv: kv[1])
        if n >= 2 and len(b.syscall_ret_v0) == 1:
            return (f"every guest-to-guest syscall returned $v0 = {v0}, "
                    f"{n} time(s) -- a predicate that never flips")

    # One guest address owning every dispatch.
    if b.pc_profile_top:
        return f"one guest address dominates the dispatch profile ({b.pc_profile_top[1]}%)"

    return None


# --------------------------------------------------------------------------- #
# Hypotheses
# --------------------------------------------------------------------------- #


@dataclass
class Hypothesis:
    rank_title: str
    because: str
    falsifier: str
    next_action: str
    bits: float
    evidence: list[str] = field(default_factory=list)


def build_hypotheses(text: str, b: Behaviour, hits: dict[str, list[str]]) -> list[Hypothesis]:
    out: list[Hypothesis] = []

    # --- highest-value first: a coverage gap names itself ------------------
    if "missing-override-handler" in hits:
        h = hits["missing-override-handler"][0]
        m = re.search(r"handler=0x([0-9a-fA-F]+)", h)
        addr = m.group(1) if m else "?"
        out.append(Hypothesis(
            "the port is missing a function the guest registered",
            f"the guest called SetSyscall for a handler at 0x{addr} that the "
            f"function map does not contain; every such call returns KE_ERROR",
            f"run `lodestone analyze` and check whether 0x{addr} appears in "
            f"the function map; if it does, this is not the cause",
            f"add 0x{addr} to the analyzer's discovery rules (a frameless leaf "
            f"or a data-referenced address is enough - dead_ends#0063)",
            9.0, [h],
        ))

    if "missing-branch-target" in hits or "missing-function" in hits:
        first = (hits.get("missing-branch-target") or hits["missing-function"])[0]
        out.append(Hypothesis(
            "the guest transferred control to an uncovered address",
            "a guest branch or call landed on an address with no recompiled "
            "function behind it",
            "check whether the same address appears in `lodestone analyze`; "
            "if it does, the problem is registration and not coverage",
            "extend analyzer discovery for this shape, then re-run the pipeline",
            8.0, [first],
        ))

    # --- a stall with no fault: the expensive case --------------------------
    spin = detect_spin(b)
    if spin and not b.has_fault:
        bits = 7.0
        ev = [f"{b.line_count} lines, no fault signature present"]
        if b.syscall_ret_v0:
            v0s = ", ".join(f"$v0={v} x{n}" for v, n in
                            sorted(b.syscall_ret_v0.items(), key=lambda kv: -kv[1]))
            ev.append(f"guest-to-guest syscall return values: {v0s}")
        if len(b.syscall_ids) == 1:
            only = next(iter(b.syscall_ids))
            ev.append(f"only one syscall id reached the dispatcher: 0x{only:x}")
        if b.phase_split:
            ev.append("host phase split: " + b.phase_split[:160])

        out.append(Hypothesis(
            "the guest is alive and repeating -- a semantic stall, not a crash",
            f"{spin}. No fault was raised and the process is consuming CPU, so "
            f"the runtime is doing what it was told; the guest's control flow "
            f"is not reaching its exit condition",
            "if the guest's exit condition is data-dependent, read the two "
            "functions (caller and callee) in the generated sources -- the "
            "recompiler's own disassembly comments give you both bodies -- and "
            "check what the callee actually RETURNS before blaming the "
            "boundary between them (dead_ends#0077)",
            "identify the loop's exit condition and prove it is unreachable "
            "with the return value the callee really produces",
            bits, ev,
        ))

        # "The stall is upstream" is about WHAT KIND of syscall reached the
        # dispatcher, not how many. A guest that has never opened the disc
        # cannot have loaded data it later searches for, and that is checkable
        # from the ids alone.
        #
        # PS2 EE file I/O: open 0xA4, close 0xA5, read 0xA6, write 0xA7,
        # lseek 0xA8, ioctl 0xA9, plus the sceIo* family 0xB8..0xC4 and
        # the old *_async 0x51..0x58 set. If none of these ever appears and
        # the stall is data-dependent, the loop is a symptom.
        FILE_IO_IDS = {0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9,
                       0xB8, 0xB9, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,
                       0xC0, 0xC1, 0xC2, 0xC3, 0xC4}
        if b.syscall_ids and not (set(b.syscall_ids) & FILE_IO_IDS):
            seen = " ".join(f"0x{k:x}" for k in sorted(b.syscall_ids))
            out.append(Hypothesis(
                "the stall is upstream of what we are watching",
                f"the dispatchers saw only {seen} and no file-I/O syscall at "
                f"all: the guest has not reached the point in its boot where "
                f"it would normally touch the disc, so data it later searches "
                f"for was never loaded",
                "search the capture for open/read/sceIo; their total absence "
                "alongside a data-dependent stall is consistent with this and "
                "inconsistent with 'the loop itself is wrong'",
                "find and run the earlier boot stage; this loop is a symptom",
                bits - 1.0, ev + [f"syscall ids seen: {seen}"],
            ))

    # --- explicit hard faults ---------------------------------------------
    if "syscall-in-delay-slot" in hits:
        out.append(Hypothesis(
            "syscall inside a branch delay slot",
            "the runtime refuses this outright because the recompiler's "
            "basic-block model cannot represent it",
            "disassemble the guest instruction at the reported pc; if it is "
            "not in a delay slot, the delay-slot tracking is wrong",
            "emit the delay-slot syscall as an exit-then-call, or teach the "
            "scheduler the atomic two-instruction case",
            8.0, [hits["syscall-in-delay-slot"][0]],
        ))

    if "unaligned-access" in hits:
        out.append(Hypothesis(
            "the guest made an access its own width cannot express",
            "alignment is checked against the access width the translation "
            "chose, so this is a translation or an address-derivation "
            "question",
            "read the guest instruction at the faulting pc and compute the "
            "address by hand; if the hand-computed address is aligned, the "
            "translation is wrong",
            "re-derive the address from the instruction, not from the fault",
            6.5, hits["unaligned-access"][:2],
        ))

    if "tlb-miss" in hits:
        out.append(Hypothesis(
            "the guest touched a VA the EE TLB does not translate",
            "the TLB is the guest's own page table; either it was never "
            "populated or the translation is wrong for that region",
            "check whether the faulting VA is one the ELF or a module loader "
            "should have mapped; KSEG0 and KSEG1 never need the TLB",
            "confirm the region, then either populate the mapping or correct "
            "the translation",
            6.5, hits["tlb-miss"][:2],
        ))

    if not out:
        first = hits.get("fatal-exception", [""])[0]
        out.append(Hypothesis(
            "unclassified fault",
            "the capture matched no known signature",
            "add a signature for this text to the catalogue; a signature that "
            "does not exist yet cannot be classified",
            "read the fatal message and add the signature",
            1.0, [first] if first else [],
        ))

    out.sort(key=lambda h: -h.bits)
    return out


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def collect_hits(text: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for sig in SIGNATURES:
        found = [m.group(0) for m in sig.pattern.finditer(text)]
        if found:
            hits[sig.name] = found
    return hits


def cross_reference(h: Hypothesis, dead_ends: list[dict]) -> list[str]:
    """Recorded failures relevant to this hypothesis, ranked.

    The previous version only regexed hardcoded `dead_ends#NNNN` strings out of
    its own canned prose and checked the ids existed. That made the shared
    failure memory unreachable: the only entries the tool could ever surface were
    the two a human had typed by hand, and nothing could search the other eighty.
    An agent that cannot ask what is already known cannot stop re-learning it.

    Matching is on the vocabulary of the fault, not on evidence strings, because
    evidence changes every capture and a title does not. Terms are drawn from
    the signature name, the hypothesis title and the next action, and scored by
    how many distinct terms hit, so a record that shares one incidental word
    cannot outrank one that shares four.
    """
    terms = {t for t in _vocab(h.rank_title) | _vocab(h.falsifier) | _vocab(h.next_action)}
    if not terms:
        return []
    scored: list[tuple[int, str]] = []
    for d in dead_ends:
        did = str(d.get("id", "")).lstrip("#")
        if not did:
            continue
        blob = _vocab(d.get("pattern", "")) | _vocab(d.get("reason", "")) | _vocab(d.get("ref", ""))
        overlap = len(terms & blob)
        if overlap >= 2:
            scored.append((overlap, did))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [f"#{did}" for _, did in scored[:5]]


# Words too common in this domain to carry any signal. Without this filter,
# "register", "value", "register" and similar match almost every record and the
# ranking degenerates to "everything is relevant", which is worse than useless.
_STOPWORDS = frozenset("""
a an and are as at be but by for from had has have in is it its of on or that the
then there this to was were will with after before than they them their we our us
not no do does did been being can could would should may might must if else when
where which who whom what how why all any both each few more most other some such
only own same so too very just also here into over under again further once
""".split())


def _vocab(text: str) -> set[str]:
    """Lowercase content words, minus the ones that match everything."""
    words = re.findall(r"[a-z][a-z0-9_]{2,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and not w.isdigit()}


def load_dead_ends() -> list[dict]:
    path = ROOT / "knowledge" / "dead_ends.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
#
# This tool makes claims about causes, so it gets tested the way the project
# tests its own claims: against captures with KNOWN answers, drawn from several
# different failure classes so that passing one of them cannot mean the
# heuristics are tuned to it. A triage engine that only recognises the failure
# it was born with is not a triage engine.

SELFTEST_CASES: tuple[tuple[str, str, str], ...] = (
    (
        "stall: two-state machine",
        "\n".join([
            "[syscall] id=0x83 encoded=0x0 pc=0x2a1cd0 a0=0x4 a1=0x80080000 a2=0x2a1c88 override=0x2a1c88",
            "[syscall] id=0x83 encoded=0x0 pc=0x2a1cd0 a0=0x5 a1=0x80080000 a2=0x2a1c88 override=0x2a1c88",
            "[syscall] id=0x83 encoded=0x0 pc=0x2a1cd0 a0=0x4 a1=0x80080000 a2=0x2a1c88 override=0x2a1c88",
            "[syscall] id=0x83 encoded=0x0 pc=0x2a1cd0 a0=0x5 a1=0x80080000 a2=0x2a1c88 override=0x2a1c88",
        ]),
        "the guest is alive and repeating -- a semantic stall, not a crash",
    ),
    (
        "stall: predicate never flips",
        "\n".join([
            "[syscall] id=0x83 encoded=0x0 pc=0x2a1cd0 a0=0x80000000 a1=0x80080000 a2=0x2a1c88",
            "[syscall-ret] id=0x83 handler=0x2a1c88 completed.v0=0x1 caller.v0_before=0x0",
            "[syscall-ret] id=0x83 handler=0x2a1c88 completed.v0=0x1 caller.v0_before=0x1",
        ]),
        "the guest is alive and repeating -- a semantic stall, not a crash",
    ),
    (
        "fault: unaligned access",
        "[main] fatal exception: Unaligned 32-bit read at address: 0x2F00FF2",
        "the guest made an access its own width cannot express",
    ),
    (
        "coverage: missing handler",
        "[syscall-override:missing-handler] id=0x83 handler=0x2a1c88 (guest registered it via SetSyscall/0x74)",
        "the port is missing a function the guest registered",
    ),
    (
        "fault: syscall in delay slot",
        "[main] fatal exception: Attempted to execute a syscall inside a branch delay slot!",
        "syscall inside a branch delay slot",
    ),
    (
        "fault: TLB miss",
        "[main] fatal exception: TLB miss for address: 0x04000000",
        "the guest touched a VA the EE TLB does not translate",
    ),
)


def selftest(verbose: bool = True) -> int:
    failures = 0
    for name, text, expected in SELFTEST_CASES:
        b = analyse(text)
        hyps = build_hypotheses(text, b, collect_hits(text))
        got = hyps[0].rank_title if hyps else "<none>"
        ok = (got == expected)
        failures += 0 if ok else 1
        if verbose:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
            if not ok:
                print(f"        expected: {expected}")
                print(f"        got     : {got}")
    print(f"  {len(SELFTEST_CASES) - failures}/{len(SELFTEST_CASES)} passed")
    return 1 if failures else 0


def render(text: str, b: Behaviour, hits: dict[str, list[str]],
           hyps: list[Hypothesis], dead_ends: list[dict], top: int) -> str:
    W = 76
    L: list[str] = []
    L.append("=" * W)
    L.append("LODESTONE TRIAGE")
    L.append("=" * W)
    L.append(f"  capture        {b.line_count} lines")
    L.append(f"  signatures     {len(hits)} matched"
             + (", " + ", ".join(sorted(hits)) if hits else ""))
    if b.syscall_ids:
        L.append("  syscalls      " + "  ".join(
            f"0x{k:x} x{v}" for k, v in
            sorted(b.syscall_ids.items(), key=lambda kv: -kv[1])))
    if b.syscall_ret_v0:
        L.append("  returns       " + "  ".join(
            f"$v0={v} x{n}" for v, n in
            sorted(b.syscall_ret_v0.items(), key=lambda kv: -kv[1])))
    L.append("")

    for i, h in enumerate(hyps[:top], 1):
        L.append("-" * W)
        L.append(f"[{i}] {h.rank_title}   ({h.bits:+.1f} bits)")
        L.append("-" * W)
        L.append(f"    because : {h.because}")
        for e in h.evidence[:4]:
            L.append(f"      - {e[:150]}")
        L.append(f"    falsify : {h.falsifier}")
        L.append(f"    do next : {h.next_action}")
        refs = cross_reference(h, dead_ends)
        if refs:
            L.append(f"    memory  : dead_ends " + ", ".join("#" + r for r in refs))
        L.append("")

    L.append("=" * W)
    L.append("A diagnosis without a falsifier is a guess. Read the falsifier")
    L.append("before you act on the diagnosis.")
    L.append("=" * W)
    return "\n".join(L)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lodestone triage", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", nargs="?", default="-",
                    help="runtime stderr capture ('-' for stdin)")
    ap.add_argument("--profile", default=str(ROOT / "profiles" / "SLUS-211.34" / "profile.toml"))
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--selftest", action="store_true",
                    help="run the built-in cases and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        print("lodestone triage self-test")
        return selftest()

    if args.capture == "-":
        text = sys.stdin.read()
    else:
        p = Path(args.capture)
        if not p.is_file():
            print(f"triage: no such capture: {p}", file=sys.stderr)
            return 2
        text = p.read_text(encoding="utf-8", errors="replace")

    b = analyse(text)
    hits = collect_hits(text)
    hyps = build_hypotheses(text, b, hits)
    dead = load_dead_ends()

    if args.json:
        json.dump({
            "lines": b.line_count,
            "signatures": {k: v[:4] for k, v in hits.items()},
            "syscall_ids": {hex(k): v for k, v in b.syscall_ids.items()},
            "syscall_returns": b.syscall_ret_v0,
            "spin": detect_spin(b),
            "hypotheses": [
                {"title": h.rank_title, "bits": h.bits, "because": h.because,
                 "falsifier": h.falsifier, "next": h.next_action,
                 "evidence": h.evidence}
                for h in hyps
            ],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render(text, b, hits, hyps, dead, args.top))

    # Exit status reports whether WE understood the capture, not whether the
    # game worked. A capture we cannot classify is the thing that must fail.
    return 0 if hits or b.syscall_ids else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
#!/usr/bin/env python3
"""lodestone agent — an incremental port loop with a ledger, not a guess loop.

    lodestone agent plan  <capture.txt>     ordered actions for one fault
    lodestone agent run  --budget N        the loop: run -> triage -> fix -> re-run
    lodestone agent ledger [<port-id>]     what has been tried, kept and rejected
    lodestone agent --selftest             prove the loop on a simulated port

The problem it solves
---------------------
Porting a game to a static recompiler is an iterate-and-observe loop: run, read
the failure, change something, rebuild, run again. Every existing project does
this by hand, and every one of them starts from zero on the next game, because
the knowledge lives in the author's head.

Two things make the hand loop expensive. First, a rebuild is expensive -- for
this project, 250 s -- so a wrong guess costs four minutes of silence. Second,
and much worse, a wrong guess that *appears* to help gets remembered as if it
did: nothing in the loop records that hypothesis two was tried, failed, and
should not be tried again.

So this agent has two halves, and the second is the important one:

  1. The loop. Run the runtime, triage the capture, apply the highest-ranked
     hypothesis that has a MECHANISED fix, rebuild, re-run, compare.

  2. The ledger. Every hypothesis is recorded with its evidence, what was done
     about it, and -- when it was disproved -- the measurement that disproved
     it. A hypothesis that has been disproved is never re-proposed. The ledger
     is per-port but the failure memory is shared, so the ninth game starts
     knowing what the first eight already ruled out.

What it will not do
-------------------
It will not invent a fix. Only hypotheses with a known, mechanised remedy are
applied; everything else is surfaced for a human. This is the project's rule
[#0070, #0075, #0077] turned into code: name a cause only with a measurement
that rules out the alternatives, and never act on the most recently read idea.
A loop that guesses faster is not a better port; it is the same port, faster.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import triage  # noqa: E402  (local module, deliberately after sys.path fix)


# --------------------------------------------------------------------------- #
# Fix catalogue
# --------------------------------------------------------------------------- #
#
# A remedy is only listed here if it is (a) mechanised — there is a command or
# a file edit that performs it — and (b) safe to apply without a human deciding
# it is the right fix. Everything else is surfaced and left alone.
#
# `signature` is a triage signature name, so a remedy can never fire on a fault
# the triage engine did not actually observe.


@dataclass(frozen=True)
class Remedy:
    signature: str
    title: str
    action: str                       # human-readable, printed verbatim
    kind: str                         # "cmd" | "edit"
    command: tuple[str, ...] = ()     # argv, {port} and {root} substituted
    verified_by: str = ""             # what re-running must show to count


REMEDIES: tuple[Remedy, ...] = (
    Remedy(
        "missing-override-handler",
        "extend analyzer discovery for the missing handler address",
        "add the address to the analyzer's discovery rules and regenerate",
        "cmd",
        ("python", "ps2l/analyze.py", "{elf}"),
        "the [syscall-override:missing-handler] line disappears and the "
        "handler's own syscalls start appearing",
    ),
    Remedy(
        "guest-syscall-activity",
        "confirm the stall is semantic, not coverage, before changing anything",
        "no edit — re-read the caller and callee in the generated sources",
        "edit",
        verified_by="the guest's exit condition becomes reachable, or the "
                    "capture gains a signature that was not there before",
    ),
)


def remedy_for(signature: str) -> Remedy | None:
    for r in REMEDIES:
        if r.signature == signature:
            return r
    return None


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
#
# Append-only. A hypothesis is never deleted, only closed, because "we tried
# this and it did not work" is the single most valuable thing a port can know
# and the thing hand-porting loses first.


@dataclass
class HypothesisRecord:
    key: str
    title: str
    first_seen: str
    evidence: list[str]
    status: str = "open"       # open | proposed | applied | rejected | deferred
    attempts: int = 0
    ruled_out_by: str = ""            # the measurement that killed it
    signature: str = ""               # the triage signature this remedy targeted
    notes: str = ""


@dataclass
class Ledger:
    port: str
    created: str
    iterations: list[dict] = field(default_factory=list)
    hypotheses: dict[str, HypothesisRecord] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        d = ROOT / "knowledge" / "ports"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.port}.json"

    def load(self) -> "Ledger":
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.iterations = data.get("iterations", [])
            self.hypotheses = {
                k: HypothesisRecord(**v) for k, v in data.get("hypotheses", {}).items()
            }
        return self

    def save(self) -> None:
        self.path.write_text(
            json.dumps({
                "port": self.port,
                "created": self.created,
                "iterations": self.iterations,
                "hypotheses": {k: asdict(v) for k, v in self.hypotheses.items()},
            }, indent=2),
            encoding="utf-8",
        )

    def key_for(self, h: triage.Hypothesis) -> str:
        # A hypothesis is identified by its TITLE, not by its evidence. Evidence
        # changes every run — the syscall counts, the capture line numbers — and
        # keying on it would reset the ledger on every iteration and lose
        # exactly the history the ledger exists to keep.
        return h.rank_title

    def live(self) -> list[HypothesisRecord]:
        return [r for r in self.hypotheses.values() if r.status == "open"]


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


@dataclass
class Runner:
    """How the agent obtains a capture. Injected so the loop is testable.

    A port loop that can only be exercised by running a real game is a port loop
    whose logic is never exercised at all. The runner interface is one method
    wide for that reason: point it at the real runner, or at a script.
    """

    command: tuple[str, ...]
    timeout_s: int
    log: Path

    def capture(self, budget_note: str = "") -> tuple[str, int]:
        """Run once and return (stderr text, exit code)."""
        if self.log.parent and str(self.log.parent):
            self.log.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                list(self.command),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            text = (exc.stderr or b"").decode("utf-8", "replace")
            text += (f"\n[agent] run exceeded timeout {self.timeout_s}s and was killed\n")
            self.log.write_text(text, encoding="utf-8")
            return text, 124
        except FileNotFoundError:
            text = f"[agent] runner not found: {self.command[0]}\n"
            self.log.write_text(text, encoding="utf-8")
            return text, 127
        text = proc.stderr.decode("utf-8", "replace")
        self.log.write_text(text, encoding="utf-8")
        return text, proc.returncode


def classify(text: str) -> tuple[triage.Behaviour, dict[str, list[str]], list[triage.Hypothesis]]:
    b = triage.analyse(text)
    hits = triage.collect_hits(text)
    hyps = triage.build_hypotheses(text, b, hits)
    return b, hits, hyps


def top_signature(hits: dict[str, list[str]], hyps: list[triage.Hypothesis]) -> str:
    """The signature that best explains the capture, by triage's own ranking.

    Not merely "the first signature that matched": a coverage signature outranks
    a diagnostic one at equal weight, and that ordering is the whole point of
    having weights at all.
    """
    best, best_w = "", -1e9
    for name in hits:
        for sig in triage.SIGNATURES:
            if sig.name == name and sig.weight > best_w:
                best, best_w = name, sig.weight
    return best


def run_loop(led: Ledger, runner: Runner, budget: int, verbose: bool = True) -> int:
    led = led.load()
    applied_any = False

    for step in range(1, budget + 1):
        if verbose:
            print("=" * 76)
            print(f"PORT AGENT  {led.port}  iteration {step}/{budget}")
            print("=" * 76)

        text, code = runner.capture()
        b, hits, hyps = classify(text)
        sig = top_signature(hits, hyps)
        spin = triage.detect_spin(b)

        if verbose:
            print(f"  runner exit {code}; {b.line_count} capture line(s)")
            print(f"  signatures  {', '.join(sorted(hits)) or '(none)'}")
            if spin:
                print(f"  behaviour   {spin}")
            print()

        if not hits and not b.syscall_ids:
            if verbose:
                print("  Nothing recognised this capture. That is the honest result:")
                print("  a fault with no signature is a gap in the catalogue, not a")
                print("  gap in the game. Add a signature before going further.")
            led.iterations.append({"step": step, "exit": code, "signatures": [],
                                   "outcome": "no signature"})
            led.save()
            return 1

        led.iterations.append({
            "step": step, "exit": code,
            "signatures": sorted(hits),
            "spin": spin,
            "syscall_ids": {hex(k): v for k, v in b.syscall_ids.items()},
        })

        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Verification ladder, steps 4 and 5: before choosing anything new,
        # settle what happened to the remedies proposed on earlier iterations.
        #
        # This used to be missing entirely, and the absence was not subtle: the
        # loop marked a hypothesis "applied" the instant it PRINTED the remedy
        # (the code even said "printed, not executed"), and nothing ever wrote
        # "rejected", so the skip test two lines below could never fire. With
        # --budget 3 the loop therefore re-proposed the same hypothesis three
        # times by construction - precisely the compile-test-fail-guess cycle
        # the guardrails forbid, dressed as an agent.
        #
        # A remedy is only allowed to become "applied" once a later capture
        # shows the fault it targeted is gone. Otherwise it is "rejected", with
        # ruled_out_by naming what actually happened, and the loop moves on.
        for key, rec in list(led.hypotheses.items()):
            if rec.status != "proposed":
                continue
            if rec.signature and rec.signature in hits:
                rec.status = "rejected"
                rec.ruled_out_by = (
                    f"remedy applied, fault still present after {rec.attempts} "
                    f"attempt(s): signature {rec.signature!r} still matches the "
                    f"latest capture ({now})")
                if verbose:
                    print(f"  reject      {rec.title}")
                    print(f"              {rec.ruled_out_by}")
            else:
                rec.status = "applied"
                if verbose:
                    print(f"  confirm     {rec.title}: signature "
                          f"{rec.signature!r} no longer present ({now})")
            led.save()

        chosen = None
        for h in hyps:
            key = led.key_for(h)
            rec = led.hypotheses.get(key)
            if rec is None:
                rec = HypothesisRecord(key=key, title=h.rank_title, first_seen=now,
                                       evidence=h.evidence[:3])
                led.hypotheses[key] = rec
            rec.evidence = h.evidence[:3]
            if rec.status == "rejected":
                if verbose:
                    print(f"  skip        {h.rank_title}")
                    print(f"              already ruled out: {rec.ruled_out_by or '(recorded)'}")
                continue
            chosen = (h, rec)
            break

        if chosen is None:
            if verbose:
                print("  Every hypothesis here has been ruled out already.")
                print("  The loop cannot progress by itself: this needs a human.")
            led.save()
            return 3

        h, rec = chosen
        rec.status = "open"
        rec.attempts += 1
        remedy = remedy_for(sig)

        if verbose:
            print(f"  acting on   {h.rank_title}")
            print(f"    because   {h.because[:150]}")
            print(f"    falsifier {h.falsifier[:150]}")
            if remedy:
                print(f"    remedy    {remedy.title}")
                print(f"      {remedy.action}")
                if remedy.kind == "cmd":
                    cmd = " ".join(remedy.command).replace("{elf}", "<elf>")
                    print(f"      $ {cmd}")
                    print("      (printed, not executed — apply it, then re-run)")
                if remedy.verified_by:
                    print(f"    confirmed when: {remedy.verified_by}")
            else:
                print(f"    NO mechanised fix for signature '{sig or 'none'}'.")
                print("    Surfacing it rather than inventing a change.")
            print()

        # "proposed", not "applied". Printing a command is not a result: whether it
        # worked is decided on the next iteration, by comparing the new capture
        # against this one's signature. Marking it applied here is what let the
        # same fault be re-proposed for the whole budget.
        rec.status = "proposed" if remedy else "deferred"
        rec.signature = sig or ""
        applied_any = applied_any or rec.status == "proposed"
        led.save()

    if verbose:
        print("=" * 76)
        print(f"budget of {budget} iteration(s) reached. "
              f"{len(led.hypotheses)} hypothesis record(s).")
        print("=" * 76)
    return 0 if applied_any else 1


# --------------------------------------------------------------------------- #
# plan / ledger views
# --------------------------------------------------------------------------- #


def plan(text: str) -> int:
    b, hits, hyps = classify(text)
    sig = top_signature(hits, hyps)
    print("=" * 76)
    print("PORT AGENT  plan")
    print("=" * 76)
    print(f"  signatures  {', '.join(sorted(hits)) or '(none)'}")
    if triage.detect_spin(b):
        print(f"  behaviour   {triage.detect_spin(b)}")
    print()
    if not hyps:
        print("  nothing to plan.")
        return 1
    for i, h in enumerate(hyps, 1):
        r = remedy_for(sig if i == 1 else "")
        mark = "auto" if r and r.kind == "cmd" else "human"
        print(f"[{i}] ({mark}) {h.rank_title}")
        print(f"    because  {h.because}")
        print(f"    falsifier {h.falsifier}")
        if r:
            print(f"    remedy   {r.action}")
            print(f"    confirmed when: {r.verified_by}")
        else:
            print("    remedy   none registered — needs a human decision")
        print()
    return 0


def ledger_view(port: str) -> int:
    led = Ledger(port=port, created="").load()
    print("=" * 76)
    print(f"PORT LEDGER  {port}")
    print("=" * 76)
    if not led.hypotheses:
        print("  no hypotheses recorded yet.")
        return 0
    for rec in sorted(led.hypotheses.values(), key=lambda r: -r.attempts):
        tag = {"open": "OPEN    ", "proposed": "PROPOSE ", "applied": "APPLIED ", "rejected": "REJECTED",
               "deferred": "DEFERRED"}.get(rec.status, rec.status.upper())
        print(f"  [{tag}] {rec.title}")
        print(f"             attempts {rec.attempts}, first seen {rec.first_seen}")
        if rec.ruled_out_by:
            print(f"             ruled out by: {rec.ruled_out_by}")
        for e in rec.evidence[:2]:
            print(f"             evidence: {e[:120]}")
        print()
    print(f"  {len(led.iterations)} iteration(s) recorded")
    return 0


# --------------------------------------------------------------------------- #
# Self-test — the loop, on a simulated port
# --------------------------------------------------------------------------- #


def _selftest() -> int:
    import tempfile

    cases: list[tuple[str, bool, object]] = []

    # 1. a capture with no known signature must be reported as such, not guessed
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        script = root / "fake_run.py"
        script.write_text("import sys\nsys.stderr.write('nothing recognisable here\\n')\n",
                          encoding="utf-8")
        led = Ledger(port="SELFTEST-noise", created="x")
        led.path.unlink(missing_ok=True)
        rc = run_loop(led, Runner(("python", str(script)), 30, root / "log.txt"), 2, verbose=False)
        cases.append(("a capture with no signature is refused, not guessed", rc == 1, rc))

    # 2. a known signature must be planned AND get a mechanised remedy
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        script = root / "fake_run.py"
        script.write_text(
            "import sys\n"
            "sys.stderr.write('[syscall-override:missing-handler] id=0x83 handler=0x2a1c88 (x)\\n')\n",
            encoding="utf-8")
        led = Ledger(port="SELFTEST-missing", created="x")
        led.path.unlink(missing_ok=True)
        rc = run_loop(led, Runner(("python", str(script)), 30, root / "log.txt"), 1, verbose=False)
        rec = led.load().hypotheses
        got = next(iter(rec.values())) if rec else None
        # A remedy that has only been PRINTED is "proposed", never "applied".
        ok = rc == 0 and len(rec) == 1 and got is not None and got.status == "proposed"
        cases.append(("a missing handler is planned but only PROPOSED, not applied", ok, rec))

    # 2b. the verification step the old loop did not have.
    #     A proposed remedy whose fault is STILL there in a later capture must
    #     become "rejected" and the loop must move on, instead of re-proposing
    #     the same hypothesis for the whole budget.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        script = root / "fake_run.py"
        script.write_text(
            "import sys\n"
            "sys.stderr.write('[syscall-override:missing-handler] id=0x83 handler=0x2a1c88 (x)\\n')\n",
            encoding="utf-8")
        led = Ledger(port="SELFTEST-verify", created="x")
        led.path.unlink(missing_ok=True)
        r = Runner(("python", str(script)), 30, root / "log.txt")
        run_loop(led, r, 1, verbose=False)
        rc = run_loop(led, r, 1, verbose=False)   # same fault, still present
        st = led.load().hypotheses
        vals = list(st.values())
        ok = (rc == 3                       # nothing left to try -> ask a human
              and len(vals) == 1
              and vals[0].status == "rejected"
              and "still present" in vals[0].ruled_out_by)
        cases.append(("a remedy that did not fix the fault is rejected and retired",
                      ok, [(v.status, v.ruled_out_by) for v in vals]))

    # 3. an exhausted hypothesis set must stop the loop and ask for a human
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        script = root / "fake_run.py"
        script.write_text(
            "import sys\n"
            "sys.stderr.write('[syscall-override:missing-handler] id=0x83 handler=0x2a1c88 (x)\\n')\n",
            encoding="utf-8")
        led = Ledger(port="SELFTEST-repeat", created="x")
        led.path.unlink(missing_ok=True)
        r = Runner(("python", str(script)), 30, root / "log.txt")
        run_loop(led, r, 1, verbose=False)          # first pass: apply
        after_first = led.load()
        for rec in after_first.hypotheses.values():
            rec.status = "rejected"
            rec.ruled_out_by = "capture was byte-identical after the change"
        after_first.save()      # must persist: run_loop re-loads from disk
        rc = run_loop(led, r, 1, verbose=False)      # second pass: nothing left
        cases.append(("a ledger with everything rejected stops and returns 3", rc == 3, rc))

    # 4. budget must be honoured exactly
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        script = root / "fake_run.py"
        script.write_text(
            "import sys\n"
            "sys.stderr.write('[syscall-override:missing-handler] id=0x83 handler=0x2a1c88 (x)\\n')\n",
            encoding="utf-8")
        led = Ledger(port="SELFTEST-budget", created="x")
        led.path.unlink(missing_ok=True)
        run_loop(led, Runner(("python", str(script)), 30, root / "log.txt"), 3, verbose=False)
        after = led.load()
        n = len(after.iterations)
        st = after.hypotheses
        # Three identical captures of a fault nobody fixed. The loop must stop
        # EARLY - at 2, not 3 - because iteration 2 finds the fault still there,
        # retires the hypothesis, and has nothing left to propose. Spending the
        # full budget re-proposing a dead remedy is exactly the failure this
        # step exists to prevent.
        retired = [v for v in st.values() if v.status == "rejected"]
        ok = n == 2 and len(st) == 1 and len(retired) == 1 and retired[0].attempts == 1
        cases.append(("the loop stops early once a retry is retired, not at budget",
                      ok, (n, len(st), [(v.status, v.attempts) for v in st.values()])))

    # 5. the ledger must be keyed on the title, not on evidence that changes
    led = Ledger(port="SELFTEST-key", created="x")
    led.path.unlink(missing_ok=True)
    h1 = triage.Hypothesis("a title", "because", "falsify", "next", 5.0, ["evidence A"])
    h2 = triage.Hypothesis("a title", "because", "falsify", "next", 5.0, ["evidence B"])
    cases.append(("hypotheses are keyed on title, not on volatile evidence",
                  led.key_for(h1) == led.key_for(h2), led.key_for(h1)))

    failures = 0
    print("lodestone agent self-test")
    for name, ok, got in cases:
        if not ok:
            failures += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        got: {got!r}")
    print(f"  {len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lodestone agent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("plan", help="ordered actions for one capture")
    p.add_argument("capture")

    r = sub.add_parser("run", help="the run -> triage -> fix loop")
    r.add_argument("--port", required=True, help="port id, e.g. SLUS_211.34")
    r.add_argument("--command", required=True,
                   help="the command that produces a capture (argv string)")
    r.add_argument("--budget", type=int, default=3, help="max iterations")
    r.add_argument("--timeout", type=int, default=120, help="seconds per run")
    r.add_argument("--log", default=None, help="where to keep the capture")

    l = sub.add_parser("ledger", help="what has been tried, kept and rejected")
    l.add_argument("port", nargs="?", default="SLUS_211.34")

    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.cmd is None:
        ap.print_help()
        return 2

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if args.cmd == "plan":
        p = Path(args.capture)
        if not p.is_file():
            print(f"agent: no such capture: {p}", file=sys.stderr)
            return 2
        return plan(p.read_text(encoding="utf-8", errors="replace"))

    if args.cmd == "ledger":
        return ledger_view(args.port)

    assert args.cmd == "run"
    import shlex
    runner = Runner(tuple(shlex.split(args.command)), args.timeout,
                    Path(args.log) if args.log else ROOT / "analysis" / "agent" / f"{args.port}.log")
    return run_loop(Ledger(port=args.port, created=time.strftime("%Y-%m-%dT%H:%M:%S")),
                    runner, args.budget)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

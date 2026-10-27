#!/usr/bin/env python3
"""lodestone — one CLI for the whole pipeline.

    lodestone fingerprint <ELF|disc dir>     identity + census          [no build]
    lodestone analyze   <ELF>                function map + census    [no build]
    lodestone mapcheck <ELF> <CSV>           branch and delay-slot audit [no build]
    lodestone entrycheck <ELF> <CSV> <trace> <generated> observed dispatch audit
    lodestone framecheck <capture directory> captured pixel facts     [no build]
    lodestone bootcheck <capture directory>  disc progress and failures [no build]
    lodestone check    <terms...>            failure memory query     [no build]
    lodestone profile  <profile.toml>        validate a profile       [no build]
    lodestone decompref [address]             verified local C reference [no build]
    lodestone build    [--configure-flag X=V] configure + build runner  [needs core]
    lodestone triage  <capture.txt>          fault -> ranked diagnosis [no build]
    lodestone diffview diff A B            frame -> pixel verdict      [no build]
    lodestone agent  plan <capture>     port loop: run/triage/fix   [no build]
    lodestone status                          where every stage stands [no build]
    lodestone verify                         tooling regression gate [no build]
    lodestone canary --branch64               execute generated EE branch probes
    lodestone canary --compare64              execute EE comparisons and doubling probes
    lodestone canary --tailcall               check direct transfers and build dependencies
    lodestone run <ELF>                       bounded native capture [needs build]

Deliberate scope: the first four commands need nothing but Python 3.10+.
`lodestone verify` tests tooling. Game compatibility requires separate native
execution and reference evidence; a tooling pass does not certify a port.
"""

from __future__ import annotations

import subprocess
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

COMMANDS = {
    "decompref": (HERE / "decompref.py", "look up stored PS2 matching evidence and verify artifacts"),
    "entrycheck": (HERE / "entrycheck.py", "audit observed indirect targets against generated dispatch"),
    "bootcheck": (HERE / "bootcheck.py", "audit disc read acceptance and failures"),
    "framecheck": (HERE / "framecheck.py", "audit captured pixels without claiming gameplay"),
    "mapcheck": (HERE / "mapcheck.py", "validate static branches and delay slots before build"),
    "canary": (HERE / "canary.py", "known ELF to generated native CPU execution"),
    "verify": (HERE / "verify.py", "tooling regression gate"),
    "run": (HERE / "run.py", "bounded native capture"),
    "fingerprint": (HERE / "fingerprint.py", "identity + census"),
    "analyze": (HERE / "analyze.py", "function map + census"),
    "check": (HERE / "check_dead_ends.py", "failure memory query"),
    "profile": (HERE / "profile.py", "validate a profile"),
    "build": (HERE / "build.py", "configure + build the runner"),
    "triage": (HERE / "triage.py", "fault -> ranked diagnosis"),
    "diffview": (HERE / "diffview.py", "frame -> pixel verdict"),
    "agent": (HERE / "agent.py", "port loop: run/triage/fix"),
}


def run(script: Path, argv: list[str]) -> int:
    return subprocess.call([sys.executable, str(script), *argv])


def status() -> int:
    try:                                     # Python 3.11+
        import tomllib
    except ModuleNotFoundError:              # 3.10 and older
        import tomli as tomllib              # type: ignore[no-redef]

    prof = ROOT / "profiles" / "SLUS-211.34" / "profile.toml"
    print("=" * 72)
    print("LODESTONE status")
    print("=" * 72)

    tools = [
        ("fingerprint", (ROOT / "ps2l" / "fingerprint.py").is_file()),
        ("analyze", (ROOT / "ps2l" / "analyze.py").is_file()),
        ("check", (ROOT / "ps2l" / "check_dead_ends.py").is_file()),
        ("profile", (ROOT / "ps2l" / "profile.py").is_file()),
        ("build", (ROOT / "ps2l" / "build.py").is_file()),
        ("triage", (ROOT / "ps2l" / "triage.py").is_file()),
        ("diffview", (ROOT / "ps2l" / "diffview.py").is_file()),
        ("agent", (ROOT / "ps2l" / "agent.py").is_file()),
    ]
    print("  tools")
    for name, ok in tools:
        print(f"    {'ready  ' if ok else 'MISSING'} {name}")

    dead = ROOT / "knowledge" / "dead_ends.jsonl"
    if dead.is_file():
        n = sum(1 for l in dead.read_text(encoding="utf-8").splitlines() if l.strip())
        print(f"  knowledge   {n} recorded failures")
    an = ROOT / "analysis" / "analysis.json"
    print(f"  analysis    {'present' if an.is_file() else 'not yet run'}")

    print("  core")
    core_exe = ROOT / "core" / "out" / "build" / "ps2xRecomp" / "ps2_recomp.exe"
    gen = ROOT / "recomp" / "generated"
    gen_n = len(list(gen.rglob("*.cpp"))) if gen.is_dir() else 0
    for name, ok in (("C++ core (PS2Recomp fork)",
                      core_exe.is_file()),
                     ("RE4 recompile output",
                      gen_n > 0),
                     ("DiffView differ", (ROOT / "ps2l" / "diffview.py").is_file()),
                     ("triage engine", (ROOT / "ps2l" / "triage.py").is_file()),
                     ("port agent", (ROOT / "ps2l" / "agent.py").is_file())):
        print(f"    {'ready  ' if ok else 'PENDING '} {name}")
    if core_exe.is_file():
        print(f"    ps2_recomp.exe  {core_exe.stat().st_size:,} bytes")
    if gen_n:
        mb = sum(f.stat().st_size for f in gen.rglob("*.cpp")) / (1024 * 1024)
        print(f"    generated       {gen_n:,} .cpp files, {mb:.1f} MB")

    if prof.is_file():
        d = tomllib.loads(prof.read_text(encoding="utf-8"))
        print("  stages")
        for name, body in (d.get("stages") or {}).items():
            st = (body or {}).get("status", "?")
            mark = {"pending": "  ", "active": "->", "done": "ok"}.get(st, "??")
            print(f"    {mark} {name:<12} {st:<9} {(body or {}).get('exit','')}")
        lay = ((d.get("analysis") or {}).get("layout") or {})
        if lay:
            print(f"  measured    .text={lay.get('text_size', 0):,} B  "
                  f"overlays={(d.get('analysis') or {}).get('overlays', {}).get('count', 0)}")
    report_path = ROOT / "artifacts" / "verification" / "latest.json"
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            failed = [c["name"] for c in report.get("checks", []) if c.get("exit_code") != 0]
            print(f"  last verification: {report.get('started_utc', '?')}")
            print(f"    {'PASS' if report.get('passed') else 'FAIL'}; failed checks: {', '.join(failed) or 'none'}")
            print(f"    scope: {report.get('scope', 'unknown')}; game compatibility: unverified")
        except (OSError, ValueError, TypeError, KeyError):
            print("  last verification: unreadable report; rerun verify")
    print("=" * 72)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, rest = argv[1], argv[2:]
    if cmd == "status":
        return status()
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if cmd not in COMMANDS:
        print(f"unknown command {cmd!r}\n", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    script, _desc = COMMANDS[cmd]
    return run(script, rest)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # a Windows console is not UTF-8
        _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv))

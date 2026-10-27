#!/usr/bin/env python3
"""Run reproducible tooling checks; a pass is not a game-compatibility claim."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="lodestone verify", description=__doc__)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--function-map", type=Path, help="audit static branches against this CSV map")
    parser.add_argument("--entry-trace", type=Path, help="audit observed fault PCs against current generated dispatch sources")
    parser.add_argument("--generated", type=Path, default=ROOT / "recomp/generated/SLUS_211.34")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--core-tests", action="store_true", help="run the compiled C++ regression suite")
    parser.add_argument("--canary", action="store_true", help="compile and execute a known synthetic EE ELF")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/verification/latest.json")
    args = parser.parse_args(argv)
    if args.elf and not (args.profile or args.function_map):
        parser.error("--elf requires --profile or --function-map")
    if args.entry_trace and not (args.elf and args.function_map):
        parser.error("--entry-trace requires --elf and --function-map")
    if args.function_map and not args.elf:
        parser.error("--function-map requires --elf")
    checks = [("pipeline-regressions", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])]
    checks += [(name, [sys.executable, f"ps2l/{name}.py", "--selftest"])
               for name in ("triage", "diffview", "agent")]
    if args.function_map:
        checks.append(("function-map", [sys.executable, "-m", "ps2l", "mapcheck",
                                       str(args.elf.resolve()), str(args.function_map.resolve()),
                                       "--out", str(args.out.with_name(args.out.stem + "-mapcheck.json"))]))
    if args.profile:
        checks.append(("profile", [sys.executable, "ps2l/profile.py", str(args.profile.resolve()),
                                  *(["--elf", str(args.elf.resolve())] if args.elf else [])]))
    if args.entry_trace:
        checks.append(("observed-entries", [sys.executable, "-m", "ps2l", "entrycheck",
                      str(args.elf.resolve()), str(args.function_map.resolve()),
                      str(args.entry_trace.resolve()), str(args.generated.resolve()),
                      "--out", str(args.out.with_name(args.out.stem + "-entries.json"))]))
    if args.build:
        build_args = (["--configure-flag", "PS2X_BUILD_TEST=ON", "--target", "ps2x_tests",
                       "--target", "ps2EntryRunner"] if args.core_tests else [])
        if args.canary:
            if not args.core_tests:
                build_args += ["--target", "ps2EntryRunner"]
            build_args += ["--target", "ps2_recomp"]
        checks.append(("native-build", [sys.executable, "ps2l/build.py",
                                        *build_args]))
    if args.core_tests:
        checks.append(("core-tests", [str(ROOT / "core/out/build/ps2xTest" /
                                         ("ps2x_tests.exe" if os.name == "nt" else "ps2x_tests"))]))
    if args.canary:
        checks.append(("native-canary", [sys.executable, "ps2l/canary.py"]))
        checks.append(("native-branch64-canary", [sys.executable, "ps2l/canary.py", "--branch64",
                                                  "--out", str(ROOT / "artifacts/canary-branch64")]))
        checks.append(("native-compare64-canary", [sys.executable, "ps2l/canary.py", "--compare64",
                                                  "--out", str(ROOT / "artifacts/canary-compare64")]))
        checks.append(("native-move64-canary", [sys.executable, "ps2l/canary.py", "--move64",
                                               "--out", str(ROOT / "artifacts/canary-move64")]))
        checks.append(("native-tailcall-canary", [sys.executable, "ps2l/canary.py", "--tailcall",
                                                 "--out", str(ROOT / "artifacts/canary-tailcall")]))
    report = {"schema": 1, "started_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "tooling-and-optional-build", "game_compatibility": "unverified", "checks": []}
    for name, command in checks:
        print(f"Checking {name}...", flush=True)
        start = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=ROOT / "core" if name == "core-tests" else ROOT,
                                  capture_output=True, encoding="utf-8", errors="replace",
                                  timeout=None if name == "native-build" else 180)
            code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            code = 124
            stdout = (exc.stdout or b"").decode("utf-8", "replace")
            stderr = (exc.stderr or b"").decode("utf-8", "replace") + "\nCheck timed out."
        except OSError as exc:
            code, stdout, stderr = 127, "", str(exc)
        report["checks"].append({"name": name, "command": command, "exit_code": code,
                                 "seconds": round(time.monotonic() - start, 3),
                                 "stdout": stdout, "stderr": stderr})
        print(f"  {'PASS' if code == 0 else 'FAIL'} {name}", flush=True)
        if code:
            # Full diagnostics remain in the JSON report; keep the CLI usable
            # when native tests or the build emit thousands of lines.
            summary = [line for line in stdout.splitlines()
                       if any(marker in line for marker in ("[Failed]", "[Error]", "Total Tests:", "Passed:", "Failed:"))]
            print("\n".join(summary) if summary else stdout[-4000:])
            reasons = [line for line in stderr.splitlines() if line.lstrip().startswith("- ")]
            print("\n".join(reasons) if reasons else stderr[-2000:])
    report["passed"] = all(check["exit_code"] == 0 for check in report["checks"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {args.out}\nGame compatibility remains unverified by these checks.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))

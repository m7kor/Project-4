#!/usr/bin/env python3
"""Configure and incrementally build the native runner without cleaning.

CMake is refreshed when source membership or requested flags change. Ninja
tracks edits to existing files. Lock ownership remains with the build tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"
BUILD = CORE / "out" / "build"
GENERATED = ROOT / "recomp" / "generated"
STAMP = BUILD / "lodestone-generated-stamp.json"
TARGET = "ps2EntryRunner"


def _prepend_path() -> None:
    """CMakeCache stores a bare `clang-cl`; give the shell the LLVM bin dir."""
    extra = [r"C:\Program Files\LLVM\bin", r"C:\Program Files\CMake\bin"]
    if os.name == "nt":
        parts = os.environ.get("PATH", "").split(os.pathsep)
        for e in reversed(extra):
            if Path(e).is_dir() and e not in parts:
                parts.insert(0, e)
        os.environ["PATH"] = os.pathsep.join(parts)


def _generated_stamp() -> dict:
    """Track source membership; Ninja tracks content changes without CMake."""
    files = sorted(GENERATED.rglob("*.cpp")) if GENERATED.is_dir() else []
    names = [f.relative_to(GENERATED).as_posix() for f in files]
    return {
        "schema": 2,
        "count": len(files),
        "membership_sha256": hashlib.sha256("\n".join(names).encode()).hexdigest(),
        "dir": str(GENERATED.resolve()),
    }


def _run(cmd: list[str], label: str) -> int:
    print(f"\n=== {label} ===\n$ {' '.join(cmd)}", flush=True)
    t0 = time.time()
    try:
        rc = subprocess.call(cmd, cwd=str(CORE))
    except OSError as exc:
        print(f"{label} failed: {exc}", file=sys.stderr)
        return 127
    print(f"--- {label}: exit {rc} in {time.time() - t0:.1f}s", flush=True)
    return rc


def _configure(extra: list[str]) -> int:
    return _run(
        ["cmake", "-B", str(BUILD), "-S", str(CORE),
         *([] if (BUILD / "CMakeCache.txt").is_file() else ["-G", "Ninja"]), *extra],
        "configure",
    )


def _cached_flag(name: str) -> str | None:
    cache = BUILD / "CMakeCache.txt"
    if not cache.is_file():
        return None
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(name + ":") and "=" in line:
            return line.split("=", 1)[1]
    return None


def _first_configure_flags() -> list[str]:
    flags = ["CMAKE_BUILD_TYPE=Release", "PS2X_BUILD_STUDIO=OFF", "PS2X_BUILD_TEST=OFF",
             "PS2X_ENABLE_RUNNER_UNITY_BUILD=OFF", "PS2X_ENABLE_RUNNER_PCH=ON",
             "PS2X_ENABLE_SCCACHE=OFF", "PS2X_STRICT_RETURN_DIAGNOSTICS=ON",
             f"PS2X_RUNNER_SRC_DIR={(ROOT / 'recomp/generated/SLUS_211.34').as_posix()}"]
    if os.name == "nt":
        flags += ["CMAKE_C_COMPILER=clang-cl", "CMAKE_CXX_COMPILER=clang-cl"]
    for name, directory in {"ELFIO": "elfio", "FMT": "fmt", "LIBDWARF": "libdwarf",
                            "NLOHMANN_JSON": "nlohmann_json", "RABBITIZER": "rabbitizer",
                            "RAYLIB": "raylib", "TOML11": "toml11"}.items():
        path = CORE / "deps" / directory
        if path.is_dir():
            flags.append(f"FETCHCONTENT_SOURCE_DIR_{name}={path.as_posix()}")
    return flags


def _native_module_flags(generated: Path, explicit: Path | None) -> list[str]:
    """Use the durable RE4 bundle only for its known generated tree."""
    if explicit is not None:
        source = explicit.resolve()
        if not source.is_file():
            raise ValueError(f"native module source missing: {source}")
        return [f"PS2_NATIVE_MODULE_SOURCE={source.as_posix()}"]
    if generated.resolve() != (ROOT / "recomp/generated/SLUS_211.34").resolve():
        return []
    cached = _cached_flag("PS2_NATIVE_MODULE_SOURCE")
    legacy = ROOT / "artifacts/research/20261009/re4-native-modules.cpp"
    if cached and Path(cached).resolve() != legacy.resolve():
        return []  # Preserve an explicitly configured installer for this tree.
    source = ROOT / "recomp/native/SLUS_211.34/re4-native-modules.cpp"
    return [f"PS2_NATIVE_MODULE_SOURCE={source.as_posix()}"] if source.is_file() else []


def main(argv: list[str]) -> int:
    global BUILD, STAMP, GENERATED
    ap = argparse.ArgumentParser(prog="lodestone build", add_help=True)
    ap.add_argument("--configure-flag", action="append", default=[], metavar="X=VAL",
                    help="extra -D passed to CMake (repeatable)")
    ap.add_argument("--force-configure", action="store_true",
                    help="re-run CMake even if the generated tree is unchanged")
    ap.add_argument("--aggressive-logs", action="store_true",
                    help="enable PS2X_ENABLE_AGRESSIVE_LOGS (default OFF; see below)")
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--target", action="append", help="CMake target, repeatable")
    ap.add_argument("--build-dir", type=Path, help="separate build tree for another game")
    ap.add_argument("--generated-dir", type=Path, help="generated C++ tree to link into this runner")
    ap.add_argument("--native-module-source", type=Path,
                    help="game-specific installer source; default RE4 uses recomp/native/SLUS_211.34")
    args = ap.parse_args(argv)
    if args.build_dir:
        BUILD = args.build_dir.resolve()
        STAMP = BUILD / "lodestone-generated-stamp.json"
    if args.jobs is not None and args.jobs < 1:
        ap.error("--jobs must be positive")
    if any("=" not in flag or not flag.split("=", 1)[0] or flag.startswith("-")
           for flag in args.configure_flag):
        ap.error("--configure-flag expects NAME=VALUE without -D")

    # Diagnostic defaults, stated as measurements rather than preferences.
    #
    # PS2X_ENABLE_AGRESSIVE_LOGS is ON in upstream CMake, and it defines
    # PS2_FUNCTION_LOG_TRACKER=1, which makes every recompiled function write
    # "enter" and "exit" lines to ps2_log.txt with a flush() on EACH line.
    #
    # Measured on RE4: with it on, the guest executes 126 dispatches/second and
    # burns 111% of a CPU core doing it. With the guest sitting in one 5-
    # instruction loop body, that is ~7.9 ms of CPU per iteration — essentially
    # all of it two flushed file writes. It is the single largest cost in the
    # build's default configuration and it is pure diagnostic. Off by default
    # here; --aggressive-logs puts it back.
    default_flags = ["PS2X_ENABLE_AGRESSIVE_LOGS=OFF"]
    raw_flags = default_flags + list(args.configure_flag)
    if args.aggressive_logs:
        raw_flags = [f for f in raw_flags if not f.startswith("PS2X_ENABLE_AGRESSIVE_LOGS")]
        raw_flags.append("PS2X_ENABLE_AGRESSIVE_LOGS=ON")
    fresh = not (BUILD / "CMakeCache.txt").is_file()
    if fresh:
        raw_flags = _first_configure_flags() + raw_flags
    if args.generated_dir:
        raw_flags.append(f"PS2X_RUNNER_SRC_DIR={args.generated_dir.resolve().as_posix()}")
    desired = {}
    for flag in raw_flags:
        key, value = flag.split("=", 1)
        desired[key.split(":", 1)[0]] = (key, value)
    generated = desired.get("PS2X_RUNNER_SRC_DIR", ("", _cached_flag("PS2X_RUNNER_SRC_DIR")))[1]
    GENERATED = Path(generated) if generated else ROOT / "recomp" / "generated" / "SLUS_211.34"
    if not GENERATED.is_absolute():
        GENERATED = CORE / GENERATED
    if args.native_module_source and "PS2_NATIVE_MODULE_SOURCE" in desired:
        ap.error("use either --native-module-source or the PS2_NATIVE_MODULE_SOURCE configure flag")
    if "PS2_NATIVE_MODULE_SOURCE" not in desired:
        try:
            for flag in _native_module_flags(GENERATED, args.native_module_source):
                key, value = flag.split("=", 1)
                desired[key] = (key, value)
        except ValueError as exc:
            ap.error(str(exc))
    flags = [f"-D{key}={value}" for key, value in desired.values()]

    _prepend_path()

    stamp = _generated_stamp()
    prev = None
    if STAMP.is_file():
        try:
            prev = json.loads(STAMP.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = None

    changed = prev != stamp
    changed_flags = any(_cached_flag(name) != value for name, (_, value) in desired.items())
    if fresh or changed or changed_flags or args.force_configure:
        why = "first run" if fresh else "requested flags changed" if changed_flags else "source membership changed" if changed else "forced"
        print(f"re-configuring: {why}", flush=True)
        print(f"  after : {stamp['count']} files", flush=True)
        rc = _configure(flags)
        if rc != 0:
            return rc
        BUILD.mkdir(parents=True, exist_ok=True)
        temp = STAMP.with_suffix(".tmp")
        temp.write_text(json.dumps(stamp, indent=2), encoding="utf-8")
        temp.replace(STAMP)
    else:
        print(f"generated tree unchanged ({stamp['count']} files); CMake not re-run",
              flush=True)

    targets = args.target or [TARGET]
    rc = _run(["cmake", "--build", str(BUILD), "--target", *targets,
               *(["--parallel", str(args.jobs)] if args.jobs else [])], "build")
    if rc != 0:
        print("\nbuild failed. Note: do NOT run `ninja -t clean` — it costs a full "
              "~10 minute rebuild and destroys incremental state.", file=sys.stderr)
        return rc

    if TARGET not in targets:
        return 0
    suffix = ".exe" if os.name == "nt" else ""
    exe = BUILD / "ps2xRuntime" / f"{TARGET}{suffix}"
    exe = exe if exe.is_file() else BUILD / f"{TARGET}{suffix}"
    if not exe.is_file():
        print(f"build reported success but {exe} is missing", file=sys.stderr)
        return 1
    print(f"\nOK  {exe}  {exe.stat().st_size:,} bytes", flush=True)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))

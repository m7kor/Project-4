#!/usr/bin/env python3
"""Capture a bounded native run, preserving logs and explicit failure evidence."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

try:
    from .framecheck import frame_index, frame_sort_key
except ImportError:
    from framecheck import frame_index, frame_sort_key

ROOT = Path(__file__).resolve().parent.parent
FAULT = re.compile(r"\[(?:guest-branch:missing-target|EE thread:missing-entry|native-module:binding-rejected|syscall-override:missing-handler|Syscall TODO)\]"
                   r"|Error during program execution:|\[main\] fatal exception:|\[IOP runtime exception\]|\[SIF RPC unsupported\]"
                   r"|\[SIF RPC timing delivery failed\]"
                   r"|\[SIF IOP reset failed\]|\[IOP call incomplete\]|\[IOP\] unhandled import|\[IOP module buffer rejected\]|\[IOP module start rejected\]|\[IOP\] module arena exhausted"
                   r"|PS2RNA: E[0-9]+: Failed,|assertion [^\r\n]*failed:"
                   r"|Drive Error \(sceCdGetError = 0x[0-9a-fA-F]+\)"
                   r"|\[ERROR\]: vk[A-Za-z0-9_]+ failed \(code: -[0-9]+\)")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def validate_trace_environment(environment: dict[str, str]) -> dict:
    """Reject probe lists the runtime would silently truncate or partly parse."""
    ram_size = 32 * 1024 * 1024
    result = {"ee_dispatch_enabled": "PS2X_TRACE_EE" in environment,
              "ipu_mmio_enabled": "PS2X_TRACE_IPU" in environment,
              "ee_changes_enabled": "PS2X_TRACE_EE" in environment and
                                    "PS2X_TRACE_EE_CHANGES" in environment,
              "selectors": {}}

    def address(text: str, name: str) -> int:
        # Avoid base-zero octal ambiguity and partial strtoul acceptance.
        if not re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)", text):
            raise ValueError(f"{name}: use complete hexadecimal or decimal addresses")
        value = int(text, 16 if text.lower().startswith("0x") else 10)
        if value > 0xFFFFFFFF:
            raise ValueError(f"{name}: address exceeds 32 bits")
        return value

    names = ("PS2X_TRACE_CALLS", "PS2X_TRACE_CALL_SOURCES", "PS2X_TRACE_CALL_ARM",
             "PS2X_TRACE_CALL_MEMORY", "PS2X_TRACE_WORDS", "PS2X_TRACE_EE_PCS")
    for name in names:
        if name not in environment:
            continue
        values = environment[name].split(",") if environment[name] else []
        if len(values) > 16:
            raise ValueError(f"{name}: runtime accepts at most 16 selectors; none were launched")
        parsed = []
        for value in values:
            parts = value.split(":")
            if len(parts) > 1 and (name != "PS2X_TRACE_CALL_MEMORY" or len(parts) != 2):
                raise ValueError(f"{name}: pointer offsets are supported only for memory windows")
            base = address(parts[0], name)
            if base & 3:
                raise ValueError(f"{name}: base address must be aligned to four bytes")
            record = {"base": base}
            if name == "PS2X_TRACE_CALL_MEMORY":
                indirect = len(parts) == 2
                maximum = ram_size - (4 if indirect else 64)
                if not 0x1000 <= base <= maximum:
                    raise ValueError(f"{name}: physical RAM window is out of bounds")
                record.update(indirect=indirect, offset=address(parts[1], name) if indirect else 0,
                              bytes=64)
            elif name in ("PS2X_TRACE_WORDS", "PS2X_TRACE_EE_PCS") and base > ram_size - 4:
                raise ValueError(f"{name}: physical RAM address is out of bounds")
            parsed.append(record)
        result["selectors"][name] = parsed
    return result


def wait_for_fault_or_exit(proc, log_path: Path, timeout: float) -> tuple[int, bool, bool]:
    """Opt-in diagnostic stop; consume logs incrementally with bounded memory."""
    deadline = time.monotonic() + timeout
    tail = ""
    with log_path.open("rb") as log:
        while proc.poll() is None:
            block = log.read(64 * 1024)
            if block:
                text = tail + block.decode("utf-8", errors="replace")
                hit = FAULT.search(text)
                tail = text[-4096:]
                if hit and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    return 1, False, True
            if time.monotonic() >= deadline:
                proc.kill()
                proc.wait()
                return 124, True, False
            # Drain a large diagnostic burst before waiting for new output.
            if len(block) < 64 * 1024:
                time.sleep(0.05)
    return proc.returncode, False, False


def summarize_diagnostics(directory: Path) -> dict:
    """Summarize published state without treating host activity as gameplay."""
    summary = {"samples": 0, "malformed_rows": 0, "host_frame_observed": False,
               "last_state": None, "captured_frame_files": []}
    state = directory / "state.jsonl"
    if state.is_file():
        with state.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("state must be an object")
                except (ValueError, TypeError):
                    summary["malformed_rows"] += 1
                    continue
                summary["samples"] += 1
                summary["last_state"] = row
                summary["host_frame_observed"] |= row.get("host_frame") is True
    frames = sorted((path for path in directory.glob("frame-*.png") if path.is_file()),
                    key=frame_sort_key)
    summary["captured_frame_files"] = [path.name for path in frames]
    indexed = [path for path in frames if frame_index(path) is not None]
    summary["latest_captured_frame_file"] = indexed[-1].name if indexed else None
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="lodestone run", description=__doc__)
    parser.add_argument("elf", type=Path)
    parser.add_argument("--runner", type=Path, default=ROOT / "core/out/build/ps2xRuntime/ps2EntryRunner.exe")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/runs")
    parser.add_argument("--diagnostics", action="store_true", help="capture EE/GS snapshots and raw game frames")
    parser.add_argument("--stop-on-fault", action="store_true",
                        help="end this diagnostic capture when a known guest fault is logged")
    parser.add_argument("--trace-disc", action="store_true", help="record bounded CDVD traces and audit boot evidence")
    parser.add_argument("--trace-gif", action="store_true", help="record up to 512 raw GIF packet prefixes with sampled EE PCs")
    args = parser.parse_args(argv)
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be finite and positive")
    elf, runner = args.elf.resolve(), args.runner.resolve()
    for path in (elf, runner):
        if not path.is_file():
            parser.error(f"file missing: {path}")
    environment = os.environ.copy()
    try:
        trace_configuration = validate_trace_environment(environment)
    except ValueError as error:
        parser.error(str(error))
    now = datetime.now(timezone.utc)
    out = args.out / (now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    out.mkdir(parents=True)
    report = {"schema": 1, "started_utc": now.isoformat(), "elf": str(elf),
              "elf_sha256": digest(elf), "runner": str(runner), "runner_sha256": digest(runner),
              "game_compatibility": "unverified", "timed_out": False,
              "trace_configuration": trace_configuration}
    if args.trace_disc:
        environment["PS2X_TRACE_CDVD"] = "1"
    if args.trace_gif:
        environment["PS2X_TRACE_GIF"] = "1"
    report["gif_trace_requested"] = args.trace_gif
    report["disc_trace_requested"] = args.trace_disc
    if args.diagnostics:
        environment["PS2X_CAPTURE_DIR"] = str((out / "diagnostics").resolve())
    report["diagnostics_requested"] = args.diagnostics
    report["stop_on_fault_requested"] = args.stop_on_fault
    report["stopped_on_fault"] = False
    start = time.monotonic()
    with (out / "stdout.txt").open("wb") as stdout, (out / "stderr.txt").open("wb") as stderr:
        try:
            # Stream to disk so a hot guest diagnostic cannot exhaust host RAM.
            report["process_spawn_requested_unix_ns"] = time.time_ns()
            with subprocess.Popen([str(runner), str(elf)], cwd=ROOT, stdout=stdout,
                                  stderr=stderr, env=environment) as proc:
                report["process_start_observed_unix_ns"] = time.time_ns()
                report["process_pid"] = proc.pid
                if args.stop_on_fault:
                    code, report["timed_out"], report["stopped_on_fault"] = wait_for_fault_or_exit(
                        proc, out / "stderr.txt", args.timeout)
                else:
                    try:
                        code = proc.wait(timeout=args.timeout)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                        report["timed_out"] = True
                        code = 124
                report["process_exit_observed_unix_ns"] = time.time_ns()
                report["process_returncode"] = proc.returncode
                report["process_exit_forced"] = report["timed_out"] or report["stopped_on_fault"]
                report["process_timing_scope"] = "Host observations around process creation and reaping, not exact guest start or audio endpoint timestamps"
        except OSError as exc:
            stderr.write(str(exc).encode("utf-8"))
            code = 127
    report["seconds"] = round(time.monotonic() - start, 3)
    report["exit_code"] = code
    faults = {}
    examples = []
    with (out / "stderr.txt").open(encoding="utf-8", errors="replace") as log:
        for line in log:
            hit = FAULT.search(line)
            if hit:
                key = hit.group()
                faults[key] = faults.get(key, 0) + 1
                if len(examples) < 8:
                    examples.append(line.strip()[:4000])
    report["fault_counts"] = faults
    report["fault_examples"] = examples
    if args.diagnostics:
        report["diagnostics"] = summarize_diagnostics(out / "diagnostics")
        try:
            from .framecheck import audit_frames
        except ImportError:
            from framecheck import audit_frames
        frame_audit = audit_frames(out / "diagnostics")
        report["diagnostics"]["frame_audit"] = frame_audit
        (out / "diagnostics").mkdir(exist_ok=True)
        (out / "diagnostics" / "frame-audit.json").write_text(
            json.dumps(frame_audit, indent=2), encoding="utf-8")
    report["result"] = ("fault-observed" if faults else "timeout" if code == 124
                        else "process-failed" if code else "process-exited")
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.trace_disc:
        try:
            from .bootcheck import audit_capture
        except ImportError:
            from bootcheck import audit_capture
        boot = audit_capture(out, elf.parent)
        (out / "boot-audit.json").write_text(json.dumps(boot, indent=2), encoding="utf-8")
        report["boot_verdict"] = boot["verdict"]
        if boot["verdict"] == "disc-read-failure-observed":
            report["result"] = "fault-observed"
            if code == 0:
                code = 1
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Boot audit: {boot['verdict']}")
    print(f"Capture: {out}\nResult: {report['result']}; exit={code}; seconds={report['seconds']}")
    for example in examples:
        print(example)
    if args.diagnostics:
        summary = report["diagnostics"]
        print(f"Diagnostics: {summary['samples']} state samples; "
              f"{len(summary['captured_frame_files'])} frame files")
    print("A successful process exit alone does not prove playable output.")
    return code if code else 1 if faults else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))

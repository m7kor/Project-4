"""Audit disc boot evidence; accepted reads do not certify DMA delivery or gameplay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys

SEARCH = re.compile(r"\[CDVD search\] path=(.*?) found=1 directory=0 lsn=(\d+) size=(\d+)")
READ = re.compile(r"\[CDVD import\] (?:cycles=[0-9]+ )?ordinal=63 .*?a0=(0x[0-9a-f]+) a1=(0x[0-9a-f]+).*?v0=(0x[0-9a-f]+) handled=1", re.I)
DRIVE = re.compile(r"Drive Error \(sceCdGetError = (0x[0-9a-f]+)\)", re.I)


def covered(intervals: list[tuple[int, int]], start: int, end: int) -> int:
    """Union of clipped intervals: retries cannot inflate observed progress."""
    total, cursor = 0, start
    for left, right in sorted(intervals):
        left, right = max(left, start, cursor), min(right, end)
        if right > left:
            total += right - left
            cursor = right
    return total


def disc_path(root: Path, guest: str) -> Path:
    parts = guest.replace("\\", "/").lstrip("/").split("/")
    parts[-1] = re.sub(r";\d+$", "", parts[-1])
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ValueError("unsafe guest disc path")
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("guest disc path escapes game root")
    return target


def audit_capture(directory: Path, game_root: Path | None = None) -> dict:
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("capture report must be an object")
    root = game_root or Path(report["elf"]).parent
    searches, accepted, failures, drive_errors = {}, [], [], {}
    trace_rows = 0
    with (directory / "stderr.txt").open(encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            if hit := SEARCH.search(line):
                path, lsn, size = hit.groups()
                searches[path] = (int(lsn), int(size), number)
            if hit := READ.search(line):
                trace_rows += 1
                lsn, sectors, result = (int(value, 16) for value in hit.groups())
                if result == 1 and sectors:
                    accepted.append((lsn, lsn + sectors))
                elif result == 0:
                    if len(failures) < 8:
                        failures.append({"lsn": lsn, "sectors": sectors, "line": number})
            if hit := DRIVE.search(line):
                code = hit[1].lower()
                drive_errors[code] = drive_errors.get(code, 0) + 1
    archives, errors = [], []
    for guest, (lsn, size, number) in searches.items():
        if not re.search(r"\.afs(?:;\d+)?$", guest, re.I):
            continue
        try:
            source = disc_path(root, guest)
            with source.open("rb") as stream:
                header = stream.read(8)
            if len(header) != 8 or header[:4] != b"AFS\0":
                raise ValueError("invalid AFS header")
            entries = struct.unpack_from("<I", header, 4)[0]
            table_bytes = 8 + entries * 8
            if source.stat().st_size != size or table_bytes > size:
                raise ValueError("disc size mismatch or truncated AFS table")
            sectors = (table_bytes + 2047) // 2048
            seen = covered(accepted, lsn, lsn + sectors)
            archives.append({"path": guest, "search_line": number, "lsn": lsn,
                             "entries": entries, "table_sectors": sectors,
                             "accepted_table_sectors": seen,
                             "all_table_sectors_requested_and_accepted": seen == sectors})
        except (OSError, ValueError) as exc:
            errors.append({"path": guest, "error": str(exc)})
    verdict = ("disc-read-failure-observed" if failures or drive_errors else
               "disc-read-acceptance-observed" if accepted else "insufficient-disc-evidence")
    return {"schema": 1, "capture": str(directory.resolve()), "verdict": verdict,
            "elf_sha256": report.get("elf_sha256"), "runner_sha256": report.get("runner_sha256"),
            "seconds": report.get("seconds"), "timed_out": report.get("timed_out"),
            "trace_rows": trace_rows, "archives": archives, "failed_reads": failures,
            "drive_error_counts": drive_errors, "source_errors": errors,
            "frame_audit": {key: value for key, value in
                            (((report.get("diagnostics") or {}).get("frame_audit") or {}).items())
                            if key != "frames"},
            "game_compatibility": "unverified",
            "limits": ["Import success measures acceptance, not completed DMA or AFS parsing.",
                       "Bounded traces can omit later requests; missing evidence is not failure.",
                       "Timeout or repeated PC alone does not prove a hang.",
                       "AFS metadata is read from current local assets; historical identity is not certified."]}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--game-root", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit_capture(args.capture, args.game_root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Boot audit unavailable: {exc}", file=sys.stderr)
        return 2
    encoded = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 1 if result["verdict"] == "disc-read-failure-observed" or result["source_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

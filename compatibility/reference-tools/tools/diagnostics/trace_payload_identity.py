"""Compare contiguous trace memory samples with a bounded original file extent.

Matches prove only the sampled bytes, never successful decoding or a full read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

MAX_EXTENT = 64 * 1024 * 1024
MAX_SAMPLE = 64 * 1024


def compare(trace: dict, source: Path, offset: int, size: int, keys: list[str]) -> dict:
    if offset < 0 or not 0 < size <= MAX_EXTENT:
        raise ValueError("source extent must be positive and at most 64 MiB")
    if offset + size > source.stat().st_size:
        raise ValueError("source extent exceeds file bounds")
    addresses = []
    for key in keys:
        if not re.fullmatch(r"mem_[0-9a-fA-F]+", key):
            raise ValueError("use absolute memory keys, not pointer-relative samples")
        addresses.append(int(key[4:], 16))
    if not addresses or addresses != sorted(set(addresses)):
        raise ValueError("memory keys must be unique and in ascending address order")
    with source.open("rb") as handle:
        handle.seek(offset)
        original = handle.read(size)
    if len(original) != size:
        raise ValueError("source extent changed or was truncated while reading")
    samples: dict[bytes, list[int]] = {}
    missing_rows = 0
    lengths = None
    for row in trace["observations"]:
        memory = row.get("memory_snapshots", {})
        if any(key not in memory for key in keys):
            missing_rows += 1
            continue
        chunks = [bytes.fromhex(memory[key]) for key in keys]
        row_lengths = tuple(map(len, chunks))
        if any(not chunk for chunk in chunks) or sum(row_lengths) > MAX_SAMPLE:
            raise ValueError("sample must be nonempty and at most 64 KiB")
        if lengths is not None and lengths != row_lengths:
            raise ValueError("sample widths changed between observations")
        lengths = row_lengths
        if any(addresses[i] + row_lengths[i] != addresses[i + 1]
               for i in range(len(keys) - 1)):
            raise ValueError("memory samples must be contiguous without gaps or overlap")
        samples.setdefault(b"".join(chunks), []).append(row["line"])
    results = []
    for sample, lines in samples.items():
        matches = []
        if any(sample):
            start = original.find(sample)
            while start >= 0 and len(matches) < 17:
                matches.append(start)
                start = original.find(sample, start + 1)
        results.append({
            "sha256": hashlib.sha256(sample).hexdigest(), "bytes": len(sample),
            "prefix_hex": sample[:16].hex(), "observations": len(lines),
            "first_line": lines[0], "last_line": lines[-1],
            "classification": "zero_unproven" if not any(sample) else
                "matched" if matches else "unmatched",
            "relative_offsets": matches[:16],
            "absolute_offsets": [offset + value for value in matches[:16]],
            "match_list_truncated": len(matches) > 16,
        })
    return {
        "schema": 1, "source": str(source.resolve()), "offset": offset, "size": size,
        "extent_sha256": hashlib.sha256(original).hexdigest(),
        "trace_log_sha256": trace.get("sha256"), "memory_keys": keys,
        "missing_rows": missing_rows, "samples": results,
        "trace_cap_reached": trace.get("entries_at_shared_cap"),
        "scope": "Exact identity of sampled bytes within the specified source extent only. "
                 "Zero samples are inconclusive. Matches do not prove full-file delivery, "
                 "decoder success, or observations after the trace cap.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--offset", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--size", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--memory", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.out.suffix.lower() != ".json":
        parser.error("output must be a new JSON file")
    try:
        result = compare(json.loads(args.trace.read_text(encoding="utf-8")),
                         args.source, args.offset, args.size, args.memory)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"samples": len(result["samples"]), "matched": sum(
        sample["classification"] == "matched" for sample in result["samples"])}))


if __name__ == "__main__":
    main()

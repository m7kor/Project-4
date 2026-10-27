#!/usr/bin/env python3
"""Inspect a bounded pre-draw GS capture without certifying renderer accuracy."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def inspect(directory: Path) -> tuple[dict, bytes, bytes | None]:
    metadata_path = directory / "draw.json"
    if metadata_path.stat().st_size > 64 * 1024:
        raise ValueError("oversized draw metadata")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    width, height = metadata.get("width"), metadata.get("height")
    if metadata.get("schema") != 1 or type(width) is not int or type(height) is not int or not (1 <= width <= 1024 and 1 <= height <= 1024):
        raise ValueError("invalid capture dimensions or schema")
    files = {}
    def exact(name: str, size: int) -> bytes:
        path = directory / name
        if path.stat().st_size != size:
            raise ValueError(f"incorrect byte count: {name}")
        data = path.read_bytes()
        files[name] = {"bytes": size, "sha256": hashlib.sha256(data).hexdigest()}
        return data
    exact("vram.bin", 4 * 1024 * 1024)
    clut = exact("clut-u16le.bin", 1024)
    rgba = exact("texture-rgba.bin", width * height * 4)
    indices = None
    histogram = None
    if metadata["tex0"]["psm"] in (0x13, 0x14, 0x1B, 0x24, 0x2C):
        indices = exact("texture-indices.bin", width * height)
        if metadata["tex0"]["psm"] in (0x14, 0x24, 0x2C) and max(indices) > 15:
            raise ValueError("four-bit index outside its range")
        histogram = dict(sorted(Counter(indices).items()))
    halfwords = struct.unpack("<512H", clut)
    palette32 = [hex(halfwords[i] | halfwords[i + 256] << 16) for i in range(256)]
    colors = Counter(rgba[i:i+4] for i in range(0, len(rgba), 4))
    return {"schema": 1, "scope": "captured atlas and loaded CLUT; same renderer is not an independent oracle",
            "draw": metadata, "files": files, "index_histogram": histogram,
            "loaded_clut32": palette32, "distinct_rgba": len(colors),
            "top_rgba": [{"rgba": list(c), "pixels": n} for c, n in colors.most_common(20)]}, rgba, indices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    try:
        report, rgba, indices = inspect(args.directory)
        if args.preview:
            from PIL import Image
            size = (report["draw"]["width"], report["draw"]["height"])
            args.preview.mkdir(parents=True, exist_ok=True)
            Image.frombytes("RGBA", size, rgba).save(args.preview / "atlas-rgba.png")
            if indices is not None:
                multiplier = 17 if report["draw"]["tex0"]["psm"] in (0x14, 0x24, 0x2C) else 1
                Image.frombytes("L", size, bytes(x * multiplier for x in indices)).save(args.preview / "atlas-indices.png")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        parser.error(str(error))
    print(json.dumps({"distinct_rgba": report["distinct_rgba"], "top_rgba": report["top_rgba"][:3]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

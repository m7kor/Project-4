"""Read PS2 SNR2 modules from AFS without executing or patching game bytes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def span(data, offset, size):
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ValueError(f"Out-of-range SNR2 span {offset:#x}+{size:#x}")
    return data[offset:offset + size]


def cstring(data, offset):
    span(data, offset, 1)
    end = data.find(b"\0", offset, min(len(data), offset + 4096))
    if end < 0:
        raise ValueError(f"Unterminated SNR2 string at {offset:#x}")
    return data[offset:end].decode("ascii", errors="replace")


def parse_snr2(data):
    words = struct.unpack("<15I", span(data, 0, 60))
    if words[0] != 0x32524E53:
        raise ValueError("Expected SNR2 magic")
    if words[11] != len(data):
        raise ValueError("SNR2 file-size header differs from AFS entry size")
    reloc_at, reloc_count, symbol_at, symbol_count = words[1:5]
    span(data, reloc_at, reloc_count * 12)
    span(data, symbol_at, symbol_count * 12)
    symbols = []
    for i in range(symbol_count):
        name_at, value, auxiliary, kind, reserved = struct.unpack_from("<IIHBB", data, symbol_at + i * 12)
        symbols.append({"index": i, "name": cstring(data, name_at) if name_at else "",
                        "value": value, "raw_type": kind, "raw_auxiliary": auxiliary,
                        "raw_reserved": reserved})
    relocations = []
    for i in range(reloc_count):
        offset, info, addend = struct.unpack_from("<IIi", data, reloc_at + i * 12)
        kind, symbol_index = info & 255, info >> 8
        span(data, offset, 4)
        if symbol_index >= symbol_count:
            raise ValueError(f"Relocation {i} references absent symbol {symbol_index}")
        relocations.append({"offset": offset, "type": kind, "symbol_index": symbol_index,
                            "addend": addend})
    constructor = words[6]
    ctor_words = list(struct.unpack("<4I", span(data, constructor, 16))) if constructor else []
    return {
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "original_image_name": cstring(data, words[5]) if words[5] else "",
        "constructor_offset": constructor, "destructor_offset": words[7],
        "constructor_words": ctor_words, "relocation_count": reloc_count,
        "symbol_count": symbol_count,
        "relocation_type_counts": dict(Counter(r["type"] for r in relocations)),
        "max_relocation_symbol_index": max((r["symbol_index"] for r in relocations), default=None),
        "nonzero_addends": sum(r["addend"] != 0 for r in relocations),
        "raw_symbol_type_counts": dict(Counter(s["raw_type"] for s in symbols)),
        "symbols": symbols, "relocations": relocations,
    }


def verify_runtime_header(data, observed_header, base):
    """Compare original and relocated header; does not certify executable code."""
    parse_snr2(data)
    if not 0 <= base <= 0xFFFFFFFF or base + len(data) > 0x100000000:
        raise ValueError("Module load range exceeds 32-bit address space")
    original = struct.unpack("<15I", span(data, 0, 60))
    observed = struct.unpack("<15I", span(observed_header, 0, 60))
    pointer_indices = {1, 3, 5, 6, 7, 8, 13, 14}
    fields = []
    for index, value in enumerate(original):
        expected = (value + base) & 0xFFFFFFFF if index in pointer_indices and value else value
        fields.append({"offset": index * 4, "original": value,
                       "expected": expected, "observed": observed[index],
                       "matches": expected == observed[index]})
    return {"base": base, "all_fields_match": all(f["matches"] for f in fields),
            "fields": fields,
            "scope": "Header relocation identity only; code, imports and execution remain unverified."}


def read_modules(archive, selected_index=None):
    with archive.open("rb") as stream:
        total = archive.stat().st_size
        header = stream.read(8)
        if len(header) != 8 or header[:4] != b"AFS\0":
            raise ValueError("Expected AFS header")
        count = struct.unpack_from("<I", header, 4)[0]
        if count > (total - 8) // 8:
            raise ValueError("Truncated AFS table")
        table = stream.read(count * 8)
        if selected_index is not None and not 0 <= selected_index < count:
            raise ValueError("AFS index is outside the table")
        for i in range(count):
            offset, size = struct.unpack_from("<II", table, i * 8)
            if offset > total or size > total - offset:
                raise ValueError(f"AFS entry {i} exceeds archive")
            if not size or selected_index is not None and i != selected_index:
                continue
            stream.seek(offset)
            magic = stream.read(min(size, 4))
            if magic != b"SNR2":
                if selected_index == i:
                    raise ValueError("Selected AFS entry is not SNR2")
                continue
            stream.seek(offset)
            data = stream.read(size)
            result = parse_snr2(data)
            result.update({"afs_index": i, "archive_offset": offset})
            yield result, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--index", type=int)
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--observed-entry", type=lambda s: int(s, 0))
    parser.add_argument("--observed-global", type=lambda s: int(s, 0))
    parser.add_argument("--extract-to", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if (args.observed_entry is None) != (args.observed_global is None):
        parser.error("Both observed addresses are required")
    if args.extract_to and args.index is None:
        parser.error("Extraction requires one explicit AFS index")
    modules = []
    for result, data in read_modules(args.archive, args.index):
        if args.extract_to:
            if args.extract_to.resolve() == args.archive.resolve():
                raise ValueError("Cannot replace source archive")
            if args.extract_to.exists() and args.extract_to.read_bytes() != data:
                raise ValueError("Existing extraction differs; preserved")
            args.extract_to.parent.mkdir(parents=True, exist_ok=True)
            if not args.extract_to.exists():
                args.extract_to.write_bytes(data)
        if args.observed_entry is not None:
            w = result["constructor_words"]
            if len(w) == 4 and w[0] >> 16 == 0x3C07 and w[1] == 0x27BDFFD0 and w[2] >> 16 == 0x8CE5 and w[3] == 0x2402FFFF:
                base = args.observed_entry - result["constructor_offset"]
                low = w[2] & 65535
                low = low if low < 32768 else low - 65536
                predicted = ((w[0] & 65535) << 16) + low + base
                if 0 <= base <= 0xFFFFFFFF and predicted == args.observed_global:
                    result["observed_constructor_candidate_base"] = base
        if not args.details:
            result.pop("symbols")
            result.pop("relocations")
        modules.append(result)
    if not modules:
        raise ValueError("No nonempty SNR2 modules")
    output = json.dumps({"archive": str(args.archive), "modules": modules,
                        "scope": "Read-only metadata; constructor candidate is not runtime identity verification or compiled support."}, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()

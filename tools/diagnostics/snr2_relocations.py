"""Model RE4's compact SNR2 local relocations for native code generation.

Derived from the original loader at 0x2A5288..0x2A5408 and patch routine
0x2A4968. These are local relocations only: imports and symbol interposition
must be resolved separately before compiling or executing a complete module.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct

from tools.diagnostics.snr2_inventory import parse_snr2, span


def compact_relocations(data):
    """Return bounded local patch records, including HI16's explicit LO chain."""
    parse_snr2(data)
    cursor = struct.unpack_from("<I", data, 0x34)[0]
    if not cursor:
        return []
    patch_offset = 0
    records = []

    def location(previous):
        nonlocal cursor
        tag = span(data, cursor, 1)[0]
        cursor += 1
        delta = tag & 0xFC
        if delta:
            offset = previous + delta
        else:
            offset = struct.unpack("<I", span(data, cursor, 4))[0]
            cursor += 4
            if offset == 0:
                return None, tag & 3
        span(data, offset, 4)
        if offset & 3:
            raise ValueError("Unaligned compact relocation patch")
        return offset, tag & 3

    while True:
        patch_offset, kind = location(patch_offset)
        if patch_offset is None:
            return records
        word = struct.unpack_from("<I", data, patch_offset)[0]
        record = {"offset": patch_offset, "type": (6, 5, 4, 2)[kind]}
        if kind == 1:
            # a2 scans ahead, while s0 stays on the next outer record. The
            # same bytes must subsequently be consumed as ordinary patches.
            outer_cursor = cursor
            low_offset = patch_offset
            chain = []
            while True:
                low_offset, more = location(low_offset)
                if low_offset is None:
                    raise ValueError("HI16 chain ended without a LO16 patch")
                chain.append(low_offset)
                if not more:
                    break
            # The original loader reads the signed halfword at the final LO.
            low = struct.unpack_from("<h", data, chain[-1])[0]
            record.update({"target_offset": ((word & 0xFFFF) << 16) + low,
                           "pair_scan_offsets": chain, "final_low_offset": chain[-1]})
            cursor = outer_cursor
        elif kind == 0:
            record["target_offset"] = word & 0xFFFF
        elif kind == 2:
            record["target_offset"] = (word & 0x3FFFFFF) << 2
        else:
            record["target_offset"] = word
        records.append(record)


def patch_word(word, kind, value):
    """Mirror supported RE4 patch operations; reject the loader's BREAK marker."""
    value &= 0xFFFFFFFF
    if kind in (4, 5, 6) and word & 0xFC00003F == 0xD:
        raise ValueError("Original loader rejects relocation of BREAK marker")
    if kind == 2:
        return value
    if kind == 4:
        return (word & 0xFC000000) | ((value >> 2) & 0x3FFFFFF)
    if kind == 5:
        return (word & 0xFFFF0000) | (((value + 0x8000) & 0xFFFFFFFF) >> 16)
    if kind == 6:
        return (word & 0xFFFF0000) | (value & 0xFFFF)
    raise ValueError(f"Unsupported SNR2 relocation type {kind}")


def relocate_local_code(data, base):
    """Return a copy with local patches only, never a ready-to-run module."""
    if not 0 <= base <= 0xFFFFFFFF or base + len(data) > 0x100000000:
        raise ValueError("Module load range exceeds 32-bit address space")
    records = compact_relocations(data)
    result = bytearray(data)
    for record in records:
        offset, kind = record["offset"], record["type"]
        word = struct.unpack_from("<I", result, offset)[0]
        value = base + record["target_offset"]
        struct.pack_into("<I", result, offset, patch_word(word, kind, value))
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve() == args.module.resolve():
        parser.error("Cannot replace source module")
    data = args.module.read_bytes()
    metadata = parse_snr2(data)
    records = compact_relocations(data)
    output = {"schema": 1, "module": str(args.module), "sha256": metadata["sha256"],
              "original_image_name": metadata["original_image_name"],
              "constructor_offset": metadata["constructor_offset"],
              "local_relocations": records,
              "local_type_counts": dict(Counter(r["type"] for r in records)),
              "symbol_relocations": metadata["relocations"], "symbols": metadata["symbols"],
              "scope": "Native translation input plan; local operand values depend on load base. Symbol resolution, code generation and runtime registration are not implemented by this tool."}
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Local relocation records: {len(records)}; symbol records: {metadata['relocation_count']}")


if __name__ == "__main__":
    main()

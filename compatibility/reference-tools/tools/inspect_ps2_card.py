"""Read-only PS2 card geometry/header inspection; never formats or repairs storage."""
import argparse
import hashlib
import json
from pathlib import Path


def inspect_card(path):
    path = Path(path)
    size = path.stat().st_size
    raw_sizes = {mb * 1024 * 1024 // 512 * 528 for mb in (8, 16, 32, 64)}
    data_sizes = {mb * 1024 * 1024 for mb in (8, 16, 32, 64)}
    stride = 528 if size in raw_sizes else 512 if size in data_sizes else None
    digest = hashlib.sha256()
    erased = 0
    blank = True
    signature = b"Sony PS2 Memory Card Format"
    with path.open("rb") as stream:
        header = stream.read(64)
        stream.seek(0)
        for chunk in iter(lambda: stream.read((stride or 512) * 128), b""):
            digest.update(chunk)
            blank = blank and all(value == 255 for value in chunk)
            if stride:
                erased += sum(chunk[i:i + stride] == b"\xff" * stride
                              for i in range(0, len(chunk), stride))
    return {
        "schema": 1, "path": str(path.resolve()), "bytes": size,
        "sha256": digest.hexdigest(), "page_bytes": stride,
        "data_bytes_per_page": 512 if stride else None,
        "spare_bytes_per_page": stride - 512 if stride else None,
        "pages": size // stride if stride else None,
        "erased_pages": erased if stride else None,
        "all_bytes_erased": blank,
        "format_signature_present": header.startswith(signature),
        "storage_kind": "raw-with-spare" if stride == 528 else "data-only" if stride == 512 else "unsupported-size",
        "filesystem_integrity": "not-checked", "ecc_integrity": "not-checked",
        "scope": "read-only geometry, erased-byte count and PS2 format signature; not a save/load compatibility certificate"
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out and args.out.resolve() == args.card.resolve():
        parser.error("report output cannot replace the input card")
    report = inspect_card(args.card)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x', encoding='utf-8') as output:
            output.write(text + '\n')
    print(text)
    return 0 if report["page_bytes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

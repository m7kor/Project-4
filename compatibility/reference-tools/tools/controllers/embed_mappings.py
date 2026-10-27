"""Regenerate or verify the offline, pinned controller mapping bundle."""
from pathlib import Path
import argparse
import hashlib
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without modifying files")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    resources = root / "core/ps2xRuntime/resources/controllers"
    manifest_path = resources / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["files"]:
        name = item["name"]
        if Path(name).name != name:
            raise ValueError("Manifest source must be a filename")
        data = (resources / name).read_bytes()
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"Pinned source hash mismatch: {name}")
    lines = [line for line in (resources / "gamecontrollerdb.txt").read_text(encoding="utf-8").splitlines()
             if line and not line.startswith("#")]
    for line in lines:
        guid = line.split(",", 1)[0]
        if len(line) > 4096 or (len(guid) != 32 and guid != "xinput") or "\x00" in line:
            raise ValueError("Invalid mapping record")
    text = "// Generated from pinned SDL_GameControllerDB; zlib license in resources/controllers/LICENSE.\n"
    text += "#pragma once\ninline constexpr const char *kHostGamepadMappings[] = {\n"
    text += "".join("    " + json.dumps(line, ensure_ascii=True) + ",\n" for line in lines)
    text += "};\n"
    header = root / "core/ps2xRuntime/src/lib/ps2_gamepad_mappings.h"
    expected = text.encode("utf-8")
    digest = hashlib.sha256(expected).hexdigest()
    if args.check:
        if header.read_bytes() != expected or manifest["embedded_header"]["sha256"] != digest:
            raise ValueError("Embedded mappings differ from pinned source")
    else:
        header.write_bytes(expected)
        manifest["embedded_header"] = {"path": str(header.relative_to(root)), "sha256": digest, "entries": len(lines)}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"PASS: {len(lines)} pinned mappings, source/license hashes and embedded header")


if __name__ == "__main__":
    main()

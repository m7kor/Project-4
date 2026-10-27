#!/usr/bin/env python3
"""Verify a bounded public-source snapshot without executing downloaded code."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snapshot_sources import REPOSITORIES, safe_source


def audit(root: Path) -> dict:
    root = root.resolve()
    problems, projects = [], []
    for slug, (repository, pinned) in REPOSITORIES.items():
        folder = root / slug
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            revision = manifest["revision"]
            if manifest["repository"] != repository:
                raise ValueError("repository identity mismatch")
            if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
                raise ValueError("revision is not a full commit hash")
            if pinned and revision != pinned:
                raise ValueError("requested pinned revision mismatch")
            if manifest.get("errors") or manifest.get("tree_truncated") or manifest.get("file_limit_reached"):
                problems.append(f"{slug}: incomplete source snapshot")
            entries = manifest["files"]
            if len(entries) != manifest["eligible_files"]:
                problems.append(f"{slug}: eligible file count mismatch")
            seen, patches, tests, verified = set(), [], [], 0
            source_root = (folder / "sources").resolve()
            for entry in entries:
                name = entry["path"]
                if not safe_source(name) or name in seen:
                    problems.append(f"{slug}: unsafe or duplicate source path {name!r}")
                    continue
                seen.add(name)
                path = (source_root / name).resolve()
                if not path.is_relative_to(source_root):
                    problems.append(f"{slug}: source escapes snapshot {name!r}")
                    continue
                if not path.is_file() or path.stat().st_size != entry["bytes"]:
                    problems.append(f"{slug}: missing or wrong-sized source {name!r}")
                    continue
                if entry["bytes"] > 2 * 1024 * 1024:
                    problems.append(f"{slug}: oversized source {name!r}")
                    continue
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    problems.append(f"{slug}: hash mismatch {name!r}")
                    continue
                verified += 1
                if path.suffix in {".patch", ".diff"}:
                    targets = [line[6:] for line in data.decode("utf-8").splitlines()
                               if line.startswith("+++ b/")]
                    patches.append({"path": name, "targets": targets, "sha256": entry["sha256"]})
                if any("test" in part.lower() for part in Path(name).parts):
                    tests.append(name)
            projects.append({"slug": slug, "repository": repository, "revision": revision,
                             "url": manifest.get("url"), "license_metadata": manifest.get("license"),
                             "verified_files": verified, "patches": patches, "test_sources": tests,
                             "gameplay_validation": "not-run", "adoption": "requires-local-tests"})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"{slug}: {exc}")
    return {"schema": 1, "scope": "bounded-text-source-integrity",
            "excluded": "game assets, generated code, build output and dependency subtrees",
            "pass": not problems, "problems": problems, "projects": projects}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.snapshot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    count = sum(p["verified_files"] for p in report["projects"])
    print(f"{'PASS' if report['pass'] else 'FAIL'}: {len(report['projects'])} projects, {count} verified source files")
    for problem in report["problems"]:
        print(problem)
    return int(not report["pass"])


if __name__ == "__main__":
    raise SystemExit(main())

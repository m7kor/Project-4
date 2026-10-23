"""Capture public source references for review; never execute fetched files."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import urllib.parse
import urllib.request

REPOSITORIES = {
    "god-of-war": ("KIexster/god-of-war-recomp", None),
    "dq8": ("Sinan-Karakaya/DQ8-Recompiled", None),
    "spider-man-2": ("saltyboosack-blip/Spider-Man-2-PS2-Recomp", None),
    "shadow": ("nicolasserpa/shadow-the-hedgehog-recomp", None),
    "dmc": ("Gui-Tora/dmc-recomp", None),
    "ico": ("nathanialf/ico-recomp", None),
    "rabbitizer": ("Decompollaborate/rabbitizer", "fb4ab5e24994a5987c5789983789d8d3dfc7a40f"),
    "killzone": ("drakolordx7/KillzoneRecomp", None),
    "dkc3": ("explosive-kite3497/DKC3Recomp", None),
}
TEXT_SUFFIXES = {".md", ".txt", ".rst", ".py", ".cpp", ".c", ".cc", ".h", ".hpp",
                 ".inc", ".patch", ".diff", ".toml", ".json", ".yml", ".yaml", ".cmake",
                 ".ps1", ".sh", ".bat", ".cmd", ".csv"}
EXCLUDED = {"generated", "recompiled", "build", "out", "vendor", "thirdparty", "third_party",
            "node_modules", "game", "assets", "original", ".git", "_fork", "ext"}


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Lodestone-source-audit"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(4 * 1024 * 1024 + 1)


def safe_source(path: str) -> bool:
    p = PurePosixPath(path)
    return (bool(path) and not p.is_absolute() and ".." not in p.parts and "\\" not in path
            and not any(":" in part for part in p.parts)
            and not any(part.lower() in EXCLUDED for part in p.parts)
            and (p.suffix.lower() in TEXT_SUFFIXES or p.name in {"LICENSE", "NOTICE", ".gitmodules"}))


def capture(item: tuple[str, tuple[str, str | None]], root: Path) -> dict:
    slug, (repo, fixed) = item
    folder = root / slug
    folder.mkdir(parents=True, exist_ok=True)
    meta = json.loads(get(f"https://api.github.com/repos/{repo}"))
    revision = fixed or json.loads(get(f"https://api.github.com/repos/{repo}/commits/{meta['default_branch']}"))["sha"]
    tree = json.loads(get(f"https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1"))
    (folder / "tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    files = [f for f in tree.get("tree", []) if f["type"] == "blob" and safe_source(f["path"])
             and f.get("size", 0) <= 2 * 1024 * 1024]
    files.sort(key=lambda f: (0 if f["path"].lower().startswith(("patches/", "tests/", "docs/", "tools/")) else 1,
                              f["path"]))
    result = {"repository": repo, "url": f"https://github.com/{repo}", "revision": revision,
              "default_branch": meta["default_branch"], "license": meta.get("license"),
              "tree_truncated": tree.get("truncated", False), "eligible_files": len(files),
              "files": [], "errors": [], "excluded_policy": sorted(EXCLUDED)}
    for entry in files[:500]:
        path = entry["path"]
        destination = folder / "sources" / Path(*PurePosixPath(path).parts)
        url = f"https://raw.githubusercontent.com/{repo}/{revision}/{urllib.parse.quote(path)}"
        try:
            data = get(url)
            if len(data) > 2 * 1024 * 1024 or b"\x00" in data:
                raise ValueError("Not bounded text source")
            data.decode("utf-8")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            result["files"].append({"path": path, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        except Exception as exc:
            result["errors"].append({"path": path, "error": str(exc)})
    result["file_limit_reached"] = len(files) > 500
    (folder / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{slug}: {revision} files={len(result['files'])}/{len(files)} errors={len(result['errors'])}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {slug: pool.submit(capture, (slug, spec), args.out) for slug, spec in REPOSITORIES.items()}
        for slug, future in futures.items():
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"repository": REPOSITORIES[slug][0], "error": str(exc)})
                print(f"{slug}: {exc}", flush=True)
    (args.out / "manifest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return int(any("error" in r or r.get("errors") for r in results))


if __name__ == "__main__":
    raise SystemExit(main())

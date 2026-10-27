"""Create an isolated source snapshot without touching the active build."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "tmp" / "github-project4"
SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", "out", "build",
        "build64", "dist", "downloads", "saves", "mc0", "mc1", "runner",
        "cmakefiles", "_deps", ".vs", ".idea", ".cache"}
EXTENSIONS = {".py", ".cpp", ".c", ".cc", ".cxx", ".h", ".hpp", ".hxx",
              ".inl", ".inc", ".cmake", ".md", ".rst", ".txt", ".toml", ".json",
              ".yml", ".yaml", ".patch", ".diff", ".cmd", ".bat", ".ps1", ".sh",
              ".glsl", ".vert", ".frag", ".comp", ".geom", ".hlsl", ".rc", ".in",
              ".xml", ".csv", ".def", ".natvis", ".ico", ".png", ".svg", ".jpg",
              ".ttf", ".otf", ".conf", ".ini", ".map", ".s", ".asm", ".pro"}
TOP = ["core", "ps2l", "tests", "tools", "docs", "profiles", "knowledge", "integrations"]
DEPS = ["parallel-gs", "tracy", "pcsx2-spu2", "runtime-libraries"]


def git(path, *args):
    p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def main():
    if DEST.exists():
        raise SystemExit(f"Destination already exists: {DEST}")
    DEST.mkdir(parents=True)
    files = []

    def copy(path):
        rel = path.relative_to(ROOT)
        if path.is_symlink() or path.stat().st_size > 40 * 1024 * 1024:
            raise RuntimeError(f"Review required: {rel}")
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        files.append({"path": rel.as_posix(), "bytes": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    for name in TOP + ["dependencies/" + d for d in DEPS]:
        start = ROOT / name
        for directory, dirs, names in os.walk(start):
            dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP
                             and not d.lower().startswith("build-")
                             and not (name == "core" and d == "deps")
                             and not (Path(directory).name == "vu" and d == "generated"))
            for filename in sorted(names):
                p = Path(directory) / filename
                if (p.suffix.lower() in EXTENSIONS or filename.startswith(("LICENSE", "COPYING"))
                        or filename in {".gitignore", ".gitmodules", "Makefile"}):
                    if filename.endswith(("-stderr.txt", "-stdout.txt")):
                        continue
                    copy(p)
    # These are hand-written executable entry points, not generated game runners.
    for rel in ["core/ps2xRecomp/src/runner/main.cpp", "core/ps2xAnalyzer/src/runner/main.cpp"]:
        if (ROOT / rel).is_file():
            copy(ROOT / rel)
    for rel in ["README.md", ".gitignore", "PS2_PROJECT_STATE.md", "RE4-FLAGSHIP.md", "IDEA.md",
                "Play-RE4.cmd", "Enable-Game-Audio.cmd", "Record-Game-Audio.cmd",
                "recomp/config_re4.toml", "analysis/analysis.json", "analysis/functions.csv"]:
        if (ROOT / rel).is_file():
            copy(ROOT / rel)
    provenance = {"core": {"repository": git(ROOT / "core", "remote", "get-url", "origin"),
                            "base_revision": git(ROOT / "core", "rev-parse", "HEAD"),
                            "includes_local_modifications": True}, "dependencies": {}}
    for name in DEPS:
        dep = ROOT / "dependencies" / name
        provenance["dependencies"][name] = {"repository": git(dep, "remote", "get-url", "origin"),
                                               "revision": git(dep, "rev-parse", "HEAD")}
    report = {"schema": 1, "date": "2026-10-23", "provenance": provenance,
              "files": files, "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files)}
    (DEST / "docs" / "SOURCE_SNAPSHOT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"destination": str(DEST), "files": len(files), "bytes": report["total_bytes"]}))


if __name__ == "__main__":
    main()

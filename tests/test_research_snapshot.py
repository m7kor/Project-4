import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("research_audit", ROOT / "tools/research/audit_snapshot.py")
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


class ResearchSnapshotTests(unittest.TestCase):
    def test_windows_and_posix_escape_paths_are_rejected(self):
        for name in ("../evil.py", "/evil.py", "C:/evil.py", "a/evil.py:stream", "a\\evil.py", ""):
            self.assertFalse(audit_module.safe_source(name), name)
        self.assertTrue(audit_module.safe_source("src/runtime.cpp"))
        self.assertFalse(audit_module.safe_source("game/runtime.cpp"))

    def test_hash_tampering_and_requested_revision_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for slug, (repo, pinned) in audit_module.REPOSITORIES.items():
                folder = root / slug
                (folder / "sources").mkdir(parents=True)
                data = b"auditable source\n"
                (folder / "sources/README.md").write_bytes(data)
                manifest = {"repository": repo, "revision": pinned or "a" * 40,
                            "eligible_files": 1, "files": [{"path": "README.md", "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()}]}
                (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(audit_module.audit(root)["pass"])
            (root / "ico/sources/README.md").write_bytes(b"tampered source!\n")
            self.assertFalse(audit_module.audit(root)["pass"])
            path = root / "rabbitizer/manifest.json"
            manifest = json.loads(path.read_text())
            manifest["revision"] = "b" * 40
            path.write_text(json.dumps(manifest))
            self.assertTrue(any("pinned revision mismatch" in p for p in audit_module.audit(root)["problems"]))

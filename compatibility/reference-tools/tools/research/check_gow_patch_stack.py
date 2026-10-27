"""Apply the pinned external patch stack in a fresh, isolated review directory."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'research/project-survey/gow-current-review'
OUT = ROOT / 'artifacts/verification/gow-current-review'
PIN = 'c5a9d02573410a2085a4b4b831b0b68ba3515440'


def main():
    target = BASE / 'patch-stack-check'
    if target.exists() and any(target.iterdir()):
        raise RuntimeError('Review target must be absent or empty')
    target.mkdir(exist_ok=True)
    archive = subprocess.check_output(['git', '-C', str(BASE / 'waffle-runtime'), 'archive', PIN])
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        # Reject traversal, links, and generated runner trees before extracting.
        members = []
        for member in source.getmembers():
            path = target / member.name
            if not path.resolve().is_relative_to(target.resolve()):
                raise ValueError(member.name)
            if not (member.isfile() or member.isdir()):
                raise ValueError('Unexpected archive entry: ' + member.name)
            if 'runner' in Path(member.name).parts:
                continue
            members.append(member)
        source.extractall(target, members=members)
    repo = BASE / 'kiexster'
    script = (repo / 'scripts/compilar.ps1').read_text(encoding='utf-8-sig')
    paths = {m[1].lower(): m[2] for m in re.finditer(
        r"^\s*\$(\w+)\s*=\s*Join-Path\s+\$RepoRoot\s+'(patches[\\/][^']+\.patch)'", script, re.M | re.I)}
    order = [m[1].lower() for m in re.finditer(
        r"^\s*Run\s+\$git\s+@\(\s*'apply'[^)]*\$(\w+)\s*\)", script, re.M | re.I)]
    rows = []
    for name in order:
        patch = repo / paths[name].replace('\\', '/')
        result = subprocess.run(['git', 'apply', '--ignore-whitespace', str(patch)],
                                cwd=target, capture_output=True, text=True, encoding='utf-8', errors='replace')
        rows.append({'patch': patch.name, 'sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                     'exit_code': result.returncode, 'output': result.stdout + result.stderr})
        print(patch.name + ': ' + str(result.returncode), flush=True)
        if result.returncode:
            break
    OUT.mkdir(exist_ok=True, parents=True)
    report = {'base': PIN, 'target': str(target), 'expected': len(order),
              'applied': sum(r['exit_code'] == 0 for r in rows), 'results': rows}
    (OUT / 'patch-application.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['applied'] != report['expected']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

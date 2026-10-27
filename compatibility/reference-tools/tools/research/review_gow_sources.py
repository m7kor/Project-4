"""Inventory pinned GOW source checkouts and run reviewed game-independent checks."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'research/project-survey/gow-current-review'
OUT = ROOT / 'artifacts/verification/gow-current-review'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = {}
    for name in ('kiexster', 'waffle', 'waffle-runtime'):
        repo = BASE / name
        commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        paths = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--',
            ':(exclude)**/runner/**'], text=True).split('\0')
        rows = []
        for path in paths:
            if not path:
                continue
            file = repo / path
            if not file.is_file():
                rows.append({'path': path, 'kind': 'submodule-or-missing'})
                continue
            content = file.read_bytes()
            suffix = file.suffix.lower()
            kind = ('archived-patch' if path.startswith('patches/anteriores/') else
                    'patch' if suffix == '.patch' else
                    'test' if '/tests/' in '/' + path or path.startswith('ps2xTest/') else
                    'documentation' if suffix in ('.md', '.svg') else
                    'source' if suffix in ('.cpp', '.h', '.inl', '.c') else
                    'tool-or-build' if suffix in ('.py', '.ps1', '.cmd', '.sh', '.cmake', '.yml') or file.name == 'CMakeLists.txt' else
                    'configuration-or-asset')
            rows.append({'path': path, 'kind': kind, 'bytes': len(content),
                         'sha256': hashlib.sha256(content).hexdigest(),
                         'lines': content.count(b'\n') + 1 if suffix not in ('.png', '.jpg') else None})
        inventory[name] = {'commit': commit, 'files': rows,
            'counts': {kind: sum(row['kind'] == kind for row in rows) for kind in sorted({row['kind'] for row in rows})}}
    inventory['scope'] = 'Tracked-file inventory, excluding runner trees; not a claim every line was manually reviewed.'
    (OUT / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    repo = BASE / 'kiexster'
    commands = [
        ('config', [sys.executable, 'tools/ci/validar_config.py']),
        ('patch-order', [sys.executable, 'tools/ci/parches.py']),
        ('python-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v']),
    ]
    results = []
    for name, command in commands:
        proc = subprocess.run(command, cwd=repo, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=180)
        (OUT / (name + '.log')).write_text(proc.stdout + proc.stderr, encoding='utf-8')
        row = {'check': name, 'exit_code': proc.returncode, 'command': command,
               'tail': (proc.stdout + proc.stderr)[-1600:]}
        results.append(row)
        print(name + ': ' + str(proc.returncode), flush=True)
    (OUT / 'checks.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({name: {'commit': data['commit'], 'counts': data['counts']}
                      for name, data in inventory.items() if isinstance(data, dict)}))


if __name__ == '__main__':
    main()

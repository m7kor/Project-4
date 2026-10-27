"""Validate public publication content, independently of private game tests."""
from pathlib import Path
import ast
import json
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'lab/github-publication-20261027'


def main():
    checks = []
    readme = (DEST / 'README.md').read_text(encoding='utf-8')
    assert not re.search('[\u0600-\u06ff]', readme)
    checks.append('Main README is fully English')
    for document in ['README.md', 'docs/README.md', 'docs/testing/README.md',
                     'docs/testing/RESULTS.md', 'docs/status/README.md', 'docs/publication/README.md']:
        path = DEST / document
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if '://' not in target and not target.startswith('#'):
                assert (path.parent / target.split('#')[0]).exists(), (document, target)
    checks.append('New entry-point documentation links resolve locally')
    svg = ET.parse(DEST / 'docs/status/progress.svg').getroot()
    assert svg.tag.endswith('svg') and svg.attrib['viewBox'] == '0 0 1000 510'
    assert not any(e.tag.endswith(('script', 'foreignObject', 'image')) for e in svg.iter())
    checks.append('SVG parses and contains no script or external artwork')
    index = json.loads((DEST / 'docs/testing/SOURCE_INDEX.json').read_text())
    assert len(index) > 300 and all((DEST / r['path']).is_file() for r in index)
    checks.append(f'All {len(index)} indexed test/support files exist')
    for folder in ['core', 'compatibility/engines/project4', 'compatibility/source-archives/original-core']:
        fallback = (DEST / folder / 'ps2xRuntime/src/lib/vu/generated/vu1_compiled_programs.inc').read_text()
        assert 'return nullptr;' in fallback and len(fallback) < 1024
    checks.append('All three engine snapshots use public interpreter fallbacks')
    sources = list((DEST / 'compatibility').rglob('*.py'))
    for p in sources:
        ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))
    checks.append(f'{len(sources)} archived Python sources parse')
    changed = subprocess.check_output(['git', '-C', str(DEST), 'diff', '--name-only', '--cached', '-z']).decode().split('\0')
    forbidden = {'.exe', '.dll', '.obj', '.pdb', '.lib', '.iso', '.elf', '.irx', '.ps2', '.bin', '.wav'}
    for name in filter(None, changed):
        p = DEST / name
        assert p.is_file() and p.suffix.lower() not in forbidden, name
        parts = set(p.relative_to(DEST).parts)
        assert not parts & {'saves', 'mc0', 'mc1', 'bios', 'artifacts', 'runner-output'}, name
        assert not p.read_bytes().startswith((b'\x7fELF', b'MZ')), name
    checks.append(f'{len(list(filter(None, changed)))} staged publication files pass binary/private-path gate')
    report = {'passed': True, 'checks': checks, 'scope': 'Publication content checks; not engine/game acceptance'}
    out = ROOT / 'artifacts/publication-20261027'
    (out / 'content-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

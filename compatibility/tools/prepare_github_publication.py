"""Prepare a source-only publication in a fresh clone; originals remain read-only.

This is an explicit inventory, not a recursive upload of either development tree.
Private diagnostics and game-derived programs are never distribution inputs.
"""
from pathlib import Path
import collections
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path('C:/Project/PS2redmption')
DEST = ROOT / 'lab/github-publication-20261027'
PUBLIC = ROOT / 'lab/phase4-public-source'
SKIP = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'out', 'build',
        'build64', 'dist', 'downloads', 'saves', 'mc0', 'mc1', 'runner', 'generated',
        'cmakefiles', '_deps', 'deps', '.vs', '.idea', '.cache', 'artifacts', 'game', 'bios'}
EXT = {'.py', '.cpp', '.c', '.cc', '.cxx', '.h', '.hpp', '.hxx', '.inl', '.inc',
       '.cmake', '.md', '.rst', '.txt', '.toml', '.json', '.yml', '.yaml', '.patch',
       '.diff', '.cmd', '.bat', '.ps1', '.sh', '.glsl', '.vert', '.frag', '.comp',
       '.geom', '.hlsl', '.rc', '.in', '.xml', '.csv', '.def', '.natvis', '.svg',
       '.conf', '.ini', '.pro', '.html', '.mjs', '.js', '.s', '.asm', '.expected'}
SECRET = re.compile(r'gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,}|'
                    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def main():
    assert DEST.is_dir() and (DEST / '.git').is_dir()
    assert git(DEST, 'remote', 'get-url', 'origin') == 'https://github.com/m7kor/Project-4.git'
    manifest = []
    skipped = collections.Counter()
    private = ROOT / 'artifacts/publication-20261027'
    private.mkdir(exist_ok=True)

    def write(rel, data, origin='authored publication documentation'):
        rel = Path(rel)
        assert not rel.is_absolute() and '..' not in rel.parts
        raw = data.encode('utf-8') if isinstance(data, str) else data
        assert b'\x00' not in raw, f'Binary content needs review: {rel}'
        text = raw.decode('utf-8-sig')
        assert not SECRET.search(text), f'Credential signature: {rel}'
        # Public docs do not need local account names. Source scripts retain their
        # original path semantics; the portability guide labels local assumptions.
        if rel.suffix.lower() in {'.md', '.html', '.svg'}:
            text = re.sub(r'C:[/\\]Users[/\\]KH', 'C:/Users/LOCAL_USER', text, flags=re.I)
            raw = text.encode('utf-8')
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        manifest.append({'path': rel.as_posix(), 'origin': origin, 'sha256': sha(raw), 'bytes': len(raw)})

    def copy_tree(source, target):
        source = Path(source)
        for directory, dirs, names in os.walk(source, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP
                             and not d.lower().startswith(('build-', 'cmake-build'))
                             and not (Path(directory) / d).is_junction()
                             and not (Path(directory) / d).is_symlink()) if hasattr(Path('.'), 'is_junction') else sorted(
                                 d for d in dirs if d.lower() not in SKIP
                                 and not d.lower().startswith(('build-', 'cmake-build'))
                                 and not (Path(directory) / d).is_symlink()
                                 and not (os.stat(Path(directory) / d).st_file_attributes & 0x400))
            for name in sorted(names):
                p = Path(directory) / name
                if p.is_symlink() or p.suffix.lower() not in EXT and not name.startswith(('LICENSE', 'COPYING')) and name not in {'Makefile', '.gitignore', '.gitmodules'}:
                    skipped['non-source or linked files'] += 1
                    continue
                if p.stat().st_size > 8 * 1024 * 1024:
                    skipped['large files requiring separate review'] += 1
                    continue
                if name.endswith(('-stdout.txt', '-stderr.txt')):
                    skipped['raw logs'] += 1
                    continue
                write(Path(target) / p.relative_to(source), p.read_bytes(),
                      ('project4-original/' if source.is_relative_to(ORIGINAL) else 'compatibility-lab/') + str(p.relative_to(source)).replace('\\', '/'))

    # Preserve the reviewed source distribution, including its interpreter-only
    # generated-table fallback. Do not replace it with private game microcode.
    for name in git(PUBLIC, 'ls-files', 'core').splitlines():
        p = PUBLIC / name
        assert p.is_file()
        if p.suffix.lower() not in EXT and not p.name.startswith(('LICENSE', 'COPYING')) and p.name not in {'Makefile', '.gitignore', '.gitmodules'}:
            skipped['existing upstream non-text assets left unchanged'] += 1
            continue
        write(name, p.read_bytes(), 'reviewed-public-core@' + git(PUBLIC, 'rev-parse', 'HEAD'))

    for name in ('ps2l', 'tests', 'tools', 'docs', 'profiles', 'knowledge', 'integrations'):
        copy_tree(ORIGINAL / name, name)
    for name in ('tools', 'tests'):
        copy_tree(ROOT / name, 'compatibility/' + name)
    for name in ('tools', 'tests', 'ps2l', 'knowledge'):
        copy_tree(ROOT / 'reference-tools' / name, 'compatibility/reference-tools/' + name)
    copy_tree(ROOT / 'engines/project4', 'compatibility/engines/project4')
    copy_tree(ROOT / 'engines/zmbor', 'compatibility/engines/zmbor')
    copy_tree(ROOT / 'lab/zmbor-phase2/src', 'compatibility/source-archives/zmbor-00173a2')
    copy_tree(ORIGINAL / 'core', 'compatibility/source-archives/original-core')
    fallback = (PUBLIC / 'core/ps2xRuntime/src/lib/vu/generated/vu1_compiled_programs.inc').read_bytes()
    for folder in ('compatibility/engines/project4', 'compatibility/source-archives/original-core'):
        write(folder + '/ps2xRuntime/src/lib/vu/generated/vu1_compiled_programs.inc', fallback,
              'public interpreter fallback, not captured game code')
    for p in sorted((ROOT / 'artifacts/phase2/hardware-inputs').glob('*.expected')):
        write('compatibility/hardware-reference/expected/' + p.name, p.read_bytes(),
              'unchanged independent hardware-reference text, not game data')
    copy_tree(ROOT / 'reports', 'docs/compatibility/reports')
    copy_tree(ROOT / 'docs', 'docs/compatibility/design')
    write('recomp/config_re4.toml', (ORIGINAL / 'recomp/config_re4.toml').read_bytes(), 'project4-original/recompiler-config')
    for p in sorted((ROOT / 'lab').glob('*.cmd')):
        write('compatibility/lab/' + p.name, p.read_bytes(), 'compatibility-lab/build-helper')
    if (ROOT / 'lab/CMakeLists.txt').is_file():
        write('compatibility/lab/CMakeLists.txt', (ROOT / 'lab/CMakeLists.txt').read_bytes(), 'compatibility-lab/build-helper')
    write('compatibility/PS2_PROJECT_STATE.md', (ROOT / 'PS2_PROJECT_STATE.md').read_bytes(), 'compatibility-lab/checkpoint')

    # Preserve additional handwritten source changes as unapplied review patches;
    # the stable public tree and experimental engine are never blindly merged.
    reviewed = [Path(n) for n in git(PUBLIC, 'ls-files', 'core').splitlines()
                if '/generated/' not in n and n.endswith(('.cpp', '.inl', '.h', '.hpp', '.txt', '.cmake'))]
    for label, base in [('original-worktree', ORIGINAL / 'core'), ('lab-worktree', ROOT / 'engines/project4')]:
        chunks = []
        for rel in reviewed:
            other = base / rel.relative_to('core')
            if other.is_file():
                before = (PUBLIC / rel).read_text(encoding='utf-8-sig').splitlines(True)
                after = other.read_text(encoding='utf-8-sig').splitlines(True)
                chunks += difflib.unified_diff(before, after, fromfile='a/' + rel.as_posix(), tofile='b/' + rel.as_posix())
        write(f'compatibility/patches/{label}.patch', ''.join(chunks), 'unapplied handwritten-source delta')
    runtime = (ROOT / 'reports/RE4_HOST_BOUNDARY_RUNTIME.patch').read_text().replace('a/ps2xRuntime/src/lib/ps2_vu1_core.cpp', 'a/core/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp').replace('b/ps2xRuntime/src/lib/ps2_vu1_core.cpp', 'b/core/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp')
    write('compatibility/patches/host-boundary-inline.patch', runtime, 'optional validated-scene experiment; not applied')
    summary = {'date': '2026-10-27', 'snapshot_kind': 'source-only publication',
               'public_core_source_commit': git(PUBLIC, 'rev-parse', 'HEAD'),
               'lab_source_commit': git(ROOT, 'rev-parse', 'HEAD'),
               'local_fixtures_included': False, 'private_data_published': False,
               'files': manifest, 'excluded_counts': dict(skipped)}
    (private / 'staging-manifest.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    write('docs/publication/SOURCE_INVENTORY.json', json.dumps(summary, indent=2))
    print('Prepared', len(manifest), 'reviewed text sources/documents; private manifest:', private / 'staging-manifest.json')


if __name__ == '__main__':
    main()

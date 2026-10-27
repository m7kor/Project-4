"""Seal private evidence and a runtime-only patch; never publish or promote."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(name):
    return json.loads((ROOT / name).read_text())


def selected_sources():
    paths = [ROOT / name for name in (
        '.gitignore', 'PS2_PROJECT_STATE.md', 'tools/lab_regression.py',
        'tools/measure_phase5_game.py', 'tools/host_gameplay_watch.py',
        'tests/host_boundary_probe.inl', 'tests/test_host_boundary_observer.py',
        'tests/test_host_boundary_regression.py',
        'reports/RE4_HOST_CODE_ATTRIBUTION_AR.md',
        'reports/RE4_QUICKSAVE_FEASIBILITY_AR.md',
    )]
    paths += list((ROOT / 'tools').glob('host_boundary_*.py'))
    paths += list((ROOT / 'reports').glob('RE4_HOST_BOUNDARY_*'))
    return sorted(set(paths))


def main():
    frozen = read('artifacts/architecture/freeze-01/manifest.json')
    for name, digest in {**frozen['protected'], **frozen['source_files']}.items():
        assert sha(ROOT / name) == digest, name
    original = Path('C:/Project/PS2redmption/artifacts/ghidra')
    for name, digest in read('lab/ghidra-recovery-01/identity.json')['original_project_files'].items():
        assert sha(original / name) == digest, name
    expected = {r['id']: r['expected_sha256'] for r in read('artifacts/phase2/hardware-inputs.json')}
    rows = read('artifacts/phase2/hardware-current/catalog.json')['tests']
    assert len(rows) == 55
    for row in rows:
        assert sha(row['expected']) == expected[row['id'].removeprefix('ps2x_hw_')]
    for field in ('input_files', 'generated_files'):
        for path, digest in read('lab/host-boundary-inline-01/generation.json')[field].items():
            assert sha(path) == digest, path
    gate = read('artifacts/host-boundary/gate-02/report.json')
    assert gate['passed'] and gate['supplemental_lab_python']['passed'] == 104
    for path, digest in gate['source_witness'].items():
        assert sha(path) == digest, path
    cards = {}
    for run in (ROOT / 'artifacts/runs').glob('host-boundary-*'):
        path = run / 'guest/saves/cards/native-card-0.ps2'
        if path.is_file():
            cards[str(path.relative_to(ROOT))] = sha(path)
            assert cards[str(path.relative_to(ROOT))] == 'ae9c30f7ec60b2cba2363fe38de568f9f6fcad61e204e65a82ad9e15619554d6'
    assert len(cards) == 17, 'Expected human session plus sixteen automatic runs'
    reference = ROOT / 'lab/architecture-aot-02/src/ps2_vu1_core.cpp'
    candidate = ROOT / 'lab/host-boundary-inline-01/src/ps2_vu1_core.cpp'
    patch = ''.join(difflib.unified_diff(reference.read_text().splitlines(True), candidate.read_text().splitlines(True),
                                       fromfile='a/ps2xRuntime/src/lib/ps2_vu1_core.cpp',
                                       tofile='b/ps2xRuntime/src/lib/ps2_vu1_core.cpp', n=0))
    assert sum(line.startswith('+__attribute__') for line in patch.splitlines()) == 5
    (ROOT / 'reports/RE4_HOST_BOUNDARY_RUNTIME.patch').write_text(patch, encoding='utf-8', newline='\n')
    binaries = {}
    for path in [ROOT / 'lab/host-boundary-game-01/ps2EntryRunner.exe',
                 ROOT / 'lab/host-boundary-inline-01/ps2x_tests.exe',
                 ROOT / 'lab/host-boundary-inline-01/ps2x_vu1_bench.exe',
                 ROOT / 'lab/host-boundary-state-01/state_probe.exe']:
        binaries[str(path.relative_to(ROOT))] = sha(path)
    out = ROOT / 'artifacts/host-boundary/final-manifest-01'
    out.mkdir(exist_ok=True)
    reports = {str(path.relative_to(ROOT)): sha(path)
               for path in (ROOT / 'artifacts/host-boundary').rglob('*.json') if out not in path.parents}
    data = {'decision': 'Validated separate experimental improvement in the measured scene; no promotion',
            'frozen_engine_files_verified': len(frozen['source_files']),
            'expected_outputs_verified': len(rows), 'protected_verified': frozen['protected'],
            'original_ghidra_verified': True, 'binaries': binaries, 'evidence_reports': reports,
            'isolated_unchanged_cards': cards,
            'reviewable_sources': {str(p.relative_to(ROOT)): sha(p) for p in selected_sources()},
            'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'scope': 'Private manifest. No game assets, generated code or traces in the source-only patch.'}
    (out / 'manifest.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    (out / 'source-list.json').write_text(json.dumps([str(p.relative_to(ROOT)) for p in selected_sources()], indent=2))
    print('Verified 277 frozen engine files, 55 expected outputs, protected inputs, original Ghidra, and candidate witnesses.')
    print('Runtime-only patch and private manifest written; no game launch or promotion.')


if __name__ == '__main__':
    main()

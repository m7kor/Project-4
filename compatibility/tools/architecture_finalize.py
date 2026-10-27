"""Verify protected inputs and write a private, reproducible experiment manifest."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text())


def main():
    frozen = read('artifacts/architecture/freeze-01/manifest.json')
    for name, digest in {**frozen['protected'], **frozen['source_files']}.items():
        assert sha(ROOT / name) == digest, 'Protected reference changed: ' + name
    ghidra = read('lab/ghidra-recovery-01/identity.json')
    original = Path('C:/Project/PS2redmption/artifacts/ghidra')
    for name, digest in ghidra['original_project_files'].items():
        assert sha(original / name) == digest, 'Original Ghidra project changed: ' + name
    inputs = {r['id']: r for r in read('artifacts/phase2/hardware-inputs.json')}
    hardware = read('artifacts/phase2/hardware-current/catalog.json')
    assert len(hardware['tests']) == 55
    for row in hardware['tests']:
        assert sha(row['expected']) == inputs[row['id'].removeprefix('ps2x_hw_')]['expected_sha256']
    for run in ('architecture-profile-01', 'architecture-input-clock-01'):
        report = read(f'artifacts/runs/{run}/report.json')
        assert report['process_exit_observed'] and report['test_saves_unchanged']
        for name, digest in report['saves_before'].items():
            assert sha(ROOT / 'artifacts/runs' / run / 'guest/saves' / name) == digest
    witnesses = {}
    for name in ('generation.json', 'engineering-inputs.json'):
        path = ROOT / 'lab/architecture-aot-02' / name
        data = json.loads(path.read_text())
        for field in ('input_files', 'generated_files', 'files'):
            for file, digest in data.get(field, {}).items():
                assert sha(file) == digest, 'Candidate input changed: ' + file
        witnesses[str(path.relative_to(ROOT))] = sha(path)
    input_identity = read('lab/architecture-input-01/identity.json')
    for file, digest in input_identity['files'].items():
        assert sha(file) == digest, file
    binaries = {}
    for folder, names in (
        ('lab/architecture-aot-02', ('ps2x_tests.exe', 'ps2x_vu1_bench.exe')),
        ('lab/architecture-aot-state-02', ('state_probe.exe',)),
        ('lab/architecture-input-01', ('ps2EntryRunner.exe', 'ps2x_tests.exe')),
        ('lab/architecture-vu-cost-01', ('ps2x_vu1_bench.exe',)),
    ):
        for name in names:
            file = ROOT / folder / name
            binaries[str(file.relative_to(ROOT))] = sha(file)
    selected = [ROOT / '.gitignore', ROOT / 'PS2_PROJECT_STATE.md',
                ROOT / 'tools/lab_regression.py', ROOT / 'tools/run_lab.py']
    selected += list((ROOT / 'tools').glob('architecture_*.py'))
    selected += list((ROOT / 'tests').glob('test_architecture_*.py'))
    selected += list((ROOT / 'tests').glob('architecture_*.inl'))
    selected += list((ROOT / 'reports').glob('RE4_ARCHITECTURE_*.md'))
    selected += [ROOT / 'reports/RE4_RADICAL_ARCHITECTURE_RESEARCH.md',
                 ROOT / 'reports/RE4_PERFORMANCE_ROOT_CAUSES.md']
    sources = {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(selected))}
    evidence = {}
    for folder in ('equivalence-02', 'equivalence-03', 'regression-01', 'operand-fuzz-01',
                   'benchmark-01', 'full-gate-01', 'full-gate-02', 'input-clock-01',
                   'vu-native-coverage-01', 'host-code-02', 'ammo-counter-01', 'audio-01'):
        p = ROOT / 'artifacts/architecture' / folder / 'report.json'
        evidence[str(p.relative_to(ROOT))] = sha(p)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    out = ROOT / 'artifacts/architecture/final-01'
    out.mkdir(exist_ok=False)
    result = {'source_commit_before_final_record': head, 'sources': sources, 'binaries': binaries,
              'build_witnesses': witnesses, 'evidence': evidence,
              'protected': frozen['protected'], 'unchanged_frozen_engine_files': len(frozen['source_files']),
              'unchanged_hardware_expected': 55, 'unchanged_original_ghidra_files': len(ghidra['original_project_files']),
              'accepted_optimization': False, 'new_game_performance_gain': None,
              'scope': 'Private provenance. No game-derived binaries, captures or generated source may be published.'}
    (out / 'manifest.json').write_text(json.dumps(result, indent=2))
    (out / 'source-files.json').write_text(json.dumps(list(sources), indent=2))
    print('Verified protected runners/cards, 277 frozen engine sources, 55 expected files and original Ghidra database')
    print('Source-only selection:', len(sources), 'files; manifest:', out / 'manifest.json')


if __name__ == '__main__':
    main()

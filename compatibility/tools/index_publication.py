"""Index preserved source archives, all test sources and public documentation."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'lab/github-publication-20261027'


def write(name, text):
    p = DEST / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8', newline='\n')


def main():
    test_roots = ['tests', 'core/ps2xTest', 'core/ps2xIOP/tests', 'compatibility/tests',
                  'compatibility/reference-tools/tests', 'compatibility/engines/project4/ps2xTest',
                  'compatibility/engines/project4/ps2xIOP/tests',
                  'compatibility/source-archives/original-core/ps2xTest',
                  'compatibility/source-archives/original-core/ps2xIOP/tests',
                  'compatibility/engines/zmbor/ps2xTest', 'compatibility/engines/zmbor/ps2xIOP/tests',
                  'compatibility/source-archives/zmbor-00173a2/ps2xTest',
                  'compatibility/source-archives/zmbor-00173a2/ps2xIOP/tests',
                  'compatibility/hardware-reference/expected']
    rows = []
    for folder in test_roots:
        for p in sorted((DEST / folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                rows.append({'path': p.relative_to(DEST).as_posix(), 'group': folder})
    write('docs/testing/SOURCE_INDEX.json', json.dumps(rows, indent=2))
    lines = ['# Complete distributable test-source index', '',
             'Files are listed by source tree. Mirrored source archives overlap; file counts are not independent test-case counts.', '',
             'Private VU snapshots, game-derived payloads, game binaries and saves are excluded. Their absence must be reported as unavailable, never as a pass.', '']
    for folder in test_roots:
        selected = [r for r in rows if r['group'] == folder]
        lines += ['## ' + folder, '', f'{len(selected)} source/support files.', '']
        lines += ['- [' + r['path'] + '](../../' + r['path'] + ')' for r in selected]
        lines += ['']
    write('docs/testing/SOURCE_INDEX.md', '\n'.join(lines))
    write('docs/testing/README.md', '''# All tests: commands, inputs and evidence

The [complete source index](SOURCE_INDEX.md) lists Project-4, compatibility-lab and preserved engine test sources. [RESULTS.md](RESULTS.md) records executed results separately from available source. A public checkout does not include private workloads or accepted executables.

## Project-4 Python

From the repository root:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests
```

Tests with missing optional dependencies or local inputs may skip or fail; read the actual output. No full public clean-checkout pass is asserted by historical local results.

## Native tests

`core/ps2xTest/` and `core/ps2xIOP/tests/` contain the native source suites. Use the x64 developer shell and the build instructions in [01-BUILD.md](../01-BUILD.md). Tests must be bound to the exact source revision and newly built executable identity. The source archives under `compatibility/engines/` and `compatibility/source-archives/` are separate snapshots, not an automatically merged engine.

## Laboratory command groups

Run from `compatibility/` so Python resolves the laboratory tools rather than the root Project-4 tools:

```powershell
cd compatibility
python tools/lab_regression.py fast --plan
python tools/lab_regression.py vu --plan
python tools/lab_regression.py ee --plan
python tools/lab_regression.py graphics --plan
python tools/lab_regression.py audio --plan
python tools/lab_regression.py hardware --plan
python tools/lab_regression.py dma --plan
python tools/lab_regression.py iop --plan
python tools/lab_regression.py integration --plan
python tools/lab_regression.py full --plan
python tools/lab_regression.py auto --changed engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp --plan
```

Remove `--plan` only after supplying the required private binaries, source manifests and fixtures. Use `--candidate-dir`, `--baseline-dir`, `--vu-source`, `--project4-recompiler` and `--integration-spec` as appropriate. `integration --allow-game` requires an explicit validated spec and isolated cards. An old executable is never evidence for newly edited source. Running `--help` or `--plan` validates command selection, not hardware correctness.

The existing commands do not automatically download or reconstruct private inputs. Paths to prior `lab/` and `artifacts/` experiments are retained for provenance and need the corresponding local evidence. Some legacy diagnostic scripts have machine-specific paths. These are source archives, not a turnkey recreation of every old private experiment.

## Replay and negative controls

Sources include VU full-state equivalence, VIF, narrow DMA and IOP/SIF replay, input quality checks, source/binary identity, malformed ELF and integer-semantics tests, synthetic mutation checks, graphics and PCM analysis. Distinguish runtime agreement, recorded RE4 agreement and independent PS2 hardware evidence.

Do not change `.expected` files to create passes. Do not treat incomplete captures, missing fixtures, process liveness, or a successful compile as gameplay acceptance. Preserve failures and skipped/unavailable results.
''')
    write('docs/testing/RESULTS.md', '''# Executed test ledger â€” 27 October 2026

These results come from the private Windows compatibility lab. This publication is documentation/source organization, not a fresh validation of every native source snapshot.

| Gate | Actual result | Scope |
|---|---|---|
| Latest VU candidate C++ | 635/635 each reference and candidate | Exact independently built binaries |
| Full-state snapshots | 3,200 matched | Reference/candidate execution, not just inventory |
| Command replay | 964 and 1,024 commands matched | State, cycles, ordered GIF output |
| Small budgets / continuation | 800-snapshot subset matched | Budgets 1,2,4,31,256,4096,65536 and resume coverage |
| Queue cases | 512 deterministic cases / 6,144 checkpoints | Full architectural state |
| Operand mutations | 64 matched | Synthetic operands on real microcode, not hardware evidence |
| Latest complete lab Python rerun | 104/104 | Supplemental after test-fixture repair |
| Closure focused tests | 4/4 | Already included in the broader suite; do not add counts |
| Project-4 Python | 403 cases, including 7 skipped | Existing local suite via verify |
| Arithmetic gates | Z3 29; emitted-arithmetic UBSan 952 | Not whole-runtime sanitizer coverage |
| Existing VIF/GIF/DMA and IOP/SIF gates | Passed in recorded full jobs | Detailed per-job evidence remains local |
| Audio / PCM tests | 22 audio / 4 PCM | Does not establish synchronized host playback |
| Hardware baseline | 47/55 exact; 8 known mismatches | Separate Zmbor 00173a2d4a9d740adac2d5a1df5f1cf1ecb9abcb |
| Two full invocations | Each 116 passed, 1 failed, 8 known mismatches | Original failed runs retained; not relabeled green |
| Whole game | 7 primary alternating pairs, one scene | 0.205848x â†’ 0.215486x; paired median +4.9357% |
| Matched graphics | 37/37 matching RGBA frames | Guest-tag contract; aim/inventory matching keys absent |
| Raw PCM | 5,570,686 common committed stereo frames equal | WAV hard-stop tails excluded; AV sync unverified |

The first full run exposed a relative recompiler path after changing child cwd; it was normalized to an absolute path. The second exposed a malformed newly added Python fixture. All104 lab Python tests were then rerun. An aggregate gate binds these results to unchanged candidate engine binaries. Neither original full invocation passed as a whole.

## Duration and overhead

Full-state equivalence took 58.704 seconds. Isolated seven-pair comparisons for two workloads took 85.774 seconds. The first full invocation took 288.797 seconds. Real-game acceptance is substantially more expensive: sixteen automatic launches were used, including the preregistered replacement pair after an observer failure. The human session ended after1079.516 seconds at the user's request.

Diagnostic host-scope instrumentation added roughly34.65â€“57.32% overhead, so its bucket timing percentages were rejected. Sampling fractions are thread sample fractions, not exact whole-process costs. ETW sampling failed with Windows Access Denied0x5; cache/branch counters and GPU timestamps were not captured.

## Open gates

No new candidate hardware baseline, full campaign, later distinct room transition, accepted village combat, latest-candidate campaign save/reload, complete aim/inventory image equivalence, external quicksave, speaker-loopback proof, AV synchronization, or complete frame-pacing acceptance. The public interpreter fallback and absent private generated inputs mean local game benchmark numbers cannot be assumed for an unconfigured clone.

Exact local executable/source identities and per-phase failures: [latest engineering report](../compatibility/reports/RE4_HOST_BOUNDARY_ENGINEERING_AR.md), [commit record](../compatibility/reports/RE4_HOST_BOUNDARY_COMMITS.md), and the preserved earlier reports in the [documentation index](../README.md).
''')
    write('docs/publication/README.md', '''# Public source archive

This update collects the redistributable text sources, tools, test harnesses and documentation from the Project-4 development workspace and the compatibility laboratory. The repository remains public. Original working directories, accepted executable packages, game assets and save data were not modified by publication.

## Preserved source versions

- `core/`: reviewed public runtime/recompiler snapshot with Phase4 safety fixes and the disabled Phase5 FMAC experiment; existing public dependencies and licenses are retained.
- `compatibility/engines/project4/`: separate laboratory handwritten-engine snapshot. Private generated microprograms are replaced by the small public interpreter fallback.
- `compatibility/source-archives/original-core/`: original Project-4 handwritten-core snapshot, preserved separately rather than merged over the laboratory or reviewed core.
- `compatibility/reference-tools/`: the lab's Project-4 diagnostic/Python reference copy, including its isolation changes.
- `compatibility/tools/` and `compatibility/tests/`: all reviewed distributable lab tool/test sources, including rejected and disabled experiment tooling.
- `compatibility/patches/`: unapplied original/lab source deltas plus the five-attribute VU experiment. Patches are review artifacts, not an instruction to apply all experiments.
- `docs/compatibility/`: laboratory reports, patches and design documents; earlier claims keep their original context.

The archive contains overlapping versions intentionally. Their tests, commits and benchmark results must not be conflated. Source hashes and origins are recorded in [SOURCE_INVENTORY.json](SOURCE_INVENTORY.json). Publication changes do not certify a new clean native build.

## Local-only exclusions

Game discs and extracted assets; BIOS; proprietary executables and IRX modules; generated EE/native-module/VU game code; captured game RAM/VRAM, traces, raw audio and screenshots; user/test saves and memory cards; compiled binaries, libraries, objects, build caches and logs; credentials, account configuration and machine-private connector files. External reference PDFs/images with no established redistribution grant are not rehosted. Cached dependency checkout copies are not duplicated into each source archive; the existing public dependencies and upstream license notices remain available.

The source manifest inventories selected distributable files. It is not a claim that every byte of either private development directory is on GitHub. Local paths in old scripts may need configuration; private artifact links intentionally remain unavailable. No published game package or game-data download is provided.

## History and publication

The publication branch descends from the existing owner repository history. Original Git histories and working branches remain untouched locally. The latest laboratory change records are0350377 and1a83319. Source organization and README/SVG work are committed separately on the publication branch. No upstream PS2Recomp push and no automatic PR merge are authorized here.
''')
    docs = sorted(p for p in (DEST / 'docs').rglob('*.md') if p.name != 'README.md' or p.parent != DEST / 'docs')
    lines = ['# Documentation', '', 'English entry points for the current state:', '',
             '- [Gameplay and hardware progress](status/README.md)',
             '- [All tests and commands](testing/README.md)',
             '- [Executed result ledger and limitations](testing/RESULTS.md)',
             '- [Public source archive and exclusions](publication/README.md)',
             '- [Source setup](GITHUB_SETUP.md)', '',
             'Historical documents retain their original language, dates and evidence scope. A link to private artifacts is not a distributed fixture. No older report overrides the latest explicitly scoped test ledger.', '',
             '## All documents', '']
    lines += ['- [' + p.relative_to(DEST / 'docs').as_posix() + '](' + p.relative_to(DEST / 'docs').as_posix() + ')' for p in docs]
    write('docs/README.md', '\n'.join(lines) + '\n')
    results = DEST / 'docs/testing/RESULTS.md'
    results.write_text(results.read_text(encoding='utf-8') + '''
## Publication-time checks

The actual public root Python suite ran403 tests on the normal Windows host: **OK,7 skipped**, in8.672 seconds wall time (7.606 seconds unittest time). Two preceding restricted-environment runs each recorded6 path-access errors and7 skips; both failures were preserved locally. Moving temporary files into the workspace alone did not resolve those errors. No source expectation was changed for this rerun. Publication content checks are separate from engine correctness.
''', encoding='utf-8', newline='\n')
    print('Indexed', len(rows), 'test/support source files and', len(docs), 'documents.')


if __name__ == '__main__':
    main()

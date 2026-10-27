"""Author English public entry points and an original SVG status map."""
from pathlib import Path
import html
import json

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'lab/github-publication-20261027'


def write(name, text):
    path = DEST / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def main():
    hardware = [
        ('EE / R5900', 'Static recompilation', 'Integer semantics / malformed ELF tests', 'Broader campaign instruction coverage'),
        ('MMI + FPU', 'Implemented, scoped tests', 'Translation and arithmetic regressions', 'Independent hardware edge-case evidence'),
        ('VU0', 'Runtime implementation', 'Shared helpers and unit-test coverage', 'More captured real-workload equivalence'),
        ('VU1', 'Primary performance bottleneck', '3,200 snapshots; 964 + 1,024 commands', 'Sustained real-time performance'),
        ('VU pipeline', 'Reference semantics retained', 'Budgets, flags, queues and continuation', 'Low-overhead candidate attribution'),
        ('VIF0 / VIF1', 'Fast paths retained', 'VIF replay and payload-bound tests', 'Wider interleaved workload coverage'),
        ('GIF + XGKICK', 'Packet paths exercised', 'Ordered GIF / full-state comparisons', 'Independent timing edge cases'),
        ('GS / paraLLEl-GS', 'Existing renderer retained', '37 matched guest-tagged RGBA frames', 'Wider scenes and frame-pacing proof'),
        ('DMAC + SPR', 'Narrow replay coverage', 'Chains, payload bounds and DMA tests', 'More channels / independent timing'),
        ('IOP + SIF', 'Services and replay', 'Protocol / ordering regression gates', 'Broader RPC and scheduler workloads'),
        ('IPU / movies', 'Intro path demonstrated', 'Historical real-game intro observations', 'Longer video and AV-sync validation'),
        ('SPU2 / audio', 'PCM agrees; underruns remain', '5,570,686 common stereo frames equal', 'Speaker output and AV synchronization'),
        ('Disc / streaming', 'Read-only original assets', 'Resource requests and room loading', 'More rooms and completion behavior'),
        ('Controllers', 'Movement / aiming / shooting', 'Verified input and real observations', 'Lossless same-tick event replay'),
        ('Memory cards', 'Earlier save / restart / reload', 'Isolated campaign card validation', 'New candidate progress-save acceptance'),
        ('Timing / scheduler', 'Measured below real time', 'Seven alternating scene A/B pairs', 'CPU / GPU wait attribution and pacing'),
        ('Dynamic modules', 'Existing loader reused', 'Gameplay and IOP diagnostics', 'More events and module lifecycles'),
        ('External quicksave', 'Not implemented', 'Card backup is not a savestate', 'Restorable complete-state contract'),
    ]
    data = {'as_of': '2026-10-27', 'scope': 'Evidence, not an overall completion percentage',
            'performance': {'reference_median_speed': 0.2058477945, 'candidate_median_speed': 0.2154855482,
                            'paired_median_gain_percent': 4.9357072, 'pairs': 7},
            'cpp_tests_per_implementation': 635, 'snapshot_count': 3200,
            'separate_zmbor_hardware': {'exact': 47, 'total': 55, 'revision': '00173a2d4a9d740adac2d5a1df5f1cf1ecb9abcb'},
            'components': [dict(zip(('component', 'status', 'evidence', 'gap'), row)) for row in hardware]}
    write('docs/status/data.json', json.dumps(data, indent=2))
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1580" viewBox="0 0 1440 1580" role="img" aria-labelledby="title desc">',
           '<title id="title">Project-4: RE4 gameplay and PS2 subsystem evidence</title>',
           '<desc id="desc">Room 100 to 101 confirmed. Experimental scene speed 0.2058 to 0.2155 times real time. Eighteen component cards show evidence and remaining gaps; no overall completion percentage.</desc>',
           '<style>text{font-family:Segoe UI,Arial,sans-serif}.title{font-size:36px;font-weight:700;fill:#f2f5fb}.body{font-size:16px;fill:#b7c4d8}.name{font-size:21px;font-weight:600;fill:#e7eef9}.small{font-size:14px;fill:#a6b6cf}</style>',
           '<rect width="1440" height="1580" fill="#0b1220"/>',
           '<text x="40" y="61" class="title">PROJECT-4 / RESIDENT EVIL 4</text>',
           '<text x="40" y="94" class="body">GAMEPLAY + HARDWARE EVIDENCE MAP   /   SLUS-211.34   /   27 OCT 2026</text>',
           '<rect x="40" y="119" width="1360" height="56" rx="8" fill="#17243a"/>',
           '<text x="60" y="154" class="body">Scoped evidence, not completion:  green = observed checkpoint   amber = partial coverage   gray = unverified / absent</text>']
    for i, (value, label, note) in enumerate([
        ('0.2155x', 'Experimental scene speed', 'Reference 0.2058x / real time = 1.0x'),
        ('+4.94%', 'Median paired scene gain', '7 alternating A/B pairs / one fixed scene'),
        ('635 / 635', 'C++ tests per implementation', '3,200 full-state snapshots compared'),
        ('47 / 55', 'Separate Zmbor hardware baseline', '8 known mismatches / not this candidate')]):
        x = 40 + i * 345
        svg += [f'<rect x="{x}" y="197" width="325" height="123" rx="10" fill="#132035" stroke="#293a55"/>',
                f'<text x="{x+18}" y="236" font-family="Segoe UI,Arial" font-size="31" font-weight="700" fill="#76d5d3">{value}</text>',
                f'<text x="{x+18}" y="269" class="body">{label}</text>',
                f'<text x="{x+18}" y="296" font-family="Segoe UI,Arial" font-size="12" fill="#a6b6cf">{note}</text>']
    svg += ['<text x="40" y="359" class="name">GAMEPLAY CHECKPOINTS</text>']
    for i, (a, b, color) in enumerate([
        ('Boot + menus', 'Observed', '#38c793'), ('Forest controls', 'Move / aim / shoot', '#38c793'),
        ('Room 100 → 101', '677 stable observations', '#38c793'), ('Save + reload', 'Earlier isolated runner', '#efb85b'),
        ('Full campaign', 'Not verified', '#8390a4')]):
        x = 40 + i * 275
        svg += [f'<rect x="{x}" y="379" width="260" height="85" rx="9" fill="#142237" stroke="{color}"/>',
                f'<text x="{x+15}" y="412" class="name">{html.escape(a)}</text>',
                f'<text x="{x+15}" y="440" class="small">{html.escape(b)}</text>']
    svg += ['<text x="40" y="510" class="name">PS2 COMPONENTS / IMPLEMENTATION ≠ COMPLETE COMPATIBILITY</text>']
    for i, row in enumerate(hardware):
        col, line = i % 3, i // 3
        x, y = 40 + col * 460, 533 + line * 145
        name, state, proof, gap = map(html.escape, row)
        color = '#8390a4' if i == 17 else '#efb85b'
        svg += [f'<rect x="{x}" y="{y}" width="440" height="129" rx="9" fill="#132035" stroke="#293a55"/>',
                f'<rect x="{x}" y="{y+13}" width="4" height="102" rx="2" fill="{color}"/>',
                f'<text x="{x+18}" y="{y+29}" class="name">{name}</text>',
                f'<text x="{x+18}" y="{y+55}" font-family="Segoe UI,Arial" font-size="15" fill="{color}">{state}</text>',
                f'<text x="{x+18}" y="{y+82}" class="small">{proof}</text>',
                f'<text x="{x+18}" y="{y+108}" class="small">Next: {gap}</text>']
    svg += ['<path d="M40 1423H1400" stroke="#293a55"/>',
            '<text x="40" y="1457" class="body">Candidate stays separate. Accepted executable and saves preserved. Full campaign / synchronized audio remain open.</text>',
            '<text x="40" y="1487" class="small">37 matched RGBA frames. Matching raw PCM prefix does not prove speaker playback or AV sync. No game assets distributed.</text>',
            '<text x="40" y="1517" class="small">Latest lab: source 0350377 / closure 1a83319. Hardware baseline: Zmbor 00173a2. Details: docs/status/README.md.</text>',
            '<text x="40" y="1547" class="small">Original diagram inspired by component status maps; no game artwork, extracted program data, or invented percentage bars.</text>', '</svg>']
    write('docs/status/progress.svg', '\n'.join(svg))
    table = '\n'.join('| ' + ' | '.join(row) + ' |' for row in hardware)
    write('docs/status/README.md', '''# Gameplay and hardware status

As of **27 October 2026**. The [SVG map](progress.svg) and [machine-readable data](data.json) describe scoped evidence. They do not measure overall port completion.

| Component | Current state | Evidence | Remaining gap |
|---|---|---|---|
''' + table + '''

## Performance and validation contract

One fixed RE4 scene, seven alternating primary A/B pairs: median reference speed **0.205848x**, candidate **0.215486x**; median paired gain **4.9357%**. These are different statistics. Descriptive bootstrap interval for the paired median: 4.248–5.868%; conservative endpoint-bracket median bounds: 0.173–10.699%. Individual bounds for two pairs cross zero. The replaced fourth pair was preregistered after an observer failure, with the original retained. No whole-campaign or real-time performance claim.

Reference game SHA-256: `fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53`.
Candidate SHA-256: `55b31f4f2470c06ebcd3f39cf11f223bcefb644efa6a10707d2e1f7a1103f87e`.
Protected accepted runner: `e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a`.

The small prototype force-inlines five unchanged VU helper bodies. It does not change arithmetic, retirement scheduling, flags, generated block coverage, or renderer. The candidate remains a separate experimental build. The public interpreter fallback is not the game-derived optimized table used in the private measurements; a public clean native build and equal public-fallback performance are not claimed.

## Gameplay limits

- Fresh human room transition 0x100→0x101: 677 stable observations; movement continued. Later room transition and village combat are not independently accepted.
- Backing ammunition 5→4→3→3 agreed in both runners. Historical HUD anomaly remains open.
- Earlier isolated campaign save/restart/reload was verified. No new progress-save acceptance was performed for the latest candidate. Arbitrary-location external quicksave is not implemented.
- 37 guest-tagged frames matched; no matching capture keys in the aim/inventory windows. This is not full VRAM or whole-scene coverage.
- 5,570,686 common committed stereo PCM frames matched. Hard-stop WAV tails were excluded. Speaker playback, host timing and AV sync remain unverified; underruns remain.

See the [test ledger](../testing/RESULTS.md) and [detailed lab report](../compatibility/reports/RE4_HOST_BOUNDARY_ENGINEERING_AR.md). Older reports retain the evidence and limits of their own revision.
''')
    write('README.md', '''<div align="center">

# Project-4 — Resident Evil 4 Native Recompilation

**An experimental PS2-to-PC engineering project for Resident Evil 4 (USA), SLUS-211.34.**

Windows x64 · C++ / Python · PS2Recomp · Zmbor compatibility laboratory · paraLLEl-GS

[Progress map](docs/status/README.md) · [Tests](docs/testing/README.md) · [Documentation](docs/README.md) · [Source setup](docs/GITHUB_SETUP.md)

</div>

Project-4 statically recompiles the game's EE code to native C++ and supplies a runtime for PS2 hardware and system services. IOP and other device paths still use interpretation or emulation where applicable. This is an active compatibility project, not a finished release.

**Source-only distribution:** no game disc, BIOS, extracted executable, proprietary module, generated game code, runtime capture, executable package, or save data is included. Provide your own game data locally. Existing dependency licenses are retained.

## Current progress

[![RE4 gameplay and hardware evidence map](docs/status/progress.svg)](docs/status/README.md)

Latest evidence: **27 October 2026**.

| Milestone | Verified scope |
|---|---|
| Boot, menus, new game and introductory sequences | Observed in isolated runs |
| Forest movement, aiming and shooting | Observed; backing ammunition checked |
| Room transition 0x100 → 0x101 | Real transition, then 677 stable observations |
| Inventory interaction | Observed historically; full visual equivalence still incomplete |
| Campaign save, exit, restart and reload | Verified on an earlier isolated runner/card |
| Latest VU helper-boundary candidate | Seven paired comparisons: median paired **+4.94%** in one fixed scene |
| Scene speed | Median **0.2058x → 0.2155x**; real time is 1.0x |
| Full campaign, later progression, broad combat | Not verified |
| Arbitrary-location quicksave | Not implemented |

The experimental candidate is separate from the accepted executable. Its gain does not imply campaign-wide performance or a package upgrade. VU flag coalescing, indexed retirement and coverage experiments that failed their gates remain rejected or disabled.

## Validation

- C++: **635/635** for both reference and candidate.
- VU: **3,200** full-state snapshots, 964/1,024-command workloads, budgets, continuation, queue state and GIF output compared.
- Lab Python: **104/104** in the latest complete supplemental run.
- Rendering: **37** matching guest-tagged RGBA frames; raw committed PCM prefix agreed, without speaker/AV-sync proof.
- Hardware reference: **47/55** exact on pinned **Zmbor 00173a2**, with eight known mismatches. This is separate from candidate-engine validation.
- Two full-suite invocations retained one failure each. Repaired framework tests and unchanged engine binaries form an aggregate gate; neither original invocation is described as fully passing.

See [exact results and limitations](docs/testing/RESULTS.md). Test counts are scoped evidence, not a completion percentage or a clean-clone build guarantee.

## Repository layout

```text
core/                         Reviewed PS2Recomp runtime, recompiler and native tests
ps2l/                         Project command-line tooling
tests/                        Project-4 Python tests
tools/                        Original analysis, build and diagnostic tools
profiles/                     Game identity and pipeline configuration
integrations/                 Runtime adapters
dependencies/                 Existing dependency sources and license notices
compatibility/
  tools/                      Laboratory regression, replay and measurement tools
  tests/                      Laboratory tests and source-only probe harnesses
  patches/                    Unapplied source deltas and optional VU experiment
  lab/                        Source build helpers; no compiled outputs
docs/
  README.md                   Documentation index
  status/                     English SVG map, data and evidence matrix
  testing/                    Unified test guide, source inventory and result ledger
  compatibility/reports/      Preserved laboratory engineering reports
  publication/                Source inventory and distribution boundaries
```

## Getting started

Requirements for the local native toolchain: Windows x64, Python 3.10+, Visual Studio C++ build tools and Windows SDK, LLVM/clang-cl, CMake and Ninja. Some analysis tools have additional optional dependencies. Use an x64 developer shell for native builds.

```powershell
git -c core.longpaths=true clone https://github.com/m7kor/Project-4.git
cd Project-4
python -m pip install -r requirements-dev.txt
python -m ps2l status
```

Read [source setup](docs/GITHUB_SETUP.md), [build notes](docs/01-BUILD.md) and [test setup](docs/testing/README.md) before building. The source tree deliberately omits locally generated EE/native-module sources and captured VU tables. Generate those from your own inputs and configure dependency/build paths for your machine. **A fresh public native game build has not been validated.**

Original launch scripts expect a separately assembled local game package. No ready-to-play package is offered here. Keep original game data read-only and use separate test cards and build directories.

## Testing

All distributable Project-4 and lab test sources are indexed in [docs/testing/SOURCE_INDEX.md](docs/testing/SOURCE_INDEX.md). The existing lab groups are retained:

```text
test fast        test vu          test ee          test graphics
test audio       test hardware    test dma         test iop
test integration test full        test auto
```

These are groups in the Python lab runner, not installed shell commands. Their command syntax and required local inputs are documented in the [unified guide](docs/testing/README.md). Missing private fixtures are not successful tests. Do not rewrite hardware expectations to manufacture a pass.

## Next engineering targets

1. Lossless controller recording for conflicting same-tick events and repeatable room navigation.
2. Low-overhead VU profiling of the new candidate before another optimization.
3. More post-room-transition combat, inventory, event and streaming acceptance.
4. New campaign save/reload acceptance on isolated cards for each promoted build.
5. Audio underrun attribution, speaker output, AV synchronization and frame pacing.
6. Broader independent hardware comparison and portable public build setup.

## Documentation and provenance

The main README and new navigation/status/testing guides are in English. Historical engineering reports retain their original language and revision-specific claims. [The documentation index](docs/README.md) separates current evidence from older investigations. [Publication notes](docs/publication/README.md) explain what was included from the two local workspaces and what remains private.

## Credits and licenses

- [PS2Recomp](https://github.com/ran-j/PS2Recomp): original recompiler/runtime; see [core/LICENSE](core/LICENSE).
- [Zmbor](https://github.com/m7kor/Zmbor): reference engine and hardware-regression engineering.
- paraLLEl-GS, PCSX2, Tracy and other included dependencies: their existing notices and licenses remain with their sources.
- [God of War Recomp](https://github.com/KIexster/god-of-war-recomp): inspiration for clear component-status presentation; its performance and implementation claims do not apply to RE4.

Resident Evil 4 belongs to its respective rights holders. This project is unaffiliated with them. No rights to game data or BIOS are granted by the source licenses.
''')
    print('English README, component evidence table, JSON and original SVG written.')


if __name__ == '__main__':
    main()

# Executed test ledger â€” 27 October 2026

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

## Publication-time checks

The actual public root Python suite ran403 tests on the normal Windows host: **OK,7 skipped**, in8.672 seconds wall time (7.606 seconds unittest time). Two preceding restricted-environment runs each recorded6 path-access errors and7 skips; both failures were preserved locally. Moving temporary files into the workspace alone did not resolve those errors. No source expectation was changed for this rerun. Publication content checks are separate from engine correctness.

## Publication subset

Duplicate engine/source archives, BIOS-analysis helper copies and source patch bundles were omitted after review at the user's request. The source index lists included files only. Historical635/635 and replay results are not validation of a newly rebuilt subset engine.

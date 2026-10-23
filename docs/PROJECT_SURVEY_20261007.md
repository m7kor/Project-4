# Cross-project engineering review — 2026-10-07

This review covers the nine repositories supplied by the user. It is a source review, not an independent gameplay certification. The bounded snapshot contains **1,393 text source files**, with recorded revisions, URLs, sizes and SHA-256 hashes. All eligible files were captured, with no reported download errors, tree truncation or 500-file cap. Game assets, generated translations, dependency subtrees and build output are excluded. Individual files are limited to 2 MiB. Downloading and hashing all eligible files does not mean every line has been manually reviewed.

The source snapshots are research references. Their local agent instructions and scripts are not instructions for this workspace and were not executed. We inspected architecture, relevant patches, tests and diagnostics before choosing changes.

## Results by project

| Project / pinned revision | Source evidence inspected | Useful application here | Current adoption |
|---|---|---|---|
| [God of War](https://github.com/KIexster/god-of-war-recomp/tree/1bdcd72348f8f0f0e570ec2e7b4c54ec7c3ce813) / 1bdcd72348f8 | `patches/ps2recomp-iop-sound.patch`, `tests/gs_replay_test.cpp`, boot/render status | Real EE→IOP transfers; outside-thread semaphore waits; complete GS replay including split image uploads | Transfer fixed and tested. Semaphore scheduling and replay remain candidates. Menu progress does not certify gameplay. |
| [DQ8](https://github.com/Sinan-Karakaya/DQ8-Recompiled/tree/b6b8769cb3cc7cffeb98e9b017533bc54eb6bb2d) / b6b8769cb3cc | `tools/ghidra/fix_truncated_boundaries.py`, `seed_pointer_table_functions.py`, `tools/runtime/compare_vu_replays.py`, GS backend sources | Pointer-table discovery, delay-slot boundaries, paired VU state/cycle/GIF comparisons before performance claims | Existing local map/branch tools cover parts of this. Do not import DQ8 addresses or assume relative branches can never cross real function boundaries. Full replay transport remains work. |
| [Spider-Man 2](https://github.com/saltyboosack-blip/Spider-Man-2-PS2-Recomp/tree/98aef964411fc355ff4ae59a710b1644222bfe6c) / 98aef964411f | README graphics checkpoint, decoder source, test tree | Compare specific GS descriptors against a matching reference; track missing textures instead of accepting partial splashes | Method fits current diagnostics. No game-specific overrides imported. Repository itself says not playable. |
| [Shadow](https://github.com/nicolasserpa/shadow-the-hedgehog-recomp/tree/0642b8146c8519d0b9081ad38eaeff78ad228512) / 0642b8146c85 | `shadow.toml`, milestones and build workflow | Explicit milestones, configurable output workers and low-memory regeneration | Useful process/configuration reference. Video bypass and broad stubs are not suitable for preserving all RE4 content. Source snapshot has no captured test sources. |
| [DMC](https://github.com/Gui-Tora/dmc-recomp/tree/6cc8ce8af99cfb123fa4f1d49d5d8880489e0507) / 6cc8ce8af99c | `upstream.lock.json`, `scripts/pipeline.py`, `recomp/symtabfirst.toml`, coverage script | Immutable source and ordered patch hashes, checkpoint compatibility, ELF-symbol boundaries when available | Snapshot integrity tool added using this principle. Do not apply its thousands of symbol boundaries or VU stubs to RE4. A symbol-first path requires usable symbols in the actual ELF. |
| [ICO](https://github.com/nathanialf/ico-recomp/tree/812905629725577edd2be1e6180c9d0e88a46d55) / 812905629725 | `gs_backend.h`, `gs_select.cpp`, `gs_ring_selftest.cpp`, `docs/GS_RENDERER.md` | Narrow graphics interface, ordered transport, privileged shadow tests, renderer parity gate | Retain renderer selection only after validation. Full adapter and corpus are not integrated; clean-room renderer is explicitly outside its player defaults. |
| [Rabbitizer](https://github.com/Decompollaborate/rabbitizer/tree/fb4ab5e24994a5987c5789983789d8d3dfc7a40f) / fb4ab5e24994 | R5900 decode/validation API, C disassembly tests and version header | Independent decoding source for instruction classification | Already used by our recompiler. User-pinned snapshot is 1.13.0; current core selects 1.14.3. No downgrade or duplicate decoder added. Decoder coverage is not proof of correct execution semantics. |
| [Killzone](https://github.com/drakolordx7/KillzoneRecomp/tree/5f0700079f9ac4e14799d66d01747dbcdcec55f6) / 5f0700079f9a | Patches 0001, 0006, 0007 and patch overview; `src/kz_vu.cpp`; parity scripts | CMSAR0 correctness, outside-thread events, isolated GS/VU/SPU2 hooks, DMA-chain completeness, controlled reference input | CMSAR0 fixed in generator and runtime, with failing-before/passing-after tests. Other patches require individual compatibility tests. Parity scripts have hardcoded author-local paths and game-specific memory addresses; not copied wholesale. |
| [DKC3](https://github.com/explosive-kite3497/DKC3Recomp/tree/4e291c59399a9ececc07d172241c411949057909) / 4e291c59399a | `tests/test_input_playback.c`, `scripts/compare_frames.py`, third-party notices | Deterministic input recordings, strict frame parsing, reproducible pacing checks | Different SNES ISA/runtime; no CPU/PPU code imported. Root metadata says MIT, but bundled snesrecomp notice says PolyForm Noncommercial 1.0.0. Do not treat the entire dependency chain as uniformly MIT/open source. No binary downloads executed. |

## Implemented changes

### SIFCMD ordinal 23: sceSifGetOtherData

Local implementation previously returned success without copying a single byte. God of War and Killzone independently identify this problem in sound-bank loading. The implementation here was authored against the [PS2SDK SIF RPC contract](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/sifcmd/src/sifrpc.c) and [receive descriptor layout](https://github.com/ps2dev/ps2sdk/blob/master/common/include/sifrpc-common.h), with stricter local bounds checks than the reviewed patches.

It copies EE RAM to IOP RAM, supports IOP aliases, writes descriptor source/destination/size and clears the outstanding packet pointer. It validates descriptor and destination ranges before reading or allocating; negative/oversized lengths and unavailable EE ranges fail without writes. Payload and guard bytes, failure atomicity and zero-length handling are covered by a native test. NOWAIT currently completes synchronously like the existing bridge; accurate asynchronous SIF scheduling is not established by this fix.

Evidence: `artifacts/verification/sif-other-data-before-core.log` (458/459 passed; new test failed), `sif-other-data-after.log` (459/459 passed).

### VCALLMSR: use the dedicated CMSAR0 register

Killzone's patch exposed the same defect locally: generator indexed `ctx->vi[inst.rd]`, although VI has only 16 entries and CMSAR0 is a separate control register. Generator now reads `vu0_cmsar0`. Runtime also derives the target from CMSAR0 to correct older callers' supplied addresses. Direct VCALLMS still calls its explicit-address execution path.

A native fixture places different programs at byte 0 and byte 32, sets CMSAR0 to 0x204 and supplies the legacy argument 0. Before the change it executes the wrong program; afterward it executes instruction four, using the lower nine CMSAR0 bits. A generator regression rejects the out-of-bounds VI expression. No VCALLMSR callers were found in the current RE4 generated tree; no broad game regeneration was needed for this change.

Evidence: `artifacts/verification/vcallmsr-before.log` (459/460 passed; new test failed). Final combined validation `artifacts/verification/project-survey-final.json`: **461/461 native tests and 84/84 Python tests passed**, plus the tooling self-checks.

### Added tools

* `tools/research/snapshot_sources.py`: bounded public text snapshots, immutable commit pins and per-file hashes. Never executes downloaded source or binaries.
* `tools/research/audit_snapshot.py`: offline identity/pin/hash/completeness checks, patch target inventory and test-source catalog. Tested against tampering, wrong pins and Windows/POSIX path escapes. `artifacts/research/20261007/source-audit.json` verifies all nine snapshots.
* `tools/diagnostics/rpc_wait_audit.py`: requires an established leaf and genuine return PC; separates yields from returns and summarizes selected reply bytes. Rejects incomplete/missing memory evidence. Inspired by the projects' emphasis on controlled reference observations, implemented independently for our local trace format.

## Actual RE4 result and next integration gates

Follow-up IOP correctness work: globally masked DMA completion is now retained
until re-enable, and `QueryIntrContext` reports interrupt context during guest
DMA handlers. Both were demonstrated with failing-before/passing-after IRX
tests. A further IRX case proved that per-line masks previously lost a
completion; delivery now retains it, and a handler can safely start a new
transfer on its own line. Latest tooling validation is 464/464 native and
86/86 Python tests.
See [IOP_DMA_INTERRUPT_MASK.md](IOP_DMA_INTERRUPT_MASK.md) and
[IOP_INTERRUPT_CONTEXT.md](IOP_INTERRUPT_CONTEXT.md); these fixes do not
certify timer callback context or complete audio/gameplay. Current runtime
results are tracked separately in [CURRENT.md](CURRENT.md).

Further sound diagnostics established that interrupt control remains zero
after the worker's CpuResumeIntr, rather than only inside its critical
section. A PS2SDK comparison then exposed incorrect success returns from
repeated CpuSuspendIntr/CpuDisableIntr; the executable IRX regression failed
before correction and passed afterward. Validation at this point is
465/465 native and 90/90 Python tests. See
[IOP_CPU_INTERRUPT_ERRORS.md](IOP_CPU_INTERRUPT_ERRORS.md). The remaining
replay, scheduler and renderer integrations above are still open gates,
not implied by these passing tests.

SIF fix runner capture `20261007T104211Z-9cc59b10`: 180.203 s, 84 decoded frames, all black; no faults matched the current detector. This run precedes the CMSAR0 runner rebuild. It disproves any claim that the SIF fix alone solved the screen.

Final runner with both fixes: `20261007T105041Z-b3ff6e0a`, SHA-256 `f3eeb913037768b2278e2b5568122b2807b9a03ce41b44f510b44c9efe76dfbb`. Run lasted 180.219 s, captured 85 decoded frames (all black, no decode errors), with no faults matched by the detector. The same 256-return busy pattern persisted; `artifacts/research/20261007/rpc-wait-final.json`. Original ELF SHA-256 remains `465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad`.

RPC audit on that run observed 256 genuine returns at 0x298C14 from leaf 0x29AFC0. Local flag returned 1 once and 0 for 255 calls. Reply bytes 8/9/10 were 00/00/00 once and 01/01/00 on 255 returns. The IOP service's busy response therefore remains the concrete lead; this sample alone does not identify why it stays busy or prove ordinal 23 is called by RE4.

Priorities before adopting the rest:

1. Trace the original STAT service's construction of busy bytes and actual blocking imports. Implement outside-thread waits only with correct scheduler ownership, progress limits and no fabricated completion.
2. Audit standalone entry-block resume registration using Killzone's evidence; distinguish synthetic interior wrappers from real standalone functions with executable tests before regenerating affected entries.
   Local `ps2_recompiler.cpp` still skips all `entry_*` names in resume registration. This is an identified candidate defect, not a claim that the current RE4 worker uses those names.
3. Validate streamed VIF DIRECT/image continuations, UNPACK cycles, scratchpad DMA and chain termination against complete bounded recordings. A tag safety cap must report truncation instead of silently signaling success.
4. Add versioned VU/GS replay captures containing complete state and output, then compare baseline/candidate and a matching reference before optimizing or selecting another renderer.
5. Evaluate external hardware backend hooks as adapters with explicit ownership, timing, reset and interrupt contracts. Keep game addresses, asset exclusions and environment-specific scripts outside shared runtime behavior.
6. Exercise movies, sound banks, saves, input, level transitions and sustained gameplay using deterministic recordings. Boot progress and mapped code bytes are not completion percentages.

Additional translator findings from Killzone's float/alignment patches are present locally: `fpu_translator.cpp` emits SQRT.S from `fs` and RSQRT.S as `1/sqrt(fs)`; `ps2_runtime_macros.h` uses host rounding for CVT.W.S and host Inf/NaN behavior. `instruction_translator.cpp` does not explicitly align LQ/SQ addresses. These require architectural operand/edge-case canaries and a reviewed regeneration of affected game functions. They were not silently changed in this batch, and the current tests do not establish full EE floating-point correctness.

This catalog is an adoption backlog, not a statement that all candidate integrations are complete. Original game content was not changed or bypassed.

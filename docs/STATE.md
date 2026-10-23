> الحالة التنفيذية الحالية في [CURRENT.md](CURRENT.md). هذا الملف سجل تاريخي؛ الاستنتاجات فيه قد تكون صُححت لاحقًا.

# Lodestone — project state

Append-only. Newest last. One block per session.

Format:

```
## YYYY-MM-DD  <what changed>
- changed: <file> — <what and why>
- measured: <number> — <how it was obtained>
- learned: <conclusion> — <evidence>
- next: <the single next action>
```

## 2026-10-03  session 2 — analyzer, profile validator, CLI
- changed: ps2l/analyze.py — Ghidra-free ELF analysis. New. Three design rules
  learned the hard way: scan body sections only, sort sections by address,
  treat a conditional-branch target as a label rather than a function.
- changed: ps2l/profile.py — profile validator with evidence tiers, upstream
  handler-name check, and hard failures for the settings that silently lie.
- changed: ps2l/cli.py — one entry point; `status` prints the honest picture
  including which components do not exist yet.
- changed: docs/01-BUILD.md — verified build settings, each with a citation.
- changed: profiles/SLUS-211.34/profile.toml — replaced estimates with measured
  values; boundary and evidence deliberately left EMPTY.
- changed: knowledge/dead_ends.jsonl — 30 -> 43 entries.

- measured: .text = 2,029,852 B at 0x00100000 — NOT the 0x2C9F28 PT_LOAD
  filesz I used earlier; the remainder is .data/.sndata/.rodata.
- measured: 93 .DVP.overlay.* sections, 155,808 B total, all sh_addr == 0.
  Plus .DVP.ovlytab (1,116 B = 93 x 12) and .DVP.ovlystrtab (3,465 B).
  My earlier "no overlays" claim was wrong and is retracted.
- measured: 5,904 functions, median 44 B, mean 136 B, p90 304 B, 39.75% byte
  coverage. Plausible range is 9k-16k; a Ghidra export remains the authority.
- measured: 5,702 SYSCALL sites in .text, 644 distinct 20-bit ids, 48 distinct
  10-bit ids, 1,341 with bit 10 set (immediate/non-blocking).
- measured: 60% of .text is uncovered and ALL of it is low entropy (<=7.5
  bits/byte) — literal pools and jump tables. Zero high-entropy blocks, so
  nothing in .text is compressed or encrypted.
- measured: .data is flagged 7 (R|W|X) because the EE jumps through pointer
  arrays in it.

- learned: eight bugs in my own analysis, each caught by checking a number
  against something independent. All eight are now dead_ends #0031-#0038.
  The two most consequential: SYSCALL is a top-level opcode (0x0C), not
  SPECIAL/0x0C — the wrong check undercounted by 18x; and a prologue sniff
  that accepts any $sp-touching word matches every stack frame in the program.
  Requiring a data reference as well as a real frame cut callbacks from 11,637
  to 4,484 and moved the median from 16 B to 44 B.
- learned: `PS2X_STRICT_RETURN_DIAGNOSTICS` is the highest-value flag in the
  toolchain. Default off means `jr $ra` emits a bare `pc=target; return` with
  no existence check, so a missing target is silent. profile.py now fails the
  profile if it is off.
- learned: `skip` in the TOML is a legacy field. ExportPS2Functions.java
  hardcodes `skip = []` and `skip_count = 0`. Use `stubs`.
- learned: `mmio` and `jump_tables` are read from the TOML root only, never
  from `[general]`. Under `[general]` they are silently ignored.

- next: fork PS2Recomp, apply the address-sorted section lookup from
  dead_end #0037, and configure with Ninja + clang-cl per docs/01-BUILD.md.
  That is the first action that produces a running binary, and it is the only
  thing between here and R1.

## 2026-10-03  session 3 — core forked, built, and RE4 recompiled
- changed: core/ — PS2Recomp cloned at c5a9d025 (2026-09-30, PR #256).
- changed: core/ps2xRecomp/src/lib/elf_parser.cpp — PATCH 1: address+specificity
  section ordering. Removes the header-order shadowing that `.hack//` needed four
  script iterations to work around.
- changed: core/ps2xRuntime/cmake/ReleaseMode.cmake — PATCH 2: compiler-aware
  flags. Without this, clang-cl cannot configure at all.
- changed: core/ps2xRecomp/src/runner/main.cpp + ps2_recompiler.h — PATCH 3:
  `--prune-stale` / `--prune-dry-run`, with a manifest/directory count gate.
- changed: recomp/config_re4.toml — generated from analysis, stubs empty.
- changed: knowledge/dead_ends.jsonl — 43 -> 48 entries.

- measured: core builds clean with clang-cl 23.1.1 + Ninja. ps2_recomp.exe
  links at ~1.85 MB.
- measured: RE4 recompiles end to end. 5,904 functions discovered, 5,904
  recompiled, 0 stubs, 0 skipped, **0 decode failures**. 5,905 .cpp files,
  49.7 MB, generated in ~11 seconds with 11 workers.
- measured: 33,614 resumable entry points across 2,131 owner functions.
- measured: **0 TODO_NAMED and 0 "Unhandled" in the generated tree.** 58
  handleSyscall sites; 14,441 dispatchGuestBranch sites.
- measured: regeneration is byte-stable — two consecutive runs produce an
  identical probe file (4F01BCC306D3580F). This is the reproducibility gate and
  it holds at 5,904 files.
- measured: incremental blast radius. Renaming one function in the CSV changed
  exactly 1 file (register_functions.cpp) and added 1 new file, removing 0 —
  which is the bug PATCH 3 fixes.
- measured: `PS2X_STRICT_RETURN_DIAGNOSTICS` produced no
  `GuestBranchKind::Return` in the generated code. The option lives in
  ps2xRuntime/CMakeLists.txt but the emitted `#if` is compiled into
  ps2_recomp_lib, which is a different target. **The flag as documented does not
  affect codegen** — it needs to be on the recompiler target, not the runtime.

- learned: clang-cl is not just "MSVC but clang". `if(MSVC)` is true for it,
  and `MSVC_VERSION` is defined too, so neither discriminates. Only
  `CMAKE_CXX_COMPILER_ID` does. The Agent SKILL's headline claim — clang-cl+Ninja
  takes a full rebuild from 20-30h to ~1h — was **not reachable from a clean
  checkout**, because upstream hands clang-cl three switches it rejects. Every
  project following that advice hits this wall.
- learned: FetchContent needs network for submodules; vendoring the five
  deps into core/deps/ and pointing FETCHCONTENT_SOURCE_DIR_* at them makes
  configure take 45s instead of hanging on recursive submodule clones.
- learned: **I deleted all 5,904 generated files with the pruner** on its first
  run. Root cause: I stripped `_0xADDR` from the filename before comparing it
  to manifest names that include the suffix, so nothing matched and everything
  looked stale. Two lessons, both now in the code: the stem IS the manifest
  name, and a pruner must refuse to act when the manifest count and the
  directory count disagree. Regeneration restored everything in 11 seconds —
  the only reason this was an annoyance rather than a lost week.
- learned: renaming a function in the CSV never deletes the old file. Upstream
  only writes. Two translation units then claim the same guest address, and the
  stale one is a false positive for every tool that reads the directory.

- next: fix PS2X_STRICT_RETURN_DIAGNOSTICS so it reaches the recompiler target,
  then compile the generated tree against the runtime. That is the first time
  this project produces a linked executable, and it will expose the real
  compile-time cost of 5,904 TUs.

## 2026-10-03  session 4 — first fault root-caused, fixed, and the fault is gone
- changed: ps2l/analyze.py — the triage loop is now closed (analyze -> triage ->
  analyze, four passes). Added `_scan_multi_target()`, `_scan_hole_prologues()`,
  `_holes()`, `_has_return()`, `_rollback_walk()`, `plausible_entry_op()`, and a
  `find_unresolved_returns()` feed-back path. Five real defects fixed, all
  recorded as dead_ends #0053-#0057.
- changed: core/CMakeLists.txt — PATCH 7: `add_compile_options(/EHsc)`.
- changed: core/CMakeLists.txt, core/deps/ — vendored raylib 5.5 into deps/ so
  `FETCHCONTENT_SOURCE_DIR_RAYLIB` resolves. Without it `ps2_audio.cpp` cannot
  find `raylib.h` and 6,065 objects build before the failure.
- changed: knowledge/dead_ends.jsonl — 52 -> 58 entries. #0053-#0058.
- changed: profiles/SLUS-211.34/profile.toml — R0_canary and R1_boot marked done,
  each with its evidence string.

- measured: the runtime fault `kind=Return source=0x0029CC28 target=0x002A1C24`
  is **not a missing function**. 0x2A1C24 is the instruction after
  `jal 0x29CC20` at 0x2A1C1C, i.e. a return address that lands mid-body inside
  function 0x2A1BE8. Zero J/JAL references, zero J references, zero lui+ori
  materialisations, zero pointer-table entries — because nothing should point
  at it. It is the callee's `jr $ra`, textbook MIPS, and the diagnostic was
  correct to fire while the analyzer was wrong to leave it unmapped.
- measured: ending a body at its first `jal` (#0057) was the single biggest
  error in the analyzer. Fixing it: coverage **55.90% -> 94.69%**, median
  function size **36 B -> 96 B**, max 6,072 -> 12,252 B. Functions 10,189 ->
  7,977, because truncated fragments were being counted as whole functions.
- measured: after the fix, 0x2A1C24 is a registered resume entry:
  `g_ps2RecompiledFunctionTable[427783] = FUN_002A1BE8_0x2a1be8; // 0x2a1c24`,
  reached through `case 0x2a1c24u: goto label_2a1c24;`.
- measured: regenerated 7,978 .cpp / 117.7 MB in 18 s; `--prune-stale` removed
  exactly 40 stale files and reported `40 stale, 7977 live, 7977 in manifest`.
- measured: full runner build succeeds. 8,058 build edges, 0 failures,
  **541 s wall on 12 cores**, ps2EntryRunner.exe = 96,863,232 B (92.4 MB).
- measured: the fault is gone. Re-ran the runner: **no `missing-target` line at
  all**, no "No exact recompiled function", no unhandled-syscall error. Execution
  passes 0x2A1C24 and runs on.
- measured: new frontier. The guest now spins in `FUN_002A1CE0` -> `FUN_002A1CC8`
  (`syscall 0x83`, `FindAddress`), 100,000 consecutive calls in 60 s and no
  progress. 0x2A1CC8 is a 12-byte leaf: `addiu $v1,$zero,0x83; syscall; jr $ra`.

- learned: "the runtime reported address X as missing" and "X is not a function
  entry" are not the same claim. Verifying the disassembly first inverted the
  conclusion: the analyzer was wrong five times over, not the runtime.
- learned: `visited` is load-bearing state, not a cache. Rolling back `funcs`
  without rolling back `visited` makes an address permanently invisible, which
  is strictly worse than never scanning it.
- learned: exceptions and raylib are the two upstream gaps between "clang-cl
  configures" and "clang-cl links a runner". Both are one line each, and both
  are invisible until you actually attempt the full build.
- learned: sccache on Windows fails under Ninja's full parallelism with
  `Only one usage of each socket address ... (os error 10048)` — a port-exhaustion
  race in sccache's local server, not a compile error. `-DPS2X_ENABLE_SCCACHE=OFF`
  builds clean. Also worth knowing: with a PCH, 5,997 of 6,078 requests are
  non-cacheable anyway (`/Fp`), so sccache was buying nothing here.

- next: R2. Diagnose syscall 0x83. `FUN_002A1CE0` calls it with $a0=0x8000,
  $a1=0x8008 in a retry loop whose exit condition never becomes true, so the
  answer it gets back is wrong or the syscall is mis-mapped. Establish the real
  semantics of 0x83 before touching the AFS layer.

## 2026-10-05 session 5 — the 0x83 spin is solved, and the survey stops being an opinion
- changed: ps2l/profile.py — `check_measured()` re-derives every `[analysis]`
  figure `analysis.json` can produce and makes a mismatch a HARD error. A profile
  that can hold a stale number is the failure this project exists to end.
- changed: ps2l/analyze.py — `_scan_prologues()` no longer requires a prologue;
  a data-referenced code address that is not inside a known body is mapped, as
  `callback` with a frame and `orphan_ref` without one. Added
  `_scan_syscall_handlers()` for immediates at syscall sites.
- changed: core/ps2xRuntime/src/lib/ps2_runtime.cpp — PATCH 11: `$ra == 0` is
  the invocation-completion sentinel, not a missing branch.
- changed: core/.../Syscalls/System.cpp — PATCH 10: a registered syscall handler
  with no recompiled function is named once per (id, handler) instead of
  silently returning KE_ERROR.
- changed: profiles/SLUS-211.34/profile.toml — the stale session-2 census
  (5,904 / 39.75%) replaced with measured values; `R0_canary` split into
  `R0_pipeline` (done) and `R0b_canary` (pending, honestly).
- changed: README.md, RE4-FLAGSHIP.md, recomp/config_re4.toml — every retracted
  or stale claim corrected in place.
- changed: research/ADOPTED.md — new. What we take from the other 20 projects,
  what we refuse, and three claims in ECOSYSTEM-REPORT.md that source reading
  invalidated.
- changed: ps2l/*.py — console output forced to UTF-8; a Windows console is not.

- measured: RE4 syscall census — 8,297 functions (was 7,977), coverage 95.72%
  (was 94.69%), median 92 B, max 11,612 B, 8,337 generated .cpp, 119.2 MB.
  `orphan_ref` accounts for 439 of the +320 net new entries.
- measured: `table@0x32ACD0 = { 0x83, 0x2A1C88, 0x5A, 0x2A1C50 }` read
  directly out of the ELF.
- measured: `0x2A1C88 = lw $v0,0($a0) ; beq $t0,$t0,+0x0B ; lw $v0,0x2B($s0)`.
  No frame. `looks_like_prologue` correctly said no, and that was the bug.
- measured: the 0x83 loop now exits after 3 calls. Before: 15,000+ in 30 s with
  no progress. Trace in `analysis/boot-trace-re4.txt`.
- measured: build 8,343 objects, link clean. clang-cl warns `/arch:SSE2` invalid
  and `/GL` unused on every TU — upstream's MSVC profile, mostly inert here.

- learned: **`syscall 0x83` is not a kernel syscall.** RE4 installs its own
  handler with `SetSyscall` — a public libkernl API, declared in ps2sdk
  `ee/kernel/include/kernel.h` as `void SetSyscall(s32 syscall_num, void
  *handler)` — and calls `SetSyscall(0x83, 0x2A1C88)` and
  `SetSyscall(0x5A, 0x2A1C50)` at 0x2A1DE8. Every subsequent 0x83 call shows
  `override=0x2a1c88` and never reaches `case 0x83`. Three sessions were spent
  on a `case` label that the guest's own code had already overridden.
  dead_ends#0065.
- learned: `ps2_call_list.h` carries **no numeric IDs**. It is an X-macro list
  consumed only for name→function-pointer resolution in `game_overrides.cpp`.
  Flattening it and counting entries produces a plausible newlib libc table that
  has nothing to do with syscall numbering. The dispatcher's numbers are real
  kernel constants — ps2sdk's `SetMemoryMode`, `GetMemorySize`, `Deci2Call`,
  `InitTLB` and `SetSyscall` all land where the runtime expects them.
- learned: **a one-shot diagnostic latch is a single-use resource and the
  sentinel path spends it.** `reportMissingFunction`'s `firstReport` fired on
  the `$ra == 0` handler return, which is correct behaviour and the wrong place
  to look. PATCH 11.
- learned: the previous session's diagnosis — "$a0=0x8000, $a1=0x8008" — was
  never measured. The real values are `$a0=0x80000000`, `$a1=0x80080000`,
  `$a2=0x2A1C88`. Two hex digits were dropped and a pointer was turned into a
  loop counter.
- learned: upstream `ps2xIOP` **does** run IRX modules on an R3000A
  interpreter with a virtual IOP kernel (`ps2xIOP/README.md`). The ecosystem
  report said otherwise, and the error made IOP look like the largest item on
  the risk register. It is not.
- learned: the SKILL's "clang-cl ≈ 1 h, and delete Unity Build" is refuted
  against upstream source — `if(MSVC)` is true for clang-cl, so it gets the same
  `/O2 /GL /LTCG /arch:AVX2` profile, and upstream defaults unity ON. Our own
  `unity_build = false` mandate was inherited from that claim and has never
  been measured. It needs an A/B, not a citation.

- next: R1c. The guest now makes no syscall at all for 40+ s after 0x83
  resolves, which means no new instrumentation fires and the next fault is
  invisible. It needs a cycle budget and a progress watchdog — detect "no
  forward PC in N million instructions" and report the hot address — not more
  syscall tracing. After that: `--per-file N` chunked emission, which AC5 uses
  to compile 10,742 functions into 43 files in 15 s against our 8,337.

## 2026-10-05 session 6 — the silence is not a hang, and the build loop is dead
- changed: ps2l/build.py — new. `lodestone build`, the command this repo did
  not have. Owns the stale `.ninja_lock`, the LLVM `PATH`, and an explicit stamp
  check that re-runs CMake only when the generated tree really changed.
- changed: core/ps2xRuntime/src/lib/GuestPcProfile.{h,cpp} — new, PATCH 12.
  Guest PC histogram, allocation-free, compile-time gated.
- changed: core/ps2xRuntime/src/lib/Kernel/EeScheduler.cpp — one `#if`-gated
  sample per dispatch; whole-run totals on clean shutdown.
- changed: core/ps2xRuntime/CMakeLists.txt — PATCH 13: `CONFIGURE_DEPENDS`
  removed from the 8,337-file runner glob, and its replacement made explicit.
- changed: knowledge/dead_ends.jsonl — 65 → **68** (#0066–#0068).

- measured: **`ninja` cost 462 s per invocation and that was not a hang.**
  The work list was one link. The other 460 s was CMake re-verifying a
  `CONFIGURE_DEPENDS` glob over 8,337 generated files before ninja started.
  Same invocation after PATCH 13: **10 s**. A killed build also leaves a
  `.ninja_lock` that makes the *next* ninja wait forever with no output at all
  — that is the thing that reads as "infinite loop". Both now handled by one
  command instead of tribal knowledge. dead_ends#0068.

- measured: **RE4 is executing six addresses, not hanging.** The guest PC
  profile shows `0x100008` (entry), then `0x2a1c88`, `0x2a1cd0`, `0x2a1d3c`,
  `0x2a1d50`, and then `0x2a1ca0` for **100% of every remaining dispatch**.
  `0x2A1CA0` is a linear scan — `lw $v0,0($a0)` / `beq $v0,$a2` /
  `addiu $a0,$a0,4` — over `$a0=0x80000000 .. $a1=0x80080000`, which is
  physical `0 .. 0x80000`, **131,072 words**. It is grinding through a 512 KB
  search, not looping on one value. dead_ends#0066.

- measured: **dispatch rate 126/second.** At 32 EE cycles charged per back-edge
  that is 4.19M cycles ≈ 14 ms of emulated time, a plausible cost for the scan
  on real hardware. The 17 real minutes it actually takes is entirely host-side:
  the generated code calls `runtime->eeCheckpointDue()` on every backward edge
  (`FUN_002A1C88_0x2a1c88.cpp:98`), `checkpointDue()` returns true whenever
  `m_eeCycle >= nextDeadlineCycle`, and that stays true continuously once the EE
  counter runs ahead of the host clock — so every back-edge costs a scheduler
  round-trip plus a host-time pacing wait. **Not fixed.** The fix is in the
  pacing policy, not in the charge, and guessing at it would replace a measured
  17 minutes with an unmeasured something.

- learned: **`PS2_RAM_MASK` already translates KSEG0 correctly.** The hypothesis
  was "0x80000000 is unmapped, so the scan reads out of bounds and never
  matches". It is not: `Ps2FastRead32` does `addr & PS2_RAM_MASK`, which is
  exactly `Ps2DirectMappedPhysicalAddress`. The scan is reading real RAM. Two
  plausible-but-wrong diagnoses were killed here by reading the header instead
  of reasoning about it — and one of them, "the recompiler mistranslated
  `ori`", was doubly wrong because `0x3c048000` is `LUI`, not `ORI`.

- learned: **the profiler invalidated its own first measurement.** At
  `PS2X_PC_PROFILE_INTERVAL=1` it reported 71 dispatches/second; the same
  binary at interval 200 reports 126. `reportInterval()` called `getenv` on
  every sample and `reportWindow()` sweeps 131,072 slots. Fixed by reading the
  override once. This is DC2's "arm observability" rule applied to an
  instrument instead of an A/B arm: a sampler that dominates what it samples
  reports a rate that is a property of the sampler. dead_ends#0067. **Every
  performance number from this profiler must name the interval it was taken
  at.**

- next: R1c, properly. The blocker is characterised: a 131,072-word scan
  running at 126 iterations/second because every back-edge yields. Two things
  must be measured before either is changed — what fraction of a back-edge
  checkpoint is `processDueDeadlines()` host-time pacing versus scheduler
  bookkeeping, and what the same scan costs with the charge raised from 32
  cycles. Then R2 (AFS) is genuinely unblocked, because boot now has a known
  cost instead of an unknown hang.

## 2026-10-05 session 7 — the numbers were wrong twice, and the scheduler is innocent
- changed: core/ps2xRuntime/src/lib/GuestPcProfile.{h,cpp} — phase accounting
  (`Events` / `Checkpoint` / `Guest` / `Other`), five `steady_clock` reads per
  dispatch, same compile-time gate so an OFF build is unchanged.
- changed: core/ps2xRuntime/src/lib/Kernel/EeScheduler.cpp — four `#if`-gated
  `phaseBegin`/`phaseAdd` calls around the loop body.
- changed: ps2l/build.py — `PS2X_ENABLE_AGRESSIVE_LOGS=OFF` by default, plus a
  reconciliation against `CMakeCache.txt` on every invocation.
- changed: profiles/SLUS-211.34/profile.toml — **R1c's central claim retracted
  and replaced**, see below.
- changed: knowledge/dead_ends.jsonl — 68 → **72**.

- measured: **99.5% of host CPU is inside the recompiled function.**
  `events=0us (0%) checkpoint=17436us (0.45%) guest=3856186us (99.53%)
  other=791us (0.02%)`. Four hypotheses eliminated in one measurement, including
  the two that had each already cost a round — scheduler event processing and
  checkpoint/pacing. The instrument's own cost was checked rather than assumed:
  it inflates per-dispatch figures by roughly 2.5×, so none of its absolute
  numbers are performance claims.

- measured: **turning the function-log tracker off bought exactly nothing.**
  126 dispatches/second and 33 s CPU per 30 s wall, identical with
  `PS2_FUNCTION_LOG_TRACKER` on and off. The exe shrank 6,175,232 bytes, so
  the code genuinely went away. The flag is still OFF by default because two
  flushed file writes per function call is indefensible in a hot path — but a
  changelog claiming a speedup there would be a lie, and dead_ends#0069 now
  says so in those words.

- measured: **the scan completes and boot resumes.** 500 s of runtime produced
  `syscall 0x83` calls with new arguments — `$a0` cycling 4, 5, 4, 5 — after
  the initial `0x80000000 / 0x80080000` range call. The guest is enumerating
  something through its private syscall. It is slow, not hung.

- **retracted: "126 iterations/second" and "17 minutes".** Both were wrong, and
  both are now fixed in `profile.toml`, `README.md` and here. The PC sampler
  reads `ctx->pc` at *dispatch* boundaries and a dispatch contains many scan
  iterations. The corrected figure is **~60 s per completed 131,072-iteration
  scan ≈ 457 µs per five-instruction loop body** — still roughly 1000× slower
  than native, but a different claim, and the mechanism that explained the old
  one ("every backward edge yields") is falsified by the phase timer at the same
  moment. dead_ends#0072. **Rule adopted: every number in this repo names its
  unit.**

- learned: a wrapper that manages a configuration it does not own must
  reconcile against the owner's cache every time. `lodestone build` asked CMake
  to turn a flag OFF, tested membership against a list whose elements had a
  `-D` prefix, silently never fired, and burned a 457-second rebuild with the
  flag still ON. CMake `-D` values are sticky and invisible to ninja: nothing
  rebuilds when a diagnostic flag changes and nothing says it did not.
  dead_ends#0073.

- next: R1c, localised. The cost is inside a recompiled function body — five
  instructions costing 457 µs. The next measurement must be inside that body,
  not around it: per-operation timers in the translation macros (`READ32`,
  `dispatchGuestBranch`, the register accessors) behind the same gate. Guessing
  again is what cost sessions 6 and 7; the phase timer exists so that the next
  answer costs one measurement instead of one round. After that, R2 (AFS) —
  boot now has a known cost instead of an unknown hang, which is what R2 was
  blocked on.

## 2026-10-05 session 8 — a counter beat a stopwatch, and two more numbers died
- changed: core/ps2xRuntime/src/lib/ps2_runtime.cpp — `eeCheckpointDue()` now
  phase-timed, which puts a counter *and* a stopwatch on the one out-of-line
  call in a typical guest loop body.
- changed: core/ps2xRuntime/src/lib/GuestPcProfile.{h,cpp} — per-phase start
  times and per-phase call counts; the report prints `n=` and `avg=` per phase.
- changed: profiles/SLUS-211.34/profile.toml — R1c retracted **again**; the
  corrected figures are in.
- changed: knowledge/dead_ends.jsonl — 72 → **74**.

- measured: **the scheduler, the syscall path and the diagnostics are all
  innocent.** Whole-run host phase split against 27,100 ms of process CPU:
  `guest=21,960 ms (81%) checkpoint=114 ms (0.4%) events=0 ms other=0 ms`,
  with 5,000 ms outside the scheduler loop and not yet attributed.

- measured: **`eeCheckpointDue()` costs 1.5 nanoseconds.** It was called
  15,360,459 times in 25 s and consumed 114 ms in total. It was the third
  candidate I instrumented in a row on the theory that "the last remaining
  out-of-line call" must be the cost. It is 0.4% of CPU. dead_ends#0075.

- **the useful number came from the counter, not the stopwatch.** The recompiler
  emits `eeCheckpointDue()` on every guest backward edge, so **its invocation
  count is a free, exact iteration counter for the whole guest** — no sampling,
  no instrumentation cost, no unit ambiguity. That single fact resolves three
  bad inferences at once:

  | quantity | value |
  |---|---|
  | guest iterations in 25 s | **15,360,459** |
  | rate | **614,000 iterations/second** |
  | cost per five-instruction loop body | **1.43 µs** |
  | full 131,072-iteration scan | **0.19 s** |

  Not 17 minutes. Not 60 seconds. **0.19 seconds.** Both earlier figures were
  inferences from a trace, and both were wrong.

- **retracted: "~457 µs per iteration" and "60 s per scan".** Session 7 got a
  better number and it was still wrong — it assumed one syscall per scan from a
  trace showing 8 syscalls in 500 s, which assumes the guest does nothing else.
  dead_ends#0072.

- learned: an instrument can report an impossible number and be believed. The
  phase timer kept one shared `m_phaseStart`; `eeCheckpointDue()` nests inside
  the guest function and overwrote it, so `Guest` collapsed to 0 µs while the
  process burned 27 s of CPU. Per-phase starts fixed it and cannot collide,
  because no phase re-enters itself. Note the phases are no longer a partition
  — Guest includes the checkpoint nested inside it — which is why the report
  prints percentages of the accounted total and does not claim a decomposition.
  dead_ends#0074.

- learned: this is the **third** time the cause turned out to be "the code I
  read last" (#0070, #0069, #0075). The rule that actually worked both times
  was to find a measurement that is *impossible under the hypothesis*: one
  thread at 110% of wall rules out all blocking; 1.5 ns × 15.36 M rules out the
  checkpoint entirely; a call count that is definitionally the quantity of
  interest beats any stopwatch.

- **where this leaves R4.** There is no performance blocker in the runtime's own
  machinery. Guest instruction bodies run roughly 300× native, which is a
  performance ceiling for this architecture and a real number to carry into
  R7, but it does not stop boot. The 5 s of CPU unattributed outside the
  scheduler loop, and whether boot reaches graphics initialisation at all, are
  the two open items; a 20-minute run is in flight to answer the second.

## 2026-10-05 session 9 — R1b reopened, and it was never closed
- changed: profiles/SLUS-211.34/profile.toml — **R1b_sema `done` → `pending`**.
  See below for why.
- changed: knowledge/dead_ends.jsonl — 74 → **75**.

- measured: **a 20-minute boot run produces 17 syscalls and nothing else.**
  `0x83 x17, 0x40 x2, 0x74 x2, 0x3c x1, 0x3d x1`, and the `$a0` of every one of
  those 17 alternates `4, 5, 4, 5, 4, 5…` with no third value and no exit. One
  iteration per ~70 seconds, forever. No other syscall id, no branch
  diagnostic, no fault, no progress.

- **R1b_sema was closed on bad evidence and is now reopened.** The stage's own
  exit criterion reads *"the guest passes the last resolved syscall with defined
  semantics instead of spinning in a retry loop"*. The evidence offered for
  closing it was that the `0x83` loop exits after three calls — which was true,
  and was one loop. There is a second one behind it, and the evidence never
  excluded it. A stage is not closed because the loop you were watching
  stopped; it is closed when the loop you have not found yet is gone.
  dead_ends#0076.

- what this rules out, and what it does not. The **mapping layer is correct**:
  `override=0x2a1c88` on every call, the handler is a real recompiled
  function, `$v0` propagates through `onComplete`, and the guest burns
  614,000 iterations/second while doing it. Every host-side suspect measured
  this session is innocent — scheduler 0%, checkpoint 0.4%, events 0, other 0.
  What is left is **semantic**: `FUN_002A1C88` returns something the caller will
  not accept, and the caller's only exit is a retry. That is a guest-behaviour
  question, not a runtime-mechanism one, and no amount of further host
  profiling will answer it.

- next: `FUN_002A1C88`, statically. It is 0x3C instructions of linear scan plus
  three exits; the question is which return path the recompilation takes for
  `$a0=4` and `$a0=5`, and what the caller at `FUN_002A1CE0` expects `$v0` to
  be. Reading those two functions against the register file at the point of the
  call is a static task with the ELF already on disk — no build required — and
  it is the first thing in three sessions that is a reading problem rather than
  a measuring problem.

## 2026-10-05 session 10 — read the code; the blocker is finally named
- changed: core/ps2xRuntime/src/lib/Kernel/Syscalls/System.cpp — PATCH 14,
  a return-value trace inside `onComplete`, capped at 64 lines. It must live
  there and not after `dispatchNumericSyscall`: that dispatch is asynchronous,
  so the return value does not exist yet at the call site and a trace there
  prints a stale `$v0`.
- changed: profiles/SLUS-211.34/profile.toml — R1b_sema evidence rewritten
  from measurement; R1c unchanged.
- changed: knowledge/dead_ends.jsonl — 75 → **76**.

- measured: **`$v0 = 1`.** The 0x83 handler returns 1 on a not-found exit. It
  is not a corrupted return value — it is what the function returns, because
  `$v0` still holds the `sltu $v0,$a0,$a1` predicate from the loop tail.

- **the caller, read in full from the recompiler's own disassembly comments.**
  `FUN_002A1CE0` registers `SetSyscall(0x83, 0x2A1C88)` and
  `SetSyscall(0x5A, 0x2A1C50)` from the table at `0x32ACD0`, then runs a
  **two-cursor convergence loop**:

  ```
  s3 = search(0x80000000, 0x80080000, key=0x2A1C88)   ; s1 = s3 - 0x20C
  s2 = search(0x80000000, 0x80080000, key=0x2A1C50)   ; s0 = s2 - 0x168
  while (s1 != s0) {
      s3 = search(s3+4, 0x80080000, 0x2A1C88);  s1 = s3 - 0x20C
      s2 = search(s2+4, 0x80080000, 0x2A1C50);  s0 = s2 - 0x168
  }
  sw s1, 0x32ACC8
  ```

  Exit requires `s3 - s2 == 0xA4` **exactly**. Both searches fail, so
  `s3 == s2 == 1`, so `s3 - s2 == 0` forever and **the exit condition is
  unreachable**. The `$a0` alternating `4,5,4,5` is `(s3+4)` and `(s2+4)`
  with both cursors at 1. That is the whole symptom, explained.

- **why the search never succeeds, and it is not the runtime's fault.** The
  first call searches the KSEG0 range `0x80000000..0x80080000`, which masks to
  physical `0..0x80000` = 512 KB. The keys it is looking for are the handler's
  own addresses, stored at `0x32ACD4` and `0x32ACD8` — physical `0x32ACD4`
  = 3,386,580, **outside the searched range by a factor of six**. The caller
  is asking the handler to search a range that cannot contain the data.

- **so this loop is very likely a symptom, not the cause.** Something must copy
  that table down into the first 512 KB, or the range must be materialised
  differently, and neither has happened. The syscall trace agrees that the stall
  is upstream: the last kernel calls before the loop are `0x3C`, `0x3D`,
  `0x40 ×2`, `0x74 ×2`, with **no `open`, no `read`, no `sceIo` at all**. A
  game that has not touched the disc cannot have populated a table.

- learned: two false leads came from reading the generated code, and both are
  recorded because both were close. The `BEQL` delay slot at `0x2A1C94` looks
  like it executes unconditionally — it does not; `emitConditionalBranch`
  emits the likely case inside `if (branch_taken)` at
  `control_flow_emitter.cpp:489`. And `$v0 = 1` looks like ABI corruption —
  it is the callee's own return value. dead_ends#0077.

- next: R1b_sema is no longer a performance question and never was. The
  question is now **why physical `[0, 0x80000)` does not already contain what
  RE4 expects**, and the answer is upstream of this loop. Concretely: read
  what wrote the table at `0x32ACD0` and what should have copied it low —
  `FUN_002A1C50`, the second handler, has never been traced at all (the syscall
  trace shows 0x5A zero times in 20 minutes), and a handler that is registered
  but never invoked is itself worth a number.

## 2026-10-05 session 11 — differentiator #2 shipped: auto-triage
- changed: **ps2l/triage.py (new, ~530 lines)** — fault capture → ranked,
  falsifiable diagnosis. Signature catalogue, behavioural analysis, hypothesis
  ranking, dead-ends cross-reference, JSON output, `--selftest`.
- changed: ps2l/cli.py — `triage` registered, in the docstring and in `status`.
- changed: README.md — the auto-triage row, with its test count.

- **measured: 6/6 self-test cases pass**, across three genuinely different
  failure classes — a two-state stall, a predicate that never flips, an
  unaligned access, a missing override handler, a syscall in a delay slot, and
  a TLB miss. Three classes matters: a triage engine that only recognises the
  failure it was born with is not a triage engine.

- measured: **on RE4's real captures the tool reaches the same conclusion the
  hand analysis reached after three rounds**, without being told:
  `boot-trace-re4-v0.txt` → "the guest is alive and repeating — a semantic
  stall" + "the stall is upstream of what we are watching"; and the upstream
  call is now driven by *which kind* of syscall was seen — no EE file-I/O id
  (`0xA4..0xA9`, `0xB8..0xC4`) at all — rather than by how many ids there
  were, which was the first and wrong version of that test.

- what makes it a differentiator rather than a log filter. Every hypothesis
  carries a **falsifier**: the measurement that would kill it. That is not
  decoration — this project's single most expensive recurring failure has been
  naming a cause without a measurement that rules out the alternatives, seven
  times out of seventy-seven (`#0069`, `#0070`, `#0075`, `#0077`). Encoding the
  rule into the tool is the only version of it that survives a tired port
  author. Exit status reports whether **we** understood the capture, not
  whether the game worked; an unclassifiable capture is a non-zero exit,
  because that is the thing that is usually wrong.

- learned: **the first version classified a stall-only capture as
  "unclassified fault".** That is not a neutral result — it is the
  non-answer this tool exists to replace, produced by the tool itself, on the
  project's own capture. Two fixes, both worth more than the bug:
  a structural `guest-syscall-activity` signature, so a live-but-stuck guest
  is a recognised class rather than an absence of evidence; and a lowered
  threshold on the `$v0`-never-flips rule from four identical returns to two,
  with the falsifier carrying the honesty that thin evidence requires.

- learned: the two-state-machine detector wanted **four** observations, not
  six. Two complete periods of a 2-cycle is the minimum that distinguishes
  "the guest is cycling" from "the guest repeated a value once". The threshold
  was arbitrary and the self-test caught it immediately — which is the reason
  the self-test has real cases in it rather than examples copied from the code
  being tested.

- next: R2 (AFS) is now genuinely reachable, because R1b_sema is understood
  rather than merely slow. The immediate R4 question stays the one triage just
  re-stated: find what should have written into physical `[0, 0x80000)` before
  `FUN_002A1CE0` runs. A second differentiator — the DiffView oracle against
  PCSX2 — is untouched and remains the largest single gap.

## 2026-10-05 session 12 — differentiator #1 shipped: the DiffView gate
- changed: **ps2l/diffview.py (new, ~490 lines)** — frame differ that is a
  *gate*, not a screenshot comparison. PPM in, PPM out, no image library.
- changed: ps2l/cli.py — `diffview` registered; the differentiator row now
  reads "DiffView differ" so it is not confused with "reference frames exist".
- changed: README.md, analysis/frames/_selftest/ — three fixture frames.

- **measured: 7/7 self-test**, and then verified end to end on real files. A
  64×48 frame with one scanline perturbed and one pixel blacked produced
  exactly `differing 65 (2.1159%)`, delta histogram `8:64 120:1`, bounding box
  `x 0..63 y 10..20`, and exit 1; the same file against itself produced
  `PASS - 0 differing pixel(s)` and exit 0. The counts are the ones the fixture
  was built to have, not ones that merely look plausible.

- **the self-test found a real bug in the gate.** `passed` was
  `differing <= tolerance`, so comparing a 32×24 frame against a 4×4 one with a
  large tolerance returned **PASS**. The comparison had effectively been told to
  ignore the one thing it exists to surface — and a size mismatch is not noise,
  it is a resolution or FBP-setup bug, and the two images are not measuring the
  same thing at all. `passed` now requires `size_match` unconditionally, and a
  dedicated case pins it.

- learned: **a verdict a human cannot read is not a verdict.** The report line
  "max channel delta" carried a Greek delta; on a stock cp1252 console the tool
  exited 1 with a traceback *while printing its own result*. Output is now
  ASCII-only by construction, and stdout is reconfigured to UTF-8 with
  `errors="replace"` as a second line of defence. Same lesson as `triage`, one
  round earlier, which means it is a project-level habit now: non-ASCII in a
  diagnostic is a defect.

- **what makes this a differentiator rather than an `cmp`.** It separates three
  failures that eyeballing merges into "looks wrong": a pixel in the wrong
  *place* (geometry), a pixel with the wrong *value* (colour — shown per
  channel, so a uniform R shift is visible as an R bias rather than vanishing
  into a max), and a size mismatch. And the exit code is quantised: `>1%`
  differing is reported as structural, because at that scale it is never
  rounding.

- **the oracle refuses to lie about its own absence.** `diffview oracle` counts
  a frame as a reference only if a provenance sidecar sits beside it; without
  one it prints "WITHOUT provenance (do NOT count as references)" and exits 1.
  Its first version reported `PRESENT (0 file(s))` merely because the test
  fixture directory existed, which is the exact false green the command exists
  to prevent — caught by running it against the fixtures I had just created.
  **State right now: no PCSX2 frames have been captured, so the oracle exits 1
  and says so.** Comparing two of our own frames verifies reproducibility, not
  correctness, and the tool says that in those words.

- next: the remaining gap on this differentiator is the reference *corpus* —
  capturing PCSX2 frames at named ticks with provenance. That needs PCSX2
  present and, more importantly, needs RE4 to render at all. So DiffView and R4
  are the same blocker seen from two sides, which is worth stating plainly
  rather than pretending they are independent work items.

## 2026-10-05 session 13 — differentiator #3 shipped: the port agent
- changed: **ps2l/agent.py (new, ~430 lines)** — the port loop and its ledger.
- changed: ps2l/cli.py — `agent` registered; the differentiator row is now
  driven by the file rather than hard-coded `False`.
- changed: README.md.

- **measured: 5/5 self-test**, and then run end to end against RE4's *real*
  capture, not a synthetic one. The loop's runner interface is injected, so the
  loop's logic is exercised without needing a game to boot — a port loop that can
  only be tested by porting is a port loop whose logic is never tested.

- what it does that hand-porting does not. The loop is the easy half:
  run → triage → act → re-run. The ledger is the half worth building. Every
  hypothesis is recorded append-only with its evidence, its disposition and —
  when it was disproved — **the measurement that disproved it**. A rejected
  hypothesis is never proposed again, and when every hypothesis on a capture is
  rejected the loop exits 3 rather than trying harder. This project has
  retracted enough published numbers to know that "we tried that, it did not
  work" is the first thing lost when the knowledge lives in someone's head, and
  the first thing that makes the ninth port slower than the first.

- **the safety property, verified on the hard case.** Only hypotheses with a
  *mechanised* remedy are applied; the rest are surfaced. Run against
  `analysis/boot-trace-re4-v0.txt` — the actual RE4 stall — the agent marked
  **both** hypotheses `(human)` and applied nothing:

  ```
  [1] (human) the guest is alive and repeating -- a semantic stall, not a crash
  [2] (human) the stall is upstream of what we are watching
  ```

  That is correct and it is the point. A semantic stall has no mechanical fix,
  and an agent that produced one anyway would be re-introducing `#0070` — naming
  a cause because it was the most recently read idea — with a loop and a
  progress bar to make it look rigorous.

- learned: **the self-test found that `run_loop` re-loads the ledger from disk,
  so a caller cannot pre-seed state.** The rejected-hypothesis case passed in
  memory and then vanished. It is the right behaviour for the CLI — a fresh
  iteration should not inherit a caller's object graph — but it means every
  state transition has to go through `save()`. The fix belongs in the test, and
  the test now says why in a comment.

- learned: a hypothesis must be keyed on its **title**, never on its evidence.
  Evidence changes every iteration — syscall counts, capture line numbers — and
  keying on it would reset the ledger on every pass and destroy exactly the
  history the ledger exists to keep. That case is pinned by the self-test.

- **where the objective stands.** All three differentiators now exist and are
  self-tested: DiffView 7/7, triage 6/6, agent 5/5. What none of them can do is
  verify RE4, because RE4 does not render — and the reason it does not render is
  still the open R1b_sema question, now precisely stated as "what should have
  written into physical `[0, 0x80000)` before `FUN_002A1CE0` runs". The tooling
  is ready for the answer; the answer is still not found.

## 2026-10-05 sessions 14-15 — RE4 boots, and the field's research lands

Three sessions, one story: **the infinite boot loop was a missing instruction,
not a semantic disagreement.** Everything the previous sessions argued about
was true of the code and irrelevant to the cause.

### session 14 — the compare width
`control_flow_emitter.cpp` emitted `GPR_U64(a) == GPR_U64(b)` for `beq`/`bne`.
**Corrected 2026-10-06:** the claim that o32 makes EE branches compare 32 bits
was incorrect. Sony's EE instruction manual specifies low64 comparisons.
The historical change to `GPR_U32` broke RE4's string/path scans. Restored all
scalar branch families to low64 and verified a generated native canary before
and after the correction; see [EE_BRANCH_WIDTH.md](EE_BRANCH_WIDTH.md).
The historical boot-loop cause was the missing delay slot described below.

### session 15 — the dropped delay slot, and the research
**Root cause.** `makeSyntheticDelaySlot()` fabricated `sll $zero,$zero,0` when a
branch was the last decoded instruction. A body is decoded `[start, end)`, so the
delay slot of a trailing `jr $ra` lives at `end` — outside the range. For
`FUN_002A1C88` the dropped word at `0x2A1CC4` is `0x0080102d = daddu $v0, $a0,
$zero`, the instruction that returns the **found address** in `$v0`.

**Blast radius, measured before fixing: 7,580 of 8,298 generated functions —
91.3%.** Every one of them returned a stale `$v0` across its final return.

**Proof method.** The word was read out of the ELF at vaddr `0x2A1CC4`, not
inferred from the generated C++. `_checkwords.py` dumps PT_LOAD words by vaddr;
this is how a guess was turned into a measurement.

**Fix (PATCH 15).** `decodeDelaySlot()` reads the real word out of the mapped
sections and returns the NOP only when the address is genuinely unmapped.

**Prediction made before the run, and confirmed by it.** The merge loop in
`FUN_002A1CE0` exits only when `s3 - s2 == 0xA4`. After the fix the runtime
*measured* `completed.v0 = 0x8001218C` and `0x800120E8` — the two syscall-table
slots the runtime mirrors at physical `0x1218C` and `0x120E8`, exactly `0xA4`
apart. The loop ran once and left. `dead_ends#0085`, which closes `#0077` and
`#0079`.

**What the port then did, unprompted and correctly.** RE4 executed the sequence
ps2tek documents under *BIOS EE Patches*, in order: override syscall `0x5A` to a
memcpy, copy the patch to `0x80076000`, register it for `0xFC`…`0xFF`, then
`0x12C`. No BIOS was involved and none was needed — the game patches the kernel
*in RAM*. The port and the documentation agreeing is the strongest evidence yet
that the model of the machine is right.

**The research.** Four passes, all written to `research/`: the method survey,
`ran-j/PS2Recomp` stage by stage, `recvx-decomp`, and `DQ8-Recompiled`, plus
`PS2-RECOMPILE-METHODS.md` as the synthesis. Three findings changed code:
- **DQ8's closure invariant.** "Every branch and jump lands on an address the
  dispatch table registers." Implemented as `Analysis._close_branch_targets()`.
  Promoted 237 hole targets including the live fault `0x2A2170`; 8,297 -> 8,536,
  95.72% -> 96.61%.
- **ps2autotests (ISC)** ships each R5900 test as a prebuilt `.elf` plus a
  `.expected` stdout captured on real hardware. No emulator, no BIOS, no
  toolchain. It is PCSX2's own test procedure, referenced by no CI workflow in
  that repo.
- **The oracle row is blank for exactly one method family.** Static
  recompilation replaces the parts you could check with C++ you wrote. That is
  the thesis, stated by the survey rather than assumed by us.

### session 16 — two more holes, and a third kind of evidence
- `[guest-branch:missing-target] kind=DirectJump 0x2a21e8 -> 0x2a2170`. Fixed by
  the closure pass. The guest then ran a **44-entry call trace** through the game's
  own code (`0x202908 -> ... -> 0x105fc0 -> 0x100280`) and had started building
  **GIF packets** — `record = 10000061 AE2000D0 00C098E5` is a DMA tag followed
  by a GIF tag. That is graphics initialisation, and it is code and memory.
  **CORRECTION:** this entry first said "~40 frames deep". It was a **call-trace
  depth**, not frames — the runtime prints no frame number at all, so the claim
  was unmeasured. A progress figure belongs in `eeCheckpointDue()` counts, which
  are exact guest-instruction counts; a frame count needs a definition before it
  can be quoted (R1c_next's exit criterion).
- `[guest-branch:missing-target] kind=Return source=0x2a1be0 target=0x29eca8` —
  a 204-byte hole starting with `sw $s1,-0x53E8($s3)`. `plausible_entry_op`
  rejects `sw`, so no prologue pass can ever see it. Nothing static points at it:
  no `J`, no `JAL`, no data pointer. **A third evidence source was added**
  (`_seed_from_runtime_faults`): the boot trace is the oracle for addresses only
  the guest's own registers can reveal. `FUN_0029ECA8`, 200 bytes. 8,564 total.

**Two reporting bugs found in that new code, both by measurement.**
`_close_branch_targets` reset its counters on every fixpoint iteration and so
reported 0 for work it had really done (237 promoted, reported 0). And
`_FAULT_RE` was `target=0x([0-9A-Fa-f]{8})` while the runtime prints addresses
**unpadded** — `target=0x29eca8` — so the collector silently returned an empty
dict over a trace that plainly contained three faults. Both are the same species
of error this project exists to avoid: a quiet zero instead of a failure.

### hardware
The user supplied real PS2 BIOS dumps in `bios/`. **They are not shipped.**
Sony's images get the same treatment as the game's: read locally, contribute
facts only — addresses, offsets, hashes, decoded semantics — and land in
`knowledge/ref/ps2-bios-mined.md`. Recorded in `profiles/…/profile.toml [bios]`.

### where the objective stands
RE4 boots through kernel init, both BIOS alarm patches, IRX loading and into
the game's own initialisation. Three live faults remain, each named by address
rather than by count:
1. `0x80076000` / `0x80075000` — code RE4 `memcpy`s from **ELF address
   `0x32B4B0`** into low RAM and registers as syscall handlers. Verified by
   reading the blob out of the ELF: it is code, stored in a data section, so no
   function map covers it. The fix is to carve runtime-installed code out of
   data, driven by the runtime fault — not to guess at it.
2. 23 branch targets still land in an empty address, listed by address in
   `analysis.json -> closure.unresolved_targets`.
3. No oracle. `SetupThread` is un-audited, `syscallnr.h` is not adopted, and
   `ps2autotests` is not wired. Until then every green light in this project
   means "the port does not fault", not "the port is correct".

### session 17 — the blocker was a missing `case`, not a missing implementation

The frontier after the closure and seeding passes:

```
[Syscall TODO] encoded=0x0 v1=0x7a v0=0x0 a0=0x4 a1=0x2a4160 a2=0x0 a3=0x20 pc=0x29d038
```

**543,289 calls, zero forward progress.** Not a crash — a semantic stall: the
guest polls, the host answers TODO, the guest polls again. No `missing-target`
fault remains in the map.

`v1=0x7a` is `__NR_sceSifGetReg` in ps2sdk's `ee/kernel/include/syscallnr.h`,
which also confirms the three numbers this project had been reasoning about:
`0x5A = Copy`, `0x74 = SetSyscall`, and — the useful one — **`0x5B =
GetEntryAddress`, a real kernel builtin**. So RE4 overriding `0x5B` is the same
patch-the-kernel move as overriding `0xFC`, not an abuse of a free slot the way
`0x83` is. That distinction only became checkable once the header and the
hardware were read side by side (`dead_ends#0086`).

**The finding.** `ps2_stubs::sceSifGetReg` has been implemented in
`Kernel/Stubs/SIF.cpp` the whole time, complete with its own bounded trace. The
dispatcher simply had no `case 0x7A:`, so every call fell to `default:` and the
TODO path. PATCH 17 added `case 0x79` (`sceSifSetReg`) with it, because the
audit that found one gap found its neighbour.

**And the audit is where the lesson is.** A script comparing `SIF.h` against
`Dispatcher.cpp` reported **46 stubs implemented but not dispatched**. Forty-four
of those are wrong: `sceSifBindRpc`, `sceSifLoadElf`, `sceSifRpcLoop` and the
rest are the **IOP** module's interface and have no EE syscall number at all.
The two namespaces share a header file and nothing else. Reporting 46 would have
been right once and wrong 44 times, which is how a project earns a reputation
for confident noise.

The honest statement: **EE-side SIF is `0x76`–`0x7A` and nothing else.** Five
syscalls, four of which were wired.

### a correction to a previous entry
`README.md` and this file previously said the guest reached "~40 frames deep".
It did not — it reached a **44-entry call trace**. The runtime prints no frame
number, so that figure was never measured. The only numbers quoted here are ones
a trace line contains: addresses, syscall counts, register values.

`analysis/boot-proof.md` now carries the boot-loop proof as a standalone,
checkable artifact with its raw trace lines.

### session 18 — SIF RPC, and the first gap the map cannot close

PATCH 17 wired `case 0x79`/`case 0x7A` and the stall ended: **0 `Syscall TODO`,
down from 543,289 in the same 60 seconds**. The guest then issued a real SIF
chain:

```
[syscall] id=0x79 pc=0x29d028 a0=0x80000000 a1=0x0        sceSifSetReg
[syscall] id=0x79 pc=0x29d028 a0=0x80000001 a1=0x462f98    sceSifSetReg
[syscall] id=0x77 pc=0x29cfe8 a0=0x1fafe20 a1=0x1 a2=0x462f80   sceSifSetDma
[syscall] id=0x7a pc=0x29d038 a0=0x4 a1=0x2a4160           sceSifGetReg
```

Set the chain registers, poll, then kick the DMA. That is IOP communication, not
a loop.

**The new fault, and why it is a different animal:**

```
[guest-branch:missing-target] kind=Return source=0x2a3f50 target=0x29ed74
```

`0x29ED74` **is inside a registered function** — `FUN_0029ED70` spans
`0x29ED70`–`0x29EDF8`. So the map is right and the runtime still cannot use it.
The generated dispatch switch registers `0x29ed7c, 0x29ed88, 0x29edb4, 0x29edb8,
0x29edc0` and nothing else; `0x29ED74` is the delay slot of the function's own
first `jal` (`0x29ed74: jal func_2A1BD0`).

This is the **third** member of the delay-slot family and the first one the
emitter cannot fix. `#0085` was a missing instruction, cured by decoding the real
word. Here the instruction is present and dispatched correctly; the gap is that
no code path can *enter* at that address. Every hole before this one was closed
by carving more map, and there is nothing left to carve.

**The fix is a runtime capability, not a map repair**: a return target inside a
known body must resolve to the owning function *plus an offset into its emitted
body*. PS2Recomp's `analyse` treats "resume entry points after every branch" as a
first-class requirement for exactly this reason.

`dead_ends#`0087`.

### session 19 — the blocker I called unfixable was a half-open range

Session 18 ended with a conclusion: *"This is the first blocker no map repair can
close — the fix is a runtime capability, not another map repair."* That was
wrong. It was found wrong by reading the emitted body **before** writing any
code, which is the cheapest possible way to be wrong and the most embarrassing
possible way to stay wrong.

`FUN_0029ECA8` ended like this:

```
// 0x29ed6c: 0xc0a8fb8  jal  func_2A3EE0
    ctx->pc = 0x29ED74u;
}
```

Four bytes past its own range. A `jal` at X resumes at X+8, so a function cannot
end before the resume address of a call inside it — and because the range is
half-open it must reach X+12. The entry carved at `0x29ED70` was **false**: it is
the delay slot of that same `jal`.

**No runtime change was needed, and that is checkable rather than asserted.**
`register_functions.cpp` fills dense slots for resume points inside a body —
`g_ps2RecompiledFunctionTable[3] = FUN_00100008_0x100008; // 0x10000c`. After
the map was corrected the generator emitted
`g_ps2RecompiledFunctionTable[424746] = FUN_0029EC60_0x29ec60; // 0x29eca8`,
which is the address the runtime had been refusing to dispatch.

**The pass also caught a false entry that Lodestone itself created.**
`FUN_0029EC60`'s last instruction is a `jal` at `0x29ECA0`, so its resume
address is `0x29ECA8` — meaning `FUN_0029ECA8`, promoted by our own
`_seed_from_runtime_faults` because the guest returned there, was never a
function. The bytes agree: `0x29ECA0 jal, 0x29ECA4 sw, 0x29ECA8 jal, 0x29ECB0
jal` — a chain of kernel syscall stubs sharing one dispatcher. Two discovery
passes had been fighting over an address that never was an entry.

`ps2l/analyze.py::_extend_ends_to_call_returns()`: DQ8's rule applied to the one
transfer its branch-opcode list does not cover, because a call's return address
is not a branch target and `_close_branch_targets` never sees it. **109 ends
extended, 22 false entries demoted, functions 8,566 → 8,543.**

**Two off-by-ones on the way, both caught because the counters and the map
disagreed.** Scanning `range(start, end-4, 4)` excluded the final instruction —
precisely the one under question — and reported zero extensions. Then extending
to exactly the resume address left that word *outside* the half-open range, so
`0x29ED74` stayed uncovered while the counters claimed success. **An extension
that does not change what the map can dispatch is not an extension.**

**After the rebuild:** `0 Syscall TODO`, no unimplemented syscall ids, and the
guest reached `FlushCache(0, 0x20462F40, 0x20462EC0)` with real pointers. New
fault, same shape as the last four:

```
[guest-branch:missing-target] kind=DirectJump op=EE scheduler source=0x2a3d68 target=0x2a3d68
```

`FUN_002A3D68`, 32 bytes, seeded from the trace. 8,544 functions, 96.61%.

**The lesson, stated so it survives:** four consecutive holes were closed by
carving more map, and the fifth was closed by giving back map. A growing map is
not a measure of a better one.

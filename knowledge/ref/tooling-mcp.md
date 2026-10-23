# Tooling / MCP

Distilled from four corpus files, cross-checked against the live workspace
(`ps2l/`, `core/ps2xRecomp/`, `core/ps2xRuntime/`, `docs/`, `research/`, and the
actual contents of `resources/images/`).

Sources read in full:

- `resources/05-ghidra-ghydramcp-guide.md` (64 lines)
- `resources/12-pcsx2-mcp-playbook.md` (240 lines)
- `resources/images/IMAGE_CATALOG.md` (161 lines)
- `resources/images/image-catalog.md` (148 lines)

---

## Ghidra MCP

### Tool surface

Everything is exposed under a single `mcp_ghydra_*` prefix. There are two
participants: **Ghidra itself** (a GUI app the user runs) and **GhydraMCP**
(a server plugin inside Ghidra) which bridges an MCP client to a running
Ghidra instance. The MCP client is not a headless analyser — it is a remote
control for a live, human-opened Ghidra GUI.

Connection check: if `mcp_ghydra_instances_list()` is missing or returns
nothing, *"the server is unreachable"* — either Ghidra is closed, or GhydraMCP
is missing/disabled. This is the only health probe the guide gives.

### Concrete operations named verbatim

Only seven tool names appear in the entire guide. This is the complete set:

| Tool | Purpose per the guide |
|---|---|
| `mcp_ghydra_instances_list()` | Discover running Ghidra instances |
| `mcp_ghydra_instances_use(port=8192)` | Select the active instance (port 8192 given as the example) |
| `mcp_ghydra_functions_decompile(address="0x00123456")` | Decompile a function to C-like pseudocode |
| `mcp_ghydra_xrefs_list(to_addr="0x00123456")` | Cross-references: who calls / who references this address |
| `mcp_ghydra_data_list_strings(filter="loading")` | Search strings (used against `.rodata` to locate logic) |
| `mcp_ghydra_functions_rename(address="0x00123456", new_name="Sound_Init")` | Persist a rename into Ghidra's database so later calls see it |
| `mcp_ghydra_functions_set_signature(address, "void func(int a, int b, int c, int d)")` | Override a wrong decompiler signature |

Note what is **absent**: no disassemble tool, no memory read, no patching, no
export tool, no headless/script-run tool. Seven tools, all analysis-oracle
reads plus two write-backs into Ghidra's own symbol database.

### Documented operation patterns

- **A. Discover the target.** `mcp_ghydra_instances_list()` →
  `mcp_ghydra_instances_use(port=8192)`. *"Always start by verifying the
  connection and setting the active instance."*
- **B. Understand an unknown `sub_xxx`.** decompile → look for debug strings /
  library calls → `mcp_ghydra_xrefs_list(to_addr=...)` to find callers and what
  is in `a0` at the call site.
- **C. Find known logic via strings.** `mcp_ghydra_data_list_strings(filter=...)`
  → address of the string → `mcp_ghydra_xrefs_list(to_addr="<string_address>")`
  → the function using it.
- **D. Rename to improve future analysis** (`mcp_ghydra_functions_rename`) — the
  guide frames this as durable: *"you, in future calls"*.
- **E. Get the full function map.** See below — this is the weak point.

### Setup prerequisites (all human-gated)

- Ghidra version: **strictly 11.4.2**; *"earlier versions may have issues with
  the newer EE plugin."*
- EE plugin: **ghidra-emotionengine-reloaded**
  (`github.com/chaoticgd/ghidra-emotionengine-reloaded`), which adds the custom
  `R5900` language processor. The guide is emphatic: *"Standard MIPS will **NOT**
  decompile PS2 correctly."*
- Import the game ELF, select the `MIPS R5900` language, and set
  `Options -> Language/Compiler Spec` correctly.
- Boot protocol: read the install path from `PS2_PROJECT_STATE.md` (or ask),
  `Start-Process -FilePath "C:\path\to\ghidraRun.bat"`, wait 15 s, then tell
  the user to open their ELF in the CodeBrowser. The guide's user-facing string
  is Italian: *"Ho avviato Ghidra per te. Per favore apri il tuo ELF nel
  CodeBrowser, poi dimmi di procedere"*.
- Auto-install protocol requires an explicit consent check and the **absolute
  path of the user's `mcp_config.json`**, then runs
  `python scripts/install_ghydramcp.py "<path_provided_by_user>"`. The script
  fetches a GitHub release, extracts it, and injects the server into the IDE
  config; the user then adds the emitted `.zip` via
  `File -> Install Extensions` and restarts Ghidra with CodeBrowser open.
  **This is a whole-session, human-in-the-loop ceremony.** It is not an
  automated path.

### The function-map step (§3E) — vague and manual

The guide states plainly: *"While there isn't a single MCP tool for 'export all
to CSV', you must guide the user to run the official script provided in the
PS2Recomp repository."* Location given as
`ps2xRecomp/tools/ghidra/ExportPS2Functions.py` (or `.java`), run via Ghidra's
Script Manager, producing `functions.csv` which is then fed to `ps2_analyzer`.

The guide is **explicitly vague here**: there is no documented headless or
analyzeHeadless invocation, no documented CLI export, no documented way to
capture the CSV output programmatically, and no specification of the CSV
schema. "Guide the user" and "provide you with the resulting `functions.csv`"
is the whole of the instruction.

### Decompiler artefacts the guide warns about (§4)

- `__builtin_memcpy` / `__builtin_memset` — Ghidra guesses library functions but
  applies incorrect signatures when headers aren't imported.
- `qword ptr` or `afff` types — signals 128-bit vectorisation (MMI) or floating
  point. *"Ghidra struggles to render these cleanly in C."* Directly relevant
  to a recompiler: this is where you will meet MMI/XMM translation questions.
- Argument-count mismatch — if the pseudocode shows 2 arguments but the MIPS
  pushes to `a2`/`a3`, the signature algorithm failed; fix with
  `mcp_ghydra_functions_set_signature`.

### How a headless / static-recompile workflow would drive this

Honestly: **it can't, as documented.** The guide is written entirely against a
live GUI with a human present. What *is* supported for a static pipeline is the
read-only oracle loop — connect, decompile, xrefs, strings, rename — plus one
manual export gate. There is no documented batch mode, no documented way to
run `ExportPS2Functions` unattended, and no documented way to get results back
into an automated build.

The one genuinely automatable part is `mcp_ghydra_functions_rename`: because
renames persist into Ghidra's database, a sequence of rename calls is a durable
way to accumulate curated symbol names across sessions. Everything else is a
request/response against whatever the user currently has open.

---

## PCSX2 MCP

### Connection protocol (§1)

Requires **a custom PCSX2 build with DebugServer compiled in, port 21512**. A
stock PCSX2 will not work.

1. `mcp_pcsx2_pcsx2_connect()` → must show *"DebugServer connected"*. If it
   fails: *"PCSX2 not running or wrong build. Stop."*
2. `mcp_pcsx2_pcsx2_game_info()` → *"Verify the SAME game is loaded as the recomp
   target."* Wrong game ⇒ stop.
3. `mcp_pcsx2_pcsx2_status()` → confirm running / paused.

The guide says to connect at session start if PCSX2 is available and record the
result in `PS2_PROJECT_STATE.md → PCSX2 MCP Status`.

**Naming inconsistency inside the source itself:** the three lifecycle tools are
spelled `mcp_pcsx2_pcsx2_connect()` / `_game_info()` / `_status()` (double
`pcsx2`), while every other tool in the catalogue drops the `mcp_` prefix
(`pcsx2_pause`, `pcsx2_read_registers`, …), and the §3 flow diagram then uses a
third spelling, `pcsx2_connect()`. Three spellings across one document. Pin one
and verify against the actual server before scripting.

### Full tool catalogue (§2), verbatim

**Execution control**

| Tool | Notes from the guide |
|---|---|
| `pcsx2_pause()` | Halt emulation, return current PC. Values are meaningless while running |
| `pcsx2_continue()` | Resume until next breakpoint or halt |
| `pcsx2_step()` | Execute **one** MIPS instruction |
| `pcsx2_step_over()` | Step over JAL/JALR |

**Registers**

| Tool | Notes |
|---|---|
| `pcsx2_read_registers()` | Read **ALL 128-bit EE registers** — *"THE primary diagnostic tool"* |
| `pcsx2_read_registers(category=0)` | GPR only (`v0`, `a0-a3`, `sp`, `ra`) |
| `pcsx2_read_registers(category=2)` | FPR only |
| `pcsx2_write_register(index, value)` | Modify a register. *"Use with caution."* |
| `pcsx2_evaluate(expression)` | Evaluate a MIPS expression, e.g. `"v0 + 0x100"`, `"gp + 0x20"`, dereference pointers |

**Memory**

| Tool | Notes |
|---|---|
| `pcsx2_read_memory(addr)` | Hex dump of PS2 RAM |
| `pcsx2_read_memory(addr, format="u32_array")` | As 32-bit words |
| `pcsx2_read_memory(addr, format="ascii")` | As text |
| `pcsx2_write_memory(addr, data)` | **DANGEROUS.** Testing hypotheses only |
| `pcsx2_read_string(addr)` | Null-terminated string |
| `pcsx2_find_pattern(pattern)` | Hex search, `??` wildcards |
| `pcsx2_memory_diff(addr, name)` | Call once = snapshot; call again with same name = diff |

**Breakpoints & watchpoints**

`pcsx2_set_breakpoint(addr)` · `pcsx2_set_breakpoint(addr, condition="v0 == 0x42")`
· `pcsx2_set_breakpoint(addr, temporary=True)` · `pcsx2_remove_breakpoint(addr)` ·
`pcsx2_list_breakpoints()` · `pcsx2_clear_all_breakpoints()` ·
`pcsx2_set_watchpoint(addr, type="write")` · `pcsx2_set_watchpoint(addr, type="onchange")` ·
`pcsx2_remove_watchpoint(addr)` · `pcsx2_list_watchpoints()`

**Disassembly**

- `pcsx2_disassemble(addr)` — *"Native MIPS disasm from PCSX2. Better than Ghidra
  for runtime — shows actual loaded code, not just ELF."*
- `pcsx2_disassemble(addr, count=50)`

**State management** — `pcsx2_save_state(slot)` (slots 0–9), `pcsx2_load_state(slot)`

**System info** — `pcsx2_get_threads()` (EE/IOP threads), `pcsx2_get_modules()` (IOP modules)

### What this means for our oracle use-case — the honest answer

**Capturing frames / screenshots: not present. At all.** There is no screenshot
tool, no framebuffer read, no frame capture, no video dump, no display-surface
read anywhere in §2's catalogue. The catalogue is entirely execution control,
registers, memory, breakpoints, watchpoints, disassembly, state slots, and
module/thread enumeration. If our DiffView oracle needs *pixels* from PCSX2,
this playbook contributes nothing to producing them. (Our `gs_dump_replay` route
via PCSX2 Pine IPC is a different, separately-sourced mechanism, not this one.)

**Deterministic runs: partial and unspecified.** `pcsx2_save_state(slot)` /
`pcsx2_load_state(slot)` with slots 0–9 do give checkpoint-and-replay. But the
guide **never states any determinism guarantee**, never mentions single-frame
advance, never mentions frame or tick counters, never mentions headless mode,
and never explains how to align a PCSX2 moment with a recompiler moment. The
synchronisation step in the A/B protocol is written as a human action: *"Advance
game to the same point as the crash."* That is a manual, un-specified alignment
— exactly the hard part an automated differ needs solved. Treat "deterministic
runs" as an inference, not a documented capability.

**Reading guest memory from outside the emulator: yes, and this is the strong
part.** `pcsx2_read_memory` (hex / `u32_array` / `ascii`), `pcsx2_read_string`,
`pcsx2_find_pattern` with `??` wildcards, and `pcsx2_memory_diff` for
snapshot-then-compare. Combined with `pcsx2_read_registers()` this is a complete
side-A state extractor at any breakpoint.

The limitation to design around: **memory can only be read after the guest has
already executed to that point.** There is no documented way to read RAM
without running, no bulk whole-RAM export to a file, and no documented streaming
or batch export across many breakpoints. `pcsx2_memory_diff(addr, name)` is
per-address and stateful across calls (which makes it a poor fit for a
concurrent, automated collector).

`pcsx2_disassemble` is called out as *"better than Ghidra for runtime — shows
actual loaded code, not just ELF."* `research/ADOPTED.md` §3.2 agrees and
concludes this is *"the genuinely independent oracle"* for our decoder,
reachable over the DebugServer JSON/TCP transport. Note our own corpus spells it
`ps2x_disassemble` there, not `pcsx2_disassemble` — see Contradictions.

### A/B comparison workflow (§3), and where it ends

The stated rationale: *"Instead of guessing what the recompiled code should do,
you **observe the real PS2 doing it**, then compare."*

- **Side A (PCSX2):** connect → advance game to the same point as the crash →
  `pcsx2_set_breakpoint(target_address)` → `pcsx2_continue()` →
  `pcsx2_read_registers()` → `pcsx2_read_memory(relevant_addrs)` →
  `pcsx2_step()` × N.
- **Side B (recompiled):** *"Add trace logging in the C++ override/runtime at
  the same function address"* → build → run with timeout → read log → extract
  register/memory state.
- **Diff:** registers match ⇒ entry is correct; first register divergence ⇒
  *"THAT is the bug"*; memory differs ⇒ initialisation problem; wrong `v0` ⇒
  logic error in the body. *"First divergence = root cause location."*

The fix taxonomy named is **TOML / Runtime C++ / Game Override / Recompiler**.

Use it for: crash at a known address with unknown cause; function returns a wrong
value but compiles fine; wrong DMA/GS output when the code "looks right"; hard-to-
reproduce visual glitches; anything stdout doesn't explain.

Do **not** use it for: build errors, missing stubs, or TOML configuration issues —
*"no runtime state to compare"*.

Note this is a manual loop with a human building side B each time. There is no
automation, no shared-anchor protocol, and no machine-readable exchange format
in the guide.

### Recipes (§4)

Five worked recipes, all manual: breakpoint just before `JR RA` and read `v0`
for the return value; `pcsx2_memory_diff` before/after an init call; a
`write` watchpoint on a DMA CHCR (example address `0x1000A000`) then
`pcsx2_disassemble(PC)`; a conditional breakpoint (`condition="a0 == 0x1234"`);
and a save-state → write → continue → load-state rollback experiment. Plus a
`set_watchpoint("0x203000", type="write", condition="[0x203000] == 0")` pattern
to find who zeroes a value.

### Safety rules (§5)

1. **ALWAYS `pcsx2_pause()` before `pcsx2_read_registers()`** — values are
   meaningless while running.
2. **ALWAYS `pcsx2_save_state()` before `pcsx2_write_memory()`** — writes can
   hard-crash emulation with no recovery except reload.
3. **NEVER leave breakpoints set and forget them** — they slow emulation; clear
   at session end.
4. **NEVER `pcsx2_write_register()` without explicit user approval.**
5. **ALWAYS verify the game is at the right point** before setting breakpoints
   (e.g. overlay not loaded yet).
6. **Use `temporary=True` breakpoints where possible.**
7. **Document what you learn** into `PS2_PROJECT_STATE.md → Learned Patterns`.

---

## Image corpus

Two catalogues describe the same directory, `resources/images/`. On disk there
are **80 PNGs**, which matches `IMAGE_CATALOG.md`'s stated total exactly, and
whose per-source breakdown also matches (ps2_arch_analysis 47, ps2_overview 7,
ps2_normalmapping 16, ee_programming 5, ee_chip_article 3, vu_architecture 2).

### What `image-catalog.md` is

The **raw extraction manifest**: *"Total images extracted: 104"*, one row per
image with filename, page, **pixel dimensions**, and a **"Caption Hint"**. The
caption hints are scraped fragments of surrounding page text and are frequently
mid-sentence garbage rather than captions — e.g. for
`ee_chip_article_p006_02.png`: *"sistors on 240 mm2 of 0.25-micron silicon (as
Figure 6 shows)"*, and for `vu_architecture_p007_02.png`: *"Figure 8. Vector
unit micrograph."* Most rows simply read *"(no caption found on page)"*. It
carries no description of content beyond dimensions and these fragments.

### What `IMAGE_CATALOG.md` is

The **curated, classified version**: 80 kept / 24 deleted, with ★ ratings
(★★★ critical architecture, ★★ useful context, ★ demo/illustration) and
human-written one-line descriptions. It is the only file that says what the
images actually *depict*.

### What the images depict

**★★★ Critical architecture (9).** This is the payload.
`ps2_arch_analysis_p032_28.png` — *"COMPLETE PS2 System Block Diagram — ALL
subsystems: EE, GS, IOP, SPU2, DVD, I/O. Every bus width and clock speed
labeled. **THE single most important reference image.**"* Also
`ps2_arch_analysis_p006_07.png` (EE full block diagram: MIPS R5900 core, FPU,
VPU0/VPU1, GIF, Memory Interface, DMA, SIF, IPU with bus widths),
`p010_08` (memory interface: 32 MB RDRAM dual-channel 16-bit 400 MHz, scratchpad,
cache hierarchy), `p014_09` (VPU0/VPU1 architecture, micro/macro modes),
`p017_11` (GS pipeline: rasterisation, Z-buffer, alpha, DITHER),
`p017_12` (GS texture + CLUT buffers, VRAM layout). And from the EE Overview
Manual: `ps2_overview_p010_05.png` (VU0: 32 FP + 16 Int regs, 4 FMACs, VIF0
interface), `p011_06.png` (VU1: same register layout + GIF, PATH 1/2/3),
`p014_07.png` (EE full pipeline: CPU Core → VU0 → VU1 → GIF → GS).

**★★ Useful context (~25 rows).** Hardware photographs (console, motherboard,
EE die/GS chip close-ups, front/rear panels, Network Adapter, DualShock 2,
boot screen, Memory Card browser UI), **SPU2 audio waveforms**
(`ps2_arch_analysis_p031_26.png` L/R channel visualisation; `p031_27.png`
reverb-vs-dry comparison), and two annotated EE die micrographs from
`vu_architecture`.

**★ Demo / illustration (46).** Game screenshots (incl. Kingdom Hearts — Sora
and Dragon Quest VIII — Hero T-pose models), EE programming 3D demos (tori and
cubes), **all 16 `ps2_normalmapping` images** as 3D head renders demonstrating
per-pixel lighting / normal mapping on PS2, three EE-chip-article renders, and
one SCE logo.

### Discrepancies between the two catalogues

1. **Totals differ by design: 104 vs 80.** `image-catalog.md` is the
   pre-audit extraction (104). `IMAGE_CATALOG.md` records *"24 irrelevant
   deleted"* and enumerates them: 12 × `tx79_architecture_*` (Toshiba
   packaging, safety warnings, marketing), 8 × `ps2_optimisations_*` (Australia
   map, devkit photo, scanline patterns), 3 × `ps2_overview_*` (redundant
   console photos, SCE logos — these are `p001_01`, `p001_02`, `p018_10`),
   1 × `ee_programming_p009_04.png` (*"Stiquito for Beginners"* book cover).
   104 − 24 = 80, and the deletions reconcile exactly against the raw manifest.
   **This is an explained difference, not a conflict.**

2. **`IMAGE_CATALOG.md`'s summary table contradicts its own rows.** The tier
   totals row reads `9 / 22 / 49` (= 80), but the section headers read
   `9 / 18 / 46`, and the actual per-file rows in the ★★ section list **25**
   images. The ★ section's 46 rows are internally consistent with its header.
   So: rows sum to exactly 80 and match disk; the summary table's ★★ (22) and
   ★ (49) columns are wrong, and the ★★ header (18) counts only the
   hardware-photo subsection. **Trust the per-file rows; distrust the tallies.**

3. **Content disagreement on `ps2_arch_analysis_p005_05.png` / `p005_06.png`.**
   `IMAGE_CATALOG.md` files both as ★★ *"Hardware detail"*. But
   `image-catalog.md` gives `p005_05` and `p005_06` the caption hint
   *"Diagram"*, not a photo — and `p005_06` is **1783x1008, the exact same
   dimensions as `p032_28`**, which the curated catalogue calls the complete
   system block diagram. Two identically-sized full-page figures suggests
   `p005_06` may be a duplicate extraction of the same figure, mislabelled as a
   hardware photo.

4. **Possible misclassification in the normal-mapping set.**
   `IMAGE_CATALOG.md` describes all 16 `ps2_normalmapping` images as *"3D head
   renders"* and gives them 0 critical / 0 useful value. But `image-catalog.md`'s
   caption hints for `p013_04`–`p013_07` are *"Figure 4: (a) The sphere map
   normalization table/texture…"* and for `p016_08` is *"Figure 5: The normal
   map."* Those are **textures/data tables, not renders**, and a sphere-map
   normalisation table is arguably the most algorithmically interesting asset in
   the set for anyone implementing PS2 per-pixel lighting. The ★, 0-useful
   rating likely hides real reference material.

5. **The two files differ only by filename case**
   (`IMAGE_CATALOG.md` vs `image-catalog.md`) in the same directory. They are
   readable as distinct files in this environment, but that is a hazard on a
   case-insensitive filesystem and for any tooling that globs the directory —
   one of the two will silently shadow the other depending on the backend.

---

## Contradictions

Listed only; no other file was edited. Each is grounded in a check against the
live workspace.

**Against the Ghidra playbook**

1. **`ps2_analyzer` does not exist here.** §3E says the Ghidra CSV "is used by
   `ps2_analyzer`". There is no such tool in this workspace; our tool is
   `ps2l/analyze.py`, registered as `analyze` in `ps2l/cli.py`.
2. **The mandatory Ghidra step is precisely what we made optional.**
   `ps2l/analyze.py`'s own docstring says it *"Writes a Ghidra-CSV-compatible
   function map (Name,Start,End,Size) so ExportPS2Functions.java can be skipped
   entirely."* The playbook treats Ghidra+CSV as the only route to a function map.
3. **Ghidra-free is our documented posture.** `docs/STATE.md` records
   *"ps2l/analyze.py — Ghidra-free ELF analysis"*; `docs/01-BUILD.md` §pipeline
   is *"our analysis (Ghidra-free), produces a compatible CSV"*. So the
   playbook's opening premise — that Ghidra must be installed before any
   analysis — does not describe our pipeline. (`docs/STATE.md` still notes *"a
   Ghidra export remains the authority"*, and `README.md` warns our coverage
   figure is *"a heuristic measured against our own map"*, so Ghidra is demoted
   to an unclaimed validator rather than removed.)
4. **`ExportPS2Functions.py` (or `.java`)** — only the `.java` exists, at
   `core/ps2xRecomp/tools/ghidra/ExportPS2Functions.java`. The guide's
   "`.py` or `.java`" hedge is half wrong.
5. **Ghidra 11.4.2 + `ghidra-emotionengine-reloaded` are prerequisites we never
   take.** We ship our own R5900 decoder at
   `core/ps2xRecomp/src/lib/r5900_decoder.cpp`. The guide's claim that standard
   MIPS cannot decompile PS2 correctly is real but not load-bearing for us,
   because we do not depend on Ghidra decompilation for correctness.
6. **Headless is unsupported by the source.** Every documented flow needs a
   live Ghidra GUI, a human, and a manual Script Manager run. A headless static
   pipeline can use the read-only oracle calls and nothing else.

**Against the PCSX2 playbook / our oracle goal**

7. **The single most important gap: no frame or screenshot capture exists in
   this corpus.** The playbook has zero graphical tools. Our DiffView oracle
   (`ps2l/diffview.py`, self-tested 7/7 per `README.md`) needs reference
   *pixels*, and `docs/STATE.md` is explicit that *"no PCSX2 frames have been
   captured, so the oracle exits 1 and says so"* — the reference corpus is the
   acknowledged largest remaining gap. **The playbook cannot fill it.**
8. **`lodestone verify` is specified but not built.** `docs/01-BUILD.md` §6
   lists it among *"the four [pieces of] code we must write"* — *"external PCSX2
   process, shared anchors, non-zero exit on divergence. GPL boundary:
   subprocess, never link."* It is not registered in `ps2l/cli.py`, which has
   `analyze`, `triage`, `diffview`, `build`, `profile`, `agent`, `fingerprint`,
   `check`. Notably there is no `verify` and no `ghidra` entry.
   The playbook's A/B protocol has no automated implementation in this repo, and
   the playbook itself specifies no shared-anchor protocol or machine-readable
   exchange format.
9. **Determinism and run-alignment are unaddressed.** `save_state`/`load_state`
   give checkpointing, but nothing documents determinism guarantees, frame
   advance, tick counters, headless mode, or how to align a PCSX2 moment with a
   recompiler moment — the guide's step is *"Advance game to the same point as
   the crash"*, a human action. Automatic diffing needs this solved and the
   corpus does not solve it.
10. **Tool-name drift inside our own corpus.** `research/ADOPTED.md` §3.2 and
    `research/ECOSYSTEM-REPORT.md` both write `ps2x_disassemble`; the playbook
    writes `pcsx2_disassemble`. Same tool, two names — pick one before scripting.
11. **Naming inconsistency within the playbook itself**, as described above:
    `mcp_pcsx2_pcsx2_connect()` vs `pcsx2_connect()` for one operation.
12. **The upstream MCP has tools the playbook omits.** `research/ADOPTED.md`
    records `pcsx2recomp_lookup_function` / `pcsx2recomp_list_overrides` as
    PCSX2-MCP features — and refutes them: they *"scan `ps2xRuntime/src/lib/overrides/` — that directory does not exist in upstream — and grep for a `RECOMP_FUNC` macro that appears
    nowhere."* Our overrides live in `core/ps2xRuntime/include/game_overrides.h`
    and `src/lib/game_overrides.cpp`. Any PCSX2-MCP call that inspects the
    overrides tree will target a path that does not exist here.
13. **GPL posture agrees in outcome, differs in assumption.** The playbook
    assumes a *patched PCSX2 fork* with DebugServer compiled in, driven live via
    an MCP bridge (`hkmodd/PCSX2-MCP`, GPL-3.0). Our standing decision is
    stricter: external process only, never link (`README.md`: *"PCSX2 is GPL ⇒
    diff against, never link"*; `IDEA.md` §licensing resolves it to
    subprocess/IPC). Same boundary, but the playbook quietly assumes a dependency
    we have not taken — *a custom PCSX2 build*.
14. **The playbook's write targets don't exist in this repo.** It instructs
    writing to `PS2_PROJECT_STATE.md → PCSX2 MCP Status` and
    `→ Learned Patterns`. In this workspace `PS2_PROJECT_STATE.md` exists only as
    a snapshot under `.research/dc2/` and `.research/dc2md/`, and the file it
    points to for *"Concrete paths, static export, harness wiring, PCSX2 A/B"*
    (`skill/resources/appendix-dc2-project.md`) exists only inside
    `.research/dc2md/`, not at the workspace root. Following the playbook
    literally would write to a non-live path.

**Against the image catalogues**

15. **`IMAGE_CATALOG.md`'s tier tallies are internally inconsistent** (rows sum
    to 80 and match disk; the summary table says 22/49, the headers say 18/46).
    Any automation that reads the summary table gets wrong numbers.
16. **The two catalogues disagree on the content of `ps2_arch_analysis_p005_05/06`**
    (hardware photo vs "Diagram"), and `p005_06` shares the 1783x1008
    dimensions of the complete-system diagram `p032_28` — likely a duplicate
    extraction.
17. **The 16 `ps2_normalmapping` images are uniformly rated "3D head renders,
    0 useful", but the raw manifest's caption hints say several are textures**
    (sphere-map normalisation table ×4, the normal map itself). Likely
    mis-rated; potentially real algorithm reference.
18. **The two catalogue files differ only by filename case** in one directory —
    fragile on case-insensitive filesystems and for glob-based tooling.
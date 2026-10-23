# Pipeline / Porting

*Distilled from `resources/03-ps2recomp-pipeline.md`, `resources/06-game-porting-playbook.md`,
`resources/07-ps2-code-patterns.md`, `resources/db-overlay-patterns.md`. Nothing below comes from
outside those four files. Where they are silent, the gap is marked **GAP** rather than filled.*

---

## The pipeline

The sources describe a **3-stage pipeline: Analyzer → Recompiler → Runtime** (03 §1), plus a
**build stage** that 03 §4 treats as a critical fourth practical step.

### Stage 1 — `ps2_analyzer` (ELF → `game.toml`)
Takes a PS2 ELF (and optional Ghidra CSV) and emits a `game.toml`. Goal: identify boundaries for
every function so the recompiler has something to translate.

Three operation modes (03 §1):
1. **With symbols (DWARF)** — "Ideal. Perfect boundaries and function names."
2. **Stripped (no symbols)** — native `jal` heuristic scanner. "Fast, but often misses boundaries due
   to compiler optimizations or anti-reversing."
3. **Ghidra feed** — for complex/protected games, export the function map with
   `ps2xRecomp/tools/ghidra/ExportPS2Functions.py` and pass it via `[general] ghidra_output`.

CLI (03 §1): `./build/Debug/ps2_analyzer.exe "path/to/game.elf" "base_config.toml"`

### Stage 2 — `ps2_recomp` (ELF + `game.toml` → C++)
CLI (03 §3): `./build/Debug/ps2recomp.exe config.toml`

- Emits thousands of `out_xxxxx.cpp` files (29,000+ for large games).
- Each MIPS function becomes a C++ function taking `R5900Context& ctx`. Verbatim example:
  ```cpp
  // original: add $v0, $a0, $a1
  void sub_100050(R5900Context& ctx) {
      ctx.gpr[2].words[0] = ctx.gpr[4].words[0] + ctx.gpr[5].words[0];
  }
  ```
- **Stubs** = functions NOT translated; a wrapper routes to a known runtime handler.
  Flat array form: `"sceCdRead@0x00115000"` binds address `0x00115000` to handler `sceCdRead`;
  `"ret1@0x00115500"` is "triage binding: return 1 (success)".
- **Skips** = functions actively ignored, generating placeholders like
  `ps2_stubs::TODO_NAMED("FunctionName")` returning an error-like value (e.g. `"sub_00100008"`
  to skip the crt0 bootstrapper).
- **Patches** replace MIPS instructions *before* recompilation — "Easiest way to break an infinite
  spinlock waiting on unsupported hardware", e.g.
  `{ address = "0x100004", value = "0x00000000" }` (replace with `nop`).
- **Unhandled opcode problem** (03 §3): an instruction the recompiler cannot translate is emitted as
  a comment `// Unhandled opcode at 0x123456: blah`. Hitting that path "will likely crash or behave
  incorrectly." 03 gives an explicit agent action: scan the generated C++ for `// Unhandled opcode`
  and log every occurrence in `PS2_PROJECT_STATE.md` under **Unhandled Opcodes** *before* building.

`[general]` keys (03 §2): `input` (mandatory), `output` (mandatory), `runtime_header`,
`code_base` (address where code is mapped), `single_file_output` (`true` "to speed up compilation
for testing"). Example in the source uses `code_base = 0x00100000`.

### Stage 3 — Runtime (`ps2xRuntime`)
Runs the recompiled code, resolves addresses to handlers, and emulates the hardware (DMA, GS, CD).

**The mental model that governs this whole stage (06, CRITICAL):**
> "Runtime dispatch is purely address-based (`0xADDR` → function pointer), NOT name-based
> (`sub_xxx`). Renaming generated C++ functions does not fix execution."

### Stage 4 — Build (03 §4, "CRITICAL")
| Toolchain | Generator | Approx. full build | Status |
|---|---|---|---|
| Clang-CL + Ninja | `-G Ninja` + clang-cl | **~1 hour** | ⚡ MANDATORY, already in `build64/` |
| MSVC + Ninja | `-G Ninja` | ~3–5 hours | ⚠️ temporarily acceptable |
| MSVC + VS Solution | `-G "Visual Studio 17 2022"` | ~20–25 hours | ❌ FORBIDDEN |

Two mandatory `ps2xRuntime/CMakeLists.txt` surgeries (03 §4, both flagged **HUMAN-IN-THE-LOOP** —
the agent must explain and get permission first):
- **A.** Below `add_compile_definitions(USE_SSE41=ON)` add `add_compile_options(-msse4.1)`.
  Reason: `add_compile_definitions` only defines a macro; MSVC gets SSE4.1 implicitly on x64,
  Clang needs the explicit flag or errors on intrinsics like `_mm_extract_epi32`.
- **B.** DELETE from the `ps2EntryRunner` target: `UNITY_BUILD ON UNITY_BUILD_BATCH_SIZE 16` and
  `if(MSVC) target_compile_options(ps2EntryRunner PRIVATE /FS /Z7 /MP /bigobj)`. Reason: Unity Build
  merges translation units, defeating Ninja's parallelism over 29,000 files; the flags are MSVC-only.

Rules: never delete or reconfigure a build dir without explicit user OK (only suggest). With Ninja
(single-config), build type is set at **configure** time via `-DCMAKE_BUILD_TYPE=Release`, not at
build time via `--config`.

### Which stage each failure belongs to

| Failure | Stage | Canonical signal | Source |
|---|---|---|---|
| "Function not found for address 0xXXXXXX" | **1 (Analyzer)** | analyzer missed a valid execution path | 06 Blocker 1 |
| `// Unhandled opcode at 0x...` | **2 (Recompiler)** | instruction has no translation | 03 §3 |
| "Unimplemented PS2 stub called: sub_XXXXXX" | **3 (Runtime)** | TOML declared a stub, no C++ handler written | 06 Blocker 2 |
| Crash at an address **outside** the main ELF's `.text` | **1/2 (missing binary)** or **3 (overlay not loaded)** | overlay code never recompiled | db-overlay §2 |
| `[Syscall TODO: 0x?? executing]` | **3 (Runtime)** | BIOS-provided syscall not implemented | 06 Blocker 4 |
| Freeze, CPU core 100 %, log stops | **3 (Runtime)** | spinlock on an unemulated hardware event | 06 Blocker 3 |
| Function renames "don't fix" anything | **3 (Runtime)** | dispatch is address-based, not name-based | 06 |
| Same crash address 3× in a row | **process failure** | "you are using flawed logic. STOP." | 06 Rule of 3 |

---

## Multi-binary and overlay rules

### Three distinct categories (db-overlay §1, §4)

| Category | What it is | Where it runs | Recompiled? |
|---|---|---|---|
| **Boot ELF** | Small launcher; "sets up hardware, loads COREC" | EE | Yes — own TOML |
| **Secondary ELF** | Completely separate executable loaded via `LoadExecPS2()` (e.g. boot ELF `SLUS_xxx.xx` vs. core engine `COREC.BIN`) | EE | Yes — own TOML |
| **IOP module (`.irx`)** | Loaded to the **I/O processor** via `SifLoadModule()` — audio/pad/CD drivers | IOP | **Never.** "The functionality these modules provide (pad input, CD reads, audio) must be reimplemented in the `ps2xRuntime` C++ layer" |
| **Code overlay** | Portions of the game's *own* code loaded into fixed memory regions on demand (e.g. level-specific logic "loaded over audio code when changing levels") | EE | **GAP** — the sources do not say whether this needs its own TOML. They only cover separate *binaries*; an overlay described as the game's own code is not one. |

### Multi-TOML rule
> "Each binary needs its own TOML and its own `ps2_analyzer` + `ps2_recomp` run." (db-overlay §3)

03 §1 words the same rule for a launcher-ELF + massive `.BIN` core: do **not** put everything in one
`game.toml`; run `ps2_analyzer` and `ps2_recomp` **twice**, producing two distinct sets of C++ files
"that must be compiled together into the runtime."

db-overlay §3 pipeline, verbatim:
```bash
# 1. Analyze both
ps2_analyzer SLUS_123.45 -o slus_12345.toml
ps2_analyzer COREC.BIN -o corec.toml -base_address 0x00200000

# 2. Configure both TOMLs (stubs, patches, skips)

# 3. Recompile both
ps2_recomp slus_12345.toml -o output/boot/
ps2_recomp corec.toml -o output/core/

# 4. Copy ALL generated .cpp files to runner/
```

### How overlays are detected (db-overlay §2)

| Evidence | Meaning |
|---|---|
| Crash at an address **outside** the main ELF's `.text` range | Jumped to overlay code never recompiled |
| `Function not found for address 0xXXXXXX` outside the main ELF | Missing overlay binary in the pipeline |
| Strings `COREC.BIN`, `BATTLE.OVL`, `MENU.BIN` in the ISO | Likely secondary code binaries |
| `LoadExecPS2()` / `ExecPS2()` calls (by Ghidra name or pattern) | Game explicitly loads a new ELF |
| `sceCdRead` targeting a range that **overlaps existing code** | Code overlay loaded into a reusable region |
| **Multiple `.text` sections, or a suspiciously small `.text`** | "The ELF is a boot shim that loads the real code dynamically" |

Confirm via Ghidra (db-overlay §2): find the main ELF's `.text` range
(`mcp_ghydra_segments_list()`); search for xrefs to addresses outside it (example given: game calls
`0x00500000` but `.text` ends at `0x003FFFFF`); search strings for `.elf`, `.bin`, `EXEC` in
`mcp_ghydra_data_list_strings()`.

### How base addresses are chosen
> "The `-base_address` flag tells the recompiler where the binary is loaded in memory. For the main
> ELF this is usually `0x00100000`. For overlays, you must determine the load address from either:"
> - the `LoadExecPS2()` call arguments,
> - the memory address where `sceCdRead` deposits the overlay, or
> - the ELF header of the overlay binary itself.

(db-overlay's worked example uses `0x00100000` for `SLUS_123.45` and `0x00200000` for `COREC.BIN`.
03's `[general]` equivalent key is `code_base`.)

### The address-space-conflict rule (db-overlay §3, verbatim in substance)
> If two binaries share the same address range (because overlays are loaded INTO the same memory):
> - They **CANNOT** both be active at the same time.
> - The runtime must track which overlay is currently loaded.
> - Register functions from the currently-active overlay only.
> - "This is advanced and may require runtime-level overlay management (**not yet standardized in
>   PS2Recomp**)."

A related, weaker rule from 06's final checklist: "there is no obvious same-PC infinite loop caused
by **direct raw handler binding in Game Overrides**" — i.e. binding an address straight to a handler
can produce a same-PC loop.

State-file integration (db-overlay §5): `PS2_PROJECT_STATE.md` should carry a `## Binaries` table
with columns `Binary | Type | Base Address | TOML | Status` (e.g. `MODULE/SOUND.IRX | IOP Module |
N/A (IOP) | N/A | Stubbed`).

---

## Boot-sequence patterns

> **GAP — read this first.** The four sources contain **no numbered syscall sequence at all**. A
> grep for syscall numbers / `InitMainThread` / `InitHeap` / `CreateSema` / `SetSyscall` across all
> four files returns **zero matches**. Nothing below is a syscall number; it is the concrete,
> name-level and address-level boot material the sources *do* give, kept verbatim. Any concrete
> numbered boot sequence we have (e.g. RE4's) came from elsewhere — most plausibly
> `resources/db-syscalls.md` or `resources/04-runtime-syscalls-stubs.md`, which were not in scope.
> Do **not** cite this section as a source for syscall numbers.

### 06 §"The Path to the Main Menu" — the five milestones (the closest thing to a boot sequence)
1. **Boot and Memory Init** — "Early code initializes stacks, zeros BSS, sets up DMA channels."
2. **Library Loading (`SifLoadModule`)** — "The EE loads drivers into the IOP. You will see calls to
   `sub_xxx` passing string arguments like `rom0:SIO2MAN` or `cdrom0:\MODULE\CDVDMAN.IRX`."
   *Action:* identify the `SifLoadModule` function and stub it perfectly. **It must return success
   (`1`).**
3. **CDVD Reads (`sceCdRead`, `sceCdSync`)** — "The game tries to read files from the disc."
   *Action:* emulate the CD-ROM reader in C++ reading from the PC filesystem.
4. **GS Initialization** — "The game kicks off GIF tags and configures the GS for drawing."
   *Action:* runtime should handle standard GS routing, but **verify no custom setup loops are
   hanging.**
5. **The First Frame** — if it doesn't crash after setting up display memory and reading an asset
   file, expect a splash or intro video.

### The three-call CD read sequence (07 §4, verbatim ordering)
`[08] If the game hangs after calling a sub_xxx with a filename, it's stuck in sceCdSync.`
1. `sceCdSearchFile(name, &toc_entry)` → gets sector start
2. `sceCdRead(lsn, sectors, ptr, mode)` → kicks off background read
3. `sceCdSync(0)` → waits for read to finish

Filename literals that identify it: `\\SLUS_xxx.xx;1`, `DATA.BND;1`. "You will recognize CD logic
because it often involves the `cdvdman` RPC commands."

### Module-loading sequence (07 §3)
Strings passed into a function inside a loop ⇒ that function is `SifLoadModule` or
`SifLoadModuleBuffer`. Literals named: `"rom0:SIO2MAN"` (Serial I/O Manager — gamepads/memcards),
`"rom0:MCMAN"` (Memory Card Manager), `"cdrom0:\MODULE\IOPRP.IRX"`. db-overlay §4 adds
`SifLoadModule("cdrom0:\\MODULE\\CDVDMAN.IRX")` → stub to return success, i.e. **module ID > 0**.
Strategy: "You MUST stub this function to return success (`1` or `>0`). Do NOT let the native game
logic try to execute IOP modules in the recompiler; it will fail."

### Threading / semaphore literals (07 §5)
- Function taking strings like `"Main Thread"` or `"Load Thread"` plus a priority number
  (**"usually around `64`"**) ⇒ `CreateThread`.
- Structure initialized with initial value `1` and max `1` ⇒ `CreateSema` (Semaphore).
- `ps2xRuntime` hooks `SYSCALL` for `WaitSema` and `SignalSema`. Wrapper functions around these
  syscalls are usually translatable as-is, so stubbing them is not necessarily required.

### Hardware-register boot/late-boot constants (07 §1, §2)
V-SYNC wait loop, verbatim:
```cpp
while ( (*(uint32_t*)0x12001000 & 8) == 0) {}
*(uint32_t*)0x12001000 = 8;   // Clear the flag
```
GS registers: `0x12000000` GS_PMODE, `0x12000080` GS_DISPFB1, `0x12001000` GS_CSR
("extremely common in loops").

DMA wait: spin until DMA CHCR bit 8 (START, `0x100`) clears. Channels:
`0x1000A000` ch0 VIF0 → VU0 · `0x1000A010` ch1 VIF1 → VU1 (main graphics path) ·
`0x1000A020` ch2 GIF → GS (textures usually) · `0x1000A030` ch3 from IPU · `0x1000A040` ch4 to IPU ·
`0x1000A050` ch5 SIF0 (IOP→EE) · `0x1000A060` ch6 SIF1 (EE→IOP) · `0x1000A070` ch7 SIF2 ·
`0x1000A080` ch8 from SPR · `0x1000A090` ch9 to SPR.

Address-space shortcut (06 Blocker 3): `0x10000000` range = IOP/CD; `0x12000000` = GS.

---

## Diagnosis playbook — "the game boots then stalls"

The iteration loop (06): run `ps2xRuntime` → see where it crashes/hangs → diagnose the blocker
(missing function / unimplemented stub / syscall / hang) → update `game.toml` or C++ overrides →
rebuild and repeat.

**Rule of 3 (circuit breaker), verbatim:** "If you execute steps 1–5 three times on the EXACT SAME
crash address and it still fails, you are using flawed logic. **STOP.** Do not guess a fourth time.
Open Ghidra, read `ps2tek`, or ask the user. You must break the loop."

### Ordered checklist

**Step 0 — Confirm it is a hang, not a crash.**
0.1 CPU core at ~100 % while the log stops printing ⇒ spinlock/deadlock (06 Blocker 3), not a fault.
0.2 Capture the stuck PC from the C++ debugger. That address is the input to everything below.
0.3 Grep the generated C++ for `// Unhandled opcode` and record every hit in
    `PS2_PROJECT_STATE.md` → **Unhandled Opcodes** (03 §3, "before attempting to build"). An
    unhandled opcode in the reached path explains a crash or wrong behaviour outright.

**Step 1 — Classify the stall site (06 Blocker 3).**
1.1 Look at the C++ / Ghidra decompilation of the stuck function for a spin on a fixed address.
1.2 `0x1000A0xx` ⇒ **DMA** completion never fired (07 §1).
1.3 `0x12000000` range ⇒ **GS** (07 §2); `0x12001000 & 8` is the classic V-SYNC wait.
1.4 No fixed address at all — a tight loop whose only call is a repeated `syscall` ⇒ the loop is
    *inside a syscall handler*, not a hardware spin. **GAP:** 06's triage (nop the branch) assumes
    a hardware-register spin; the sources give no recipe for a loop inside a `syscall` dispatch.
    Escalate to Step 5 rather than guessing.

**Step 2 — Check the address is even mapped (06 CRITICAL + db-overlay §2).**
2.1 Is the stuck PC inside the main ELF's `.text` range? If not → overlay/secondary-binary
    territory; go to the multi-binary rules.
2.2 Address-space check first, name check never: dispatch is `0xADDR → pointer`. Renaming generated
    C++ functions fixes nothing. Bind by address in TOML (`"name@0x00115000"`) or a Game Override.
2.3 Is it a `Function not found for address 0xXXXXXX`? → **Analyzer** stage: either map it as a
    known OS function stub, or (if large chunks are missing) re-export the function map from Ghidra
    and re-run `ps2_analyzer`.

**Step 3 — Is the stall just a missing/blank handler?**
3.1 `Unimplemented PS2 stub called: sub_XXXXXX` → you stubbed it in TOML but wrote no C++ handler.
3.2 Do **NOT** blanket-return 0. 06: "returning 0 on a function that allocates memory will create
    Zombie Threads and unresolved BSS-TRAPS later." (Telemetria Empirica / dynamic probing.)
3.3 Instead instrument and observe. Verbatim template:
    ```cpp
    void probe_sub_XXXXXX(R5900Context& ctx) {
        uint32_t a0 = ctx.gpr[4].words[0];
        uint32_t a1 = ctx.gpr[5].words[0];
        printf("[PROBE] sub_XXXXXX called. a0: 0x%08X, a1: 0x%08X\n", a0, a1);
        // If a0 looks like a pointer (e.g. 0x00A00000 range), dump the memory it points to!
        if (a0 > 0x00100000 && a0 < 0x02000000) {
            printf("  DUMP: [0x%08X] = 0x%08X\n", a0, *(uint32_t*)(memory + a0));
        }
        ctx.gpr[2].words[0] = 0; // Temporary bypass
    }
    ```
    Argument registers: `a0 = ctx.gpr[4]`, `a1 = ctx.gpr[5]`, return value `v0 = ctx.gpr[2]`.
    "If the values predictably increment or look like known enums, you can deduce the struct shape
    empirically."

**Step 4 — Unhandled syscall.**
4.1 `[Syscall TODO: 0x?? executing]` ⇒ the BIOS provides it (threading, sync, or HW access).
4.2 Implement in `ps2_syscalls.cpp` (06 Blocker 4). `WaitSema` / `SignalSema` are already hooked by
    the runtime (07 §5) — a stall there is a real signal-semantics bug, not a missing hook.
4.3 Never stub `SifLoadModule` to a failure value: it must return `1` / module ID > 0 (07 §3,
    db-overlay §4).

**Step 5 — Triage the loop (only after 1–4).**
5.1 TOML patch replacing the branch that forms the loop with `nop` (`0x00000000`) — 03 calls this the
    "easiest way to break an infinite spinlock waiting on unsupported hardware."
5.2 Or a C++ override that "forcefully advances the state the game is waiting for."
5.3 If the same crash address recurs 3× ⇒ Rule of 3 fires. Stop; open Ghidra / ps2tek / ask the user.

**Step 6 — Pre-flight checklist before asking "why is it stuck?" (06, all six).**
1. `registerAllFunctions(runtime)` is non-empty **and actually called before `loadELF`**.
2. The entry point function is registered.
3. The first unresolved function addresses are mapped or implemented.
4. The first unknown syscalls are handled.
5. No obvious same-PC infinite loop caused by direct raw handler binding in Game Overrides.
6. Temporary return stubs (`ret0`/`ret1`) are limited and documented — "if you left too many, the
   game logic will eventually fail randomly."
"If all 6 are true, you are in real behavior emulation territory, not plumbing failure."

---

## Contradictions

Listed only — **no other file was edited.**

### C1. The sources contain no boot syscall numbers, so they cannot confirm or deny our RE4 numbers
Our recorded RE4 boot sequence is `0x3C InitMainThread (a0=0x3d1df0 gp, a1=0xffffffff stack,
a2=0x50000)`, `0x3D InitHeap (a0=0x4a0a58, a1=0x100000)`, `0x40 CreateSema` ×2, `0x74 SetSyscall` ×2
(`0x83→0x2A1C88`, `0x5A→0x2A1C50`), then an unbounded loop on `syscall 0x83`.
**None of these numbers, names, or argument meanings appear in any of the four sources.** The closest
anchors are 07 §5's `CreateSema` (struct init `1`/max `1`) and its statement that the runtime hooks
`WaitSema`/`SignalSema` — no number, no argument layout, no ordering. `SetSyscall` is not mentioned
anywhere. So the RE4 sequence is **unconfirmed by this corpus, not contradicted by it**; the
apparent conflict is a *gap in the sources*, and citing these four files for that sequence would be
a fabrication. The likely homes for the numbers are out of scope: `resources/db-syscalls.md`,
`resources/04-runtime-syscalls-stubs.md`.

### C2. "Multi-binary / overlay" is described as a *separate-binary* problem; RE4's 93 overlays are not
db-overlay §3 is built entirely around **separate binaries** — one TOML per binary, `-base_address`
per binary, per-binary `ps2_analyzer`/`ps2_recomp`. But RE4 (SLUS_211.34) is a **single ELF** whose
93 overlay sections (155,808 bytes) all have `sh_addr == 0` and load over `.data`.
That is an *in-ELF* overlay mechanism, which the sources never cover: they give no rule for
`sh_addr == 0` sections, no `p_paddr`/`sh_offset`-based load derivation, and no statement about
whether such sections need a second TOML run at all. db-overlay §1's own definition of "code
overlay" ("portions of the game's **own** code loaded into fixed memory regions on demand") does
match, yet §3 then routes everything through the separate-binary pipeline. **Direct conflict in
applicability.** Note also that RE4's `.text` is clearly *not* "suspiciously small" (8,297 functions,
95.72 % byte coverage), so the "boot shim" signature in db-overlay §2 does not flag it either.

### C3. The address-space-conflict rule is stated only for *two binaries*, and is explicitly unstandardized
"If two binaries share the same address range … they CANNOT both be active at the same time … not
yet standardized in PS2Recomp." RE4's overlays conflict not with a second binary but with **the same
binary's own live `.data`**. The sources offer no rule for an overlay that clobbers resident data of
the binary that is executing, and explicitly disclaim a standardized mechanism. So we have 93
overlays recorded with no source-sanctioned strategy for the conflict.

### C4. Our stall happens *before* the playbook's milestone 2 — the milestone ordering is not a gate
06's five milestones assume boot → `SifLoadModule` → CDVD read → GS → first frame. We have "never
reached a file-I/O syscall," so RE4 is still inside milestone 1 ("Boot and Memory Init: stacks, BSS,
DMA channels"). Consequence: **milestones 2–5 and the 06/07 CD-IO guidance are not yet actionable**,
and the playbook offers no concrete guidance for a stall inside InitHeap-era code. Anything we do
next must come from the syscall trace itself, not from the playbook.

### C5. 06 Blocker 3's triage does not cover a loop inside a `syscall` handler
06 defines the infinite-loop blocker as "waiting for a hardware event" and its whole diagnosis is
"you will see something like `while ( *(uint32_t*)0x12000000 == 0 )`", with `0x1000Axxx` / `0x1200xxxx`
as the only addresses considered. Our recorded RE4 failure is **an unbounded loop calling
`syscall 0x83`** — no hardware address, the spin is inside the dispatch. The nop-the-branch patch in
§5.1 may not even be expressible (the branch is in the game, the loop body is a syscall). The
playbook's Blocker-3 section therefore does not apply as written. **GAP, not a contradiction of a
recorded fact** — but it is the single biggest hole in the corpus for our situation.

### C6. `SetSyscall` is unexplained by the sources, and the 0x83 loop is unexplained
Our record says `0x74 SetSyscall` remapped `0x83→0x2A1C88` and `0x5A→0x2A1C50`, *then* the game
loops on `syscall 0x83`. None of the four sources mentions `SetSyscall` at all, nor the semantics of
remapping a syscall number. The sources are silent; **no conclusion is drawn here.** Flagged because
it is the highest-value question the corpus cannot answer.

### C7. Internal source inconsistency: analyzer/recompiler CLI syntax
03 uses positional arguments — `ps2_analyzer.exe "game.elf" "base_config.toml"`,
`ps2recomp.exe config.toml` — and the `[general] code_base` TOML key. db-overlay §3 uses flags —
`ps2_analyzer SLUS_123.45 -o slus_12345.toml`, `-base_address 0x00200000`,
`ps2_recomp slus_12345.toml -o output/boot/`. The two forms cannot both be the real interface, and
neither was verified against the actual tool. **Do not trust either verbatim without checking the
binary's help output.**

### C8. Internal source inconsistency: a "boot shim" implies multiple `.text` sections — not applicable to RE4
db-overlay §2 lists "Multiple `.text` sections, or a `.text` section that's suspiciously small" as
overlay evidence, and states such an ELF "is a boot shim." RE4 is a single ELF with 93 overlay
sections loading over `.data` and near-complete coverage, so this particular detection heuristic is
a **false positive risk in the other direction** for us — the signal is absent here even though
overlays definitively exist. The sources offer no alternative detector for in-ELF overlays.

### Non-contradictions worth recording
- 95.72 % byte coverage on a stripped ELF is **consistent** with 03's mode 2 (stripped `jal`
  heuristic, "often misses boundaries"). The 4.28 % gap is expected behaviour, not a new finding.
- 8,297 functions is well under the 29,000+ that triggers the "thousands of C++ files" build
  guidance, but 03's build rules are stated as unconditional ("not optional"), so the Clang+Ninja
  mandate still applies.
- Nothing in the sources contradicts "93 overlays recorded"; it simply does not cover the case.

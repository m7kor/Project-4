# knowledge/PS2_REFERENCE.md — consolidated knowledge

Everything below was read from source in Oct 2026. Cited per claim.

Correction from executable-word regressions on 2026-10-05: SYSCALL is
SPECIAL/function `0x0C`; primary opcode `0x0C` is ANDI. REGIMM is `0x01`,
not MMI's `0x1C`. GPR LD/SD are `0x37`/`0x3F`; historical descriptions of
these as reversed COP2 saves/loads are invalid. The corrected RE4 census
is 155 SYSCALL sites, all with code field zero, not 5,702. Historical counts
and ABI conclusions derived from the old decoder must not be reused as evidence.

---

## 1. Toolchain lineages — three DIFFERENT trees (do not mix)

| Lineage | ISA | Tool | Projects |
|---|---|---|---|
| **PS2Recomp** | R5900 (MIPS) | `ran-j/PS2Recomp` | every PS2 project except AC5/Twinsanity |
| **PSXRecomp** | R3000A (MIPS, PS1) | `Unchiga/psxrecomp` | Yu-Gi-Oh Forbidden Memories |
| **ReXGlue / XenonRecomp** | PPC / Xenos (Xbox 360) | `ReXGlue-SDK` | Condemned 2, Downpour, Deadly Premonition |

⚠️ Four projects commonly listed as "PS2 recomp" are **Xbox 360 or PS1**:
`psxrestore/Condemned2Recomp` (X360), `LittleBitUA/DownpourRecomp` (X360),
`LittleBitUA/DPRecomp` (X360), `Unchiga/YuGiOhForbiddenMemoriesRecomp` (PS1).
The GitHub topic `static-recompilation` is what pulls them in.

**Reusable *technique* from ReXGlue projects (X360, so concepts only):**
- **60 FPS via error accumulator, not doubling** (DPRecomp): *"the game gets whole
  logic ticks with an error accumulator, exactly like the console's vblank count:
  1, 1, 1, … and a 2 every few hundred frames."* ⇒ **the correct PS2 answer.**
- **60 FPS via recompile-time patch** (DownpourRecomp) with `refresh_rate = 120.0`
  because *"guest expects half-vblank ticks"* ⇒ patch the SoA/quantum constant,
  never a host frame limiter.
- **Texture mods by pixel hash**, stable across all machines:
  `textures/<hash>.png` + `<hash>.overlay.png`. Works identically for GS uploads.
  ⇒ same trick as BT3's `<TEX0Hash>-<CLUTHash>-<bits>`.
- **Decouple presentation rate from simulation rate**: *"presentation at 59.94 FPS
  while simulation and audio run at the selected accelerated speed"* (YuGiOh).
- **A recompiler codegen bug presented as systematically wrong lighting**, not a
  crash: *"A recompiler bug skipped the block that switches on each scene's main
  light … in 297 of the game's 462 pixel shaders."*

---

## 2. Upstream PS2Recomp — exact internals

Read from `ran-j/PS2Recomp@main`, project name `PS2RetroX`.

### 2.1 Ghidra export schema (`ExportPS2Functions.java`, 1138 lines)
- **CSV: exactly 4 columns** `Name,Start,End,Size`. `End` is **exclusive**.
  `Size` is address-set cardinality, **not** `End - Start`.
- `Name` is written **raw, unquoted, unescaped** ⇒ a name containing a comma
  silently corrupts the row (parser drops it).
- TOML output: `[general]` with `input, output, ghidra_output,
  single_file_output, patch_syscalls=false, patch_cop0=true, patch_cache=true,
  stubs[], untracked_stubs[], skip=[]` + `[ghidra_export]` counters.
- **`skip` is ALWAYS empty.** `skip_count` is hardcoded `0`.
- Embedded handler snapshot: **656** names; the runtime actually has **658**
  unique (121 syscalls + 543 stubs, 5 overlapping). Missing from the Java
  snapshot: `GetOsdConfigParam2`, `SetOsdConfigParam2`.
  ⇒ **Regenerate from `ps2_call_list.h`; do not trust the snapshot count.**
- `PS2_API_PREFIXES` = 27 (9 stems × 3 casings), and matching is **shape-based**:
  prefix matches only if the next char is not lowercase (`gsPrintf` ✓, `gsub` ✗).
- Rejected as unreliable names: `sub_`, `FUN_`, `func_`, `entry_`, `function_`,
  `LAB_`, no-alpha names, pure-hex `0x…`.
- **Synthetic entry discovery**: 3 passes — callable label refs; `lui`+`ori/addiu`
  materialization with an 8-word prologue sniff (lookahead 4 instructions); and
  data-pointer scan with a **32-byte cluster filter** (`.ctors`/`.dtors`/
  `.init_array`/`.fini_array` bypass the filter).

### 2.2 `ps2_call_list.h`
- `PS2_SYSCALL_LIST` = **121** · `PS2_STUB_LIST` = **543** · unique = **658**.
- **No numeric syscall IDs in this header.** IDs live in
  `Kernel/Syscalls/Dispatcher.cpp` `dispatchNumericSyscall` (~90 cases).
  Sample: `0x01 ResetEE`, `0x02 GsSetCrt`, `0x04 ExitThread`, `0x20-0x24` thread
  ops, `0x3D SetupHeap`, `0x40-0x42` sema, `0x64/-0x68 FlushCache/iFlushCache`,
  `0x7C Deci2Call`, `0x82 InitTLB`, `0x83 FindAddress`.
  `i`-variants use `static_cast<uint32_t>(-0xNN)`.
- The recompiler `#include`s this header **directly** (PRIVATE include), so the
  two share one name list at compile time. Renaming a handler silently breaks
  generated code.

### 2.3 `game_overrides.h` — exact API
```cpp
using ApplyFn = void (*)(PS2Runtime &runtime);
struct Descriptor { const char* name; const char* elfName;
                    uint32_t entry; uint32_t crc32; ApplyFn apply; };
PS2_REGISTER_GAME_OVERRIDE(NAME, ELF_NAME, ENTRY, CRC32, APPLY_FN)
ps2_game_overrides::bindAddressHandler(runtime, addr, "handler")
```
Matching = **AND of all non-zero fields**; `0` is a wildcard for `entry` and
`crc32`; `elfName` is a case-insensitive basename compare.
⚠️ **This is C++ in the core — the exact mechanism that causes per-game forks.
Replacing it with a data-driven boundary file is Lodestone's R2.**

### 2.4 `ps2xIOP` — the README contradicts the ecosystem's belief
> *"Game-specific IOP code executes from IRX modules. **There is no game-profile
> selection or native profile-plugin loader.** A physical IRX RPC server is
> authoritative for its SID."*

**There is no plugin ABI and no built-in game-profile list.** Only three generic
HLE services:

| Service | SID |
|---|---|
| MCSERV | `0x80000400`, `0x80000480` |
| LIBSD | `0x80000701` |
| DBCMAN | `0x80001300` |

And: *"These services are dormant before module load and after reset or the final
module stop."* No R3000A CPU, no IRX execution. **Across the entire scene, no
project runs real IRX.**

### 2.5 TOML keys `config_manager.cpp` actually reads
`[general]`: `input*`, `output*`, `ghidra_output`, `single_file_output`,
`low_memory_mode`, `output_worker_threads` (clamped to `[0, nproc*2]`),
`patch_syscalls`=false, `patch_cop0`=**true**, `patch_cache`=**true**,
`stubs[]`, `entry_points[]`, `untracked_stubs[]` (legacy alias), `skip[]`.
`[patches].instructions[]`: `address`, `value`.
**Root only (never `[general]`)**: `mmio`, `jump_tables.table[]` with
`address`, `base_register`, `entries[].index`, `entries[].target`.
`[performance] critical` is **written by the analyzer and read by nothing.**

### 2.6 Code generation
- Signature: `void NAME(uint8_t* rdram, R5900Context* ctx, PS2Runtime *runtime)`.
  `R5900Context` is `struct alignas(16)`; GPRs are `__m128i r[32]`.
- **Dispatch is a dense address-indexed array**, one pointer per 4 bytes of
  guest address span. A 4 MB span ⇒ 1M entries ⇒ ~8 MB on 64-bit, regardless of
  function count. Lookup is arithmetic, bounds-checked, rejects `address & 3`.
- Delay slots are **inlined**, bracketed by `ctx->in_delay_slot = true/false` and
  `ctx->branch_pc`. A NOP delay slot emits **nothing**.
- Backward internal edges emit `if (runtime->eeCheckpointDue()) return;` — the
  EE scheduler's yield hook.
- `SYSCALL` → `ctx->pc = addr+4; runtime->handleSyscall(rdram, ctx, (raw>>6)&0xFFFFF)`.
  Inside a delay slot it **throws**.
- **`JR $ra` is a bare `pc = target; return;` by default** ⇒ a missing return
  target is *silent*. Set `PS2X_STRICT_RETURN_DIAGNOSTICS=ON` for diagnostics.
  ⇒ **Largest silent-failure source in the whole toolchain.**
- **Unhandled instructions emit a runtime `throw` into the generated C++**, not
  a compile error. Main-opcode gaps: `0x13 COP3`, `0x32 LWC2`, `0x34 LLD`,
  `0x35 LDC1`, `0x3A SWC2`, `0x3C SCD`, `0x3D SDC1`, and anything `>= 0x40`.
  (Note `LWC2`/`SWC2` are flagged VU but still fall through to `default`.)

### 2.7 `elf_parser.cpp` — the section-overlap hazard
`readWord()` scans `m_sections` **in ELF section-header-table order** and returns
the **first** match — not sorted by address, and no preference for
`SHF_ALLOC`/`SHF_EXECINSTR`. `SHT_NOBITS` sections are skipped (data==nullptr).
`isValidAddress()` uses **any**-match, so the two disagree.

⇒ **Any retail ELF with overlapping section VMAs resolves to whichever section
appears first in the header table.** `.hack//` worked around this by fabricating
an analysis ELF (`build_mwo3_analysis_elf.py`) and neutralizing a huge
non-alloc `.debug` section at `sh_addr=0`. **A single upstream fix here kills a
whole class of problems for every project.**

`FindFunctionSectionByAddress` prefers a code section, and only falls back to
any section if the ELF has **no** executable section at all.

### 2.8 Memory model
RDRAM 32 MB · scratchpad 16 KB at `0x70000000` (aliases `0xF0000000` and
KSEG `0x80000000`-set) · IO `0x10000000`+64 KB · GS regs `0x12000000`+8 KB ·
GS VRAM 4 MB · BIOS `0x1FC00000`+4 MB · IOP RAM hardcoded 2 MB.
TLB: **flat 48 entries, fully associative, no ASID**, `PageMask` truncated to
bits 13..24, `pfn` 20 bits, **a miss throws**.
`EE clock = 294.912 MHz`; timer clocks `{147456000, 9216000, 576000, 15734}`.

⚠️ **Two divergent address translations.** `PS2Memory::translateAddress` walks
the TLB; but `ps2ResolveGuestPointer` (used by the generated `READ*`/`FAST_READ*`
macros) **never consults the TLB** and masks `0xC0000000 → 0`. They disagree
for KSEG2/KSEG3. `InstructionTranslator` routes those to
`runtime->LoadN/StoreN` to paper over it.

### 2.9 Build
Root `project(PS2RetroX)`, C++20, CMake ≥ 3.21. Targets: `ps2_recomp_lib`,
`ps2_recomp`, `ps2_analyzer_lib`, `ps2_analyzer`, `ps2_iop` (alias
`ps2x::iop`), `ps2_runtime`, **`ps2EntryRunner`**, `ps2_test_lib`, `ps2x_tests`,
`ps2xStudio`, `imgui`, `rlImGui`, `rabbitizer`.
Options: `PS2X_BUILD_{RECOMP,RUNTIME,ANALYZER,TEST,STUDIO}` all ON;
`PS2X_ENABLE_RUNNER_UNITY_BUILD`=ON, `PS2X_ENABLE_RUNNER_PCH`=ON,
`PS2X_ENABLE_SCCACHE`=ON, `PS2X_ENABLE_RUNTIME_LOGS`=ON,
`PS2X_ENABLE_AGRESSIVE_LOGS`=ON (typo is upstream's), `PS2X_IOP_RPC_TRACE`=ON,
`PS2X_STRICT_RETURN_DIAGNOSTICS`=OFF, `PS2X_ENABLE_DEBUG_UI`=ON,
`PS2X_ENABLE_FFMPEG`=ON unless Android.
Unity build batch size 32, applied **only** to `ps2EntryRunner`.
Pinned: elfio `Release_3.12`, toml11 `v4.4.0`, fmt `12.1.0`, libdwarf `v2.2.0`,
**rabbitizer `1.14.3`** (also the decoder for Twinsanity — two projects
independently chose it), imgui `docking`, SDL2 `release-2.32.10`, sse2neon.
Android forces runtime-only, so **`ps2xStudio` cannot build for Android**.
Vita auto-enables if `$VITASDK` is set.

### 2.10 HLE surface (`Kernel/`)
Syscalls (13 files, ~126 definitions): Deci2(1), FileIO(10), Interrupt(24),
RPC(13), Sync(32), System(30), Thread(27).
Stubs (34 files, **561** definitions vs 543 list entries):
Audio 93, MemoryCard 65, GS 59, LibC 56, SIF 49, CD 43, VU 43, MPEG 30,
Pad 30, DMA 21, FileIO 21, Compatibility 14, Font 10, Deci2 9, System 9,
TTY 6, IPU 5, RPC 3, Unimplemented 1.

### 2.11 `ps2xStudio` (GUI)
ImGui docking + SDL2 + OpenGL. Five windows: **main menu bar** (Open ELF,
Import Ghidra CSV, Save Config, Analyze `F5`, Recompile `F7`), **Settings**
(theme/fonts/scale), **Explorer** (function list colour-coded by
`OverrideStatus`: Stub red, Skip grey, ForceRecompile green), **Inspector**
(name + 4-way strategy combo + address/size/instruction count), **Workspace**
4 tabs (C++ Preview, Hex View, config.toml, Ghidra CSV), **Logs** (progress +
copy/clear).
⚠️ **No EE/GPU/IOP debugger** — that lives in `ps2_debug_panel.cpp` (95 KB).

---

## 3. Codegen bugs worth checking FIRST in any PS2 port

Each was independently found and measured by a different project:

| Bug | Effect if present | Found by |
|---|---|---|
| `$ra` not assigned by `jal`/`jalr` | every non-leaf fn returns to a stale address | psprecomp |
| VU0 destination-component mask reversed | models/clips render wrong, silently | DC2 (`mgDistVectorXZ__FPf`) |
| divide-by-zero handling | | REO contributor |
| 64-bit branches (`BEQ`/`BNE` on 64-bit) | | REO contributor |
| `div.s` IEEE assumptions | **R5900 FPU is not IEEE** | DC2 (G371) |
| VU0 macro `VDIV`/`VSQRT` PS2 float | | DC2 (G372) |
| `DCT` coefficient bit position | decoding artifacts | ReXGlue 0.10 ports |
| APC delivery through a trap frame | | ReXGlue 0.10 ports |

DC2's own framing of its hardest bug is the lesson:
> *"A real-world port lost **~50 phases** chasing a black 3D scene in the
> runtime/GS when the bug was a **single reversed lane-mask in the recompiler's
> codegen**."*

---

## 4. Performance — what actually moved the needle

| Lever | Measured | Source |
|---|---|---|
| VU1 as native x86-64 (5-level JIT) | DC2's whole perf effort | DC2 |
| GS in Vulkan compute (paraLLEl-GS) | 2.9 ms GPU/frame @30fps on RTX 5080 | BT3 |
| GS lookup-table reduction | **2.75 MiB → 88 KiB**, no quality loss | PS2RecompAIWorkflow (563/563 tests) |
| Compiling out closed prototypes | −1.082 ms/f on all three threads at once | DC2 (G629–636) |
| TU layout (150 cold lines) | +0.567/+0.934 ms/f | DC2 rule 12b |
| `const bool`-guarded diagnostics | +0.484 ms/f, unrecoverable by env | DC2 rule 12c |
| Three-thread frame model | `frame ≈ max(VU1 busy, GS own, EE cpu)` | DC2 rule 7 |
| Single-FIFO backend ceiling | recoverable = `blocked − backendBusy`, no more | DC2 rule 10 |
| Frame pacing is a constant | 139,944 ticks/s ÷ 20,000 quantum = 7.0 vblank | SDBZ |

**Honest status of the best projects:**
- DC2: **0/14** measured windows under 16.67 ms. Best 16.67, worst 35.96.
- SOCOM II: **~27 ms/frame** vs the console's 16.7 — *slower than an emulator*.
- AC5: "fully playable"; 3D native, menus still emulated GS.

⇒ **Nobody has made a PS2 recomp faster than PCSX2 yet.** That is the open
performance frontier, and it is a GS/VU problem, not an EE problem.

---

## 5. GS feature checklist — minimum viable set
From REO, which reached a rendering title screen with a software rasterizer:
> *"GS software rasterizer — supports flat sprites, textured sprites (PSMCT32 +
> PSMT8 indexed), GIF IMAGE mode (swizzled VRAM upload), A+D register writes,
> XYOFFSET, scissor clipping, alpha test (TEST_1), alpha blending, PSMCT32 VRAM
> swizzle tables."*

Named GS bug classes: TEX0 register storage bug; VRAM page conflict on texture
upload; VIF chain tag dropping the upper quadword for REF/REFS/REFE.

**GS semantics that break ports** (from `PS2Docs/BOOKMARKS.md`):
- *"A pending VSYNC semaphore token does not prove that scanout is still blank.
  **VIF FLUSH is not a GS raster-completion fence.**"*
- `ZTST` defines the depth tie rule — LEQUAL does not resolve independently
  triangulated coplanar surfaces.
- Packed `XYZF2` drops the 4 low Z bits produced by `FTOI4`.
- REGION_CLAMP shifts with mip level; MIPTBP block bases must match uploaded
  PSMCT32 geometry.
- Texture page buffer ≈ DRAM sense amplifier; PSMCT32 page = **64 × 32 px**.

---

## 6. VU1 — the four strategies

| Project | Strategy |
|---|---|
| **AC5** | **census at runtime** (`PS2_VU_CENSUS=1` dumps uploaded microprograms) → **statically recompile to C** with a second compiler (`tools/vurecomp`) → `PS2_VU_RECOMP=0` to A/B. 15 programs from one mission. |
| **DC2** | 5-level stack ending in an **x86-64 JIT** built from the microprogram CFG. |
| **BT3** | `vu1_programs.json` (ELF offsets + hashes) + translation generated from the player's ELF at setup. |
| upstream | interpreter; *"VU1 microcode is not complete"* |

AC5 also **rewrote the VU1's job as native C++**: it decodes the VU1 uniform
bank (`m[16] c[16] l[12] e[12] …`) into a C struct and draws real GPU meshes,
gated by `ps2_vk_mesh_material_ok()` with a backbuffer fallback. **The vector
unit's lighting/transform math is gone rather than emulated.**

VU1 flag semantics that matter (GS/VU manual Ch 3.3.5 / 3.4):
ABS/MAX/MINI/FTOI/MOVE set **no** flags; Q/ACC/I have **no interlocks**;
`waitq` stalls both pipes.

---

## 7. Network / online play
**No project emulates the PS2 Network Adapter (SMAP/EMAC3).** All replace it at
the **IOP SIF service** boundary with host sockets. The stack above it
(`ps2ip`/lwIP, `libnetb`) is bypassed too.

The only working implementation: **SOCOM II**, which replaces the guest's
`socom2_libnetb.cpp` on the EE side and speaks Medius to a Horizon private
server. Critical detail (dead_end 0013): `sceInetInterfaceControl` code `0x200`
**must return a real RX byte count** — returning `0` reproduces a movement bug.

Status: *"two copies of the game have finished online rounds against each other
on the project's test server … on one machine. **No two people have played each
other yet.**"* Voice not implemented. Two separate stacks exist: Medius/Horizon
(SOCOM) vs CRI SN@P/DNAS (Outbreak/obsrv.org).

SECURITY posture worth copying verbatim:
> *"Online play is at your own risk … never with a build you did not compile or
> verify, and not yet against a community server."*

---

## 8. HDD boot — a genuine gap
**No project boots from a PS2 HDD image.** Reason, stated as architecture:
> *"the game issues raw sector reads that cannot be served from loose files."*

Enabling primitives that exist: the IOPRP **ROMDIR** parser
(`ifcaro/Open-PS2-Loader/src/ioprp.c`) and the 232-byte `HDLFS_FormatArgs`
structure (`binkynz/ps2-usbhdl`), which together would let an OPL/HDL image be
presented to the CDVD layer as a raw sector device.
`ioprp.img` is a ROMDIR image of `{name[16], extinfo_size, file_size}` at 16-byte
alignment; `REBOOT` installs SIF command `0x80000003` for `rom0:UDNL`.
⚠️ **`modules.dat` is NOT a documented PS2 structure** — do not cite it as one.

---

## 9. RE4 (SLUS_211.34) format facts
| Container | Format | Notes |
|---|---|---|
| `bio4dat.afs` | **plain CRI AFS** | generic tools suffice |
| `.dat` inside AFS | **GCA** (G Compression Archiver) | rename `.dat`→`.gca`; main (`em.dat`, `st1.dat`, `xfile.dat`), sub (`pl00.dat`), MAP files |
| textures | **TPL**, not TIM2 | `interface` CLI + Pragrana; swizzle not supported by `interface` |
| audio | **OGG Vorbis** in `ogg.dat` | `bgmtbl.dat` = cue table, `plXX_prog.out.lst` = cue lists. **No ADPCM.** |
| `0FLIST.DIR` | generic Capcom PS2 root file | **not** an archive |
| models | `.BIN` (**not** AMO — AMO is Outbreak) | |
| cutscenes | STR/ATR, IMA ADPCM *(community consensus, no primary source)* | do not assert |
| `modules.dat` | **undocumented** | |

Existing tooling: `interface` (Shin-ichi Tsuruta), Universal Quick DAT
(Un)Packer (zatarita), GCA Extractor, `OBTool` (Fothsid), AFS libs
(`MaikelChan/AFSLib`, `NeoGF/afstool`, `cri-afs` on PyPI), JADERLINK's
"RE4 PS2 - AFS Tool".

⚠️ **REO's `amo_parser` is Outbreak, not RE4** — its value to us is the *AFS/NBD/
AMO reading pattern*, not the format itself.

---

## 10. Hardware manuals — question → source
Best-indexed host: **`ninjadynamics/PS2Docs`** (127★) — GS 177p, EE Core
Instruction Set 409p, VU 369p, SPU2 80p, EE 219p, EE Core 181p, EE Overview 65p,
plus `BOOKMARKS.md` and `LESSONS_LEARNED.md` ("each chapter gives you a rule you
can apply, the failure mode that makes you reach for it, and a pointer to the
relevant Sony manual chapter").
Second host: `hkmodd/ps2-recomp-Agent-SKILL/resources/pdfs` (18 PDFs) plus
`resources/db-*.md` — an already-indexed knowledge base with a master router.
Also: **PS2Tek** (`israpps.github.io/ps2tek/`), **Copetti**'s practical analysis,
**psdevwiki**.

**Ghidra loader gotcha:** `MIPS:LE:32:R5900` is not a valid processor ID.
Use **`r5900:LE:32:default`** from `ghidra-emotionengine-reloaded`, because the
ELF header claims plain MIPS and Ghidra will not auto-detect.

---

## 11. Community index
`recomp.fyi` — **1,543 rows** (895 recomp / 68 port / 580 decomp),
1,214 active, but only **45 owner-claimed**, and it admits
*"Most rows were read from their repository by a script, and scripts misread."*
`.recomp.json` schema v1 (draft; `port` added 2026-10-01, list `toolchain`
2026-10-02). `recomp.board` is the brand; only `recomp.fyi` resolves.
GitHub topics are near-useless here: `ps2-recomp` = **1 repo**,
`static-recompilation` = 174 (includes Xbox 360), `recompilation` = 146
(dominated by emulators and awesome-lists).

---

## 12. Licensing — the constraint nobody respects
| Licence | Projects |
|---|---|
| GPL-3.0 | upstream PS2Recomp, BT3, .hack, SOCOM II, SDBZ, MC3-Port |
| AGPL-3.0 | DC2 |
| Apache-2.0 | AC5 |
| MIT | psprecomp, ps3recomp, Ehren1337, MGS3 |
| BSD-3 | DownpourRecomp (host only), DPRecomp is MIT |
| **NO LICENCE** ⚠️ | **REO, Twinsanity, ej-sanmartin, REOF2, gt4** |
| **CC0** ✅ | WoS-Findings |
| PolyForm Noncommercial | YuGiOh |

⇒ **We may take *ideas* from unlicensed projects but must never copy their code.**
Anything derived from PS2Recomp is **GPL-3.0**. That is the licence of Lodestone.

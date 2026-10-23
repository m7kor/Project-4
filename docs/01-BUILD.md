> تحديث 2026-10-05: الأمر المدعوم من جذر المشروع هو `python -m ps2l build --jobs 8`.
> يستكمل البناء بعد التهيئة الأولى، ويتتبع أسماء الملفات وإعدادات CMake المطلوبة.
> لا يحذف أقفال Ninja. مسارات وأزمنة الأقسام التالية تتضمن قياسات تاريخية.
> `python -m ps2l verify` يفحص الأدوات؛ لا يمنح شهادة توافق للعبة.

# Building the core — verified settings

Everything here is taken from upstream `ran-j/PS2Recomp` source or from a
documented failure in the field. **If a setting is not justified by a citation
in this file, it is not a default.**

---

## 0. Why the toolchain matters more than the code

The single largest schedule risk in PS2 recompilation is build time, not
correctness.

| Toolchain | Full rebuild | Source |
|---|---|---|
| MSVC + Visual Studio solution generator | **20–30 h** | `Agent-SKILL` `resources/03-ps2recomp-pipeline.md` |
| MSVC + Ninja | 3–5 h | same |
| **clang-cl + Ninja** | **~1 h** | same |
| MSVC + MSBuild (as DC2 actually uses it) | **30+ h** | `DC2-PS2RECOMP` `PS2_PROJECT_STATE.md` |

RE4 generates on the order of 6k functions (~10k translation units at
per-function output). At 30 hours per full rebuild, iteration is impossible.

### Commands

```powershell
git clone --recurse-submodules https://github.com/ran-j/PS2Recomp.git
cd PS2Recomp

# Configure with Ninja. NOT the Visual Studio generator.
cmake -S . -B out/build -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_C_COMPILER=clang-cl `
  -DCMAKE_CXX_COMPILER=clang-cl `
  -DPS2X_ENABLE_RUNNER_UNITY_BUILD=OFF `
  -DPS2X_ENABLE_RUNNER_PCH=ON `
  -DPS2X_ENABLE_SCCACHE=OFF `
  -DPS2X_ENABLE_RUNTIME_LOGS=ON `
  -DPS2X_STRICT_RETURN_DIAGNOSTICS=ON

cmake --build out/build --target ps2_recomp ps2_analyzer
```

With Ninja the build type is fixed at **configure** time via
`-DCMAKE_BUILD_TYPE=Release`. There is no `--config`.

---

## 1. Five settings that are non-negotiable

### 1.1 `PS2X_ENABLE_RUNNER_UNITY_BUILD=OFF`
Unity build is ON by default upstream. It is **counterproductive** with Ninja's
native parallelism across ~29,000 files (`Agent-SKILL` §4, operation B).

A separate project, SOCOM II, reaches the same conclusion from the other
direction: it uses unity batches of 32 ordered by guest address so a rename
keeps its file in its batch, and measures *"a recomp with nothing changed
rebuilds 0 objects; one display name changed … rebuilds 2 … and relinks in 27 s"*.

⇒ Lodestone default: **OFF**. If we re-enable unity it must be size-32 and
address-ordered, never the CMake default.

### 1.2 `PS2X_STRICT_RETURN_DIAGNOSTICS=ON`
By default the generated code emits, for `jr $ra`:

```cpp
ctx->pc = <target>;
return;
```

— **no check that the target exists.** A missing return target is silent: the
program falls into nothing and the next symptom appears somewhere unrelated.

With the flag on, it routes through
`runtime->dispatchGuestBranch(..., GuestBranchKind::Return, "JR $ra")` and
reports.

⇒ This is the highest-value single flag in the whole toolchain for a new port.
`ps2l/profile.py` **fails the profile** if it is not ON.

### 1.3 Never clean the build
No `--clean-first`. No `Remove-Item build*`. The cost is 20–30 h and there is no
undo. `Agent-SKILL` prohibition 1; DC2 makes it "Rule 2".

If a build is genuinely poisoned, delete **one** translation unit, not the tree.

### 1.4 Never edit `runner/*.cpp` or shared headers
The generated files are overwritten on the next recompile, and headers are
included by every one of ~10k TUs. `Agent-SKILL` prohibitions 2–3.

⇒ Use file-scope `static` in a `.cpp`, or a plugin, or a game override
registered by address.

### 1.5 `add_compile_options(-msse4.1)` must accompany `USE_SSE41`
`add_compile_definitions(USE_SSE41=ON)` only defines a macro. clang needs the
actual flag to emit intrinsics such as `_mm_extract_epi32`. Both are required
(`Agent-SKILL` §4, operation A). Without it the build may still succeed and
then fail at compile of the intrinsic.

### 1.6 `/EHsc` must be applied tree-wide under clang-cl
clang-cl defaults to `-fno-exceptions`. The real MSVC driver lets `try`/`throw`
through without a flag, so upstream works on MSVC and dies on clang-cl at the
first exception:

```
ps2xIOP/src/emulator/iop_emulator.cpp(510,17): error:
    cannot use 'throw' with exceptions disabled
```

This cannot be fixed in `ReleaseMode.cmake`, which only reaches targets that call
`EnableFastReleaseMode()`, and `ps2_iop` is not one of them. It goes in the root
`CMakeLists.txt` as `add_compile_options(/EHsc)` (LODESTONE PATCH 7,
dead_ends#0058).

### 1.7 Every `FetchContent` dep needs a vendored source dir
Network clones of nested submodules hang for tens of minutes. Vendoring into
`core/deps/` and pointing `FETCHCONTENT_SOURCE_DIR_*` at them takes configure
from "hangs" to **8 seconds**:

```powershell
$d = "C:/Project/PS2redmption/core/deps"
cmake -S . -B out/build `
  -DFETCHCONTENT_FULLY_DISCONNECTED=ON `
  -DFETCHCONTENT_SOURCE_DIR_ELFIO=$d/elfio `
  -DFETCHCONTENT_SOURCE_DIR_TOML11=$d/toml11 `
  -DFETCHCONTENT_SOURCE_DIR_FMT=$d/fmt `
  -DFETCHCONTENT_SOURCE_DIR_LIBDWARF=$d/libdwarf `
  -DFETCHCONTENT_SOURCE_DIR_RABBITIZER=$d/rabbitizer `
  -DFETCHCONTENT_SOURCE_DIR_NLOHMANN_JSON=$d/nlohmann_json `
  -DFETCHCONTENT_SOURCE_DIR_RAYLIB=$d/raylib
```

**raylib is the one people forget.** Its header is `src/raylib.h`, not the repo
root, and `ps2_audio.cpp` includes `"raylib.h"`. Without
`FETCHCONTENT_SOURCE_DIR_RAYLIB` the configure succeeds, ~6,000 objects build,
and then it fails — which wastes far more time than the original error.

### 1.8 Disable sccache on Windows for full builds
```
sccache: error: Only one usage of each socket address
    (protocol/network address/port) is normally permitted. (os error 10048)
```
That is port exhaustion in sccache's local server under Ninja's full
parallelism, not a compile failure. `-DPS2X_ENABLE_SCCACHE=OFF` builds clean and
loses nothing here: with a PCH, 5,997 of 6,078 requests are non-cacheable (`/Fp`).

### 1.9 Full working configure line

This is the historical diagnostic build with FFmpeg disabled, not a verified
configuration for complete video playback. The current RE4 investigation
has proved sampled SFD delivery but has not established that this game's
native Sofdec path reaches the runtime's `sceMpeg` HLE decoder. Enabling
FFmpeg provides that HLE backend; it does not implement guest IPU commands
or prove RE4 movie compatibility. See [CURRENT.md](CURRENT.md).

```powershell
$env:PATH = "C:\Program Files\LLVM\bin;" + $env:PATH   # clang-cl must be on PATH

cmake -S . -B out/build -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_C_COMPILER=clang-cl `
  -DCMAKE_CXX_COMPILER=clang-cl `
  -DPS2X_ENABLE_RUNNER_UNITY_BUILD=OFF `
  -DPS2X_ENABLE_RUNNER_PCH=ON `
  -DPS2X_ENABLE_SCCACHE=OFF `
  -DPS2X_ENABLE_RUNTIME_LOGS=ON `
  -DPS2X_STRICT_RETURN_DIAGNOSTICS=ON `
  -DPS2X_ENABLE_FFMPEG=OFF `
  -DPS2X_ENABLE_DEBUG_UI=OFF `
  -DPS2X_BUILD_STUDIO=OFF `
  -DPS2X_BUILD_TEST=OFF `
  -DPS2X_RUNNER_SRC_DIR=C:/Project/PS2redmption/recomp/generated/SLUS_211.34 `
  -DFETCHCONTENT_FULLY_DISCONNECTED=ON `
  <the six FETCHCONTENT_SOURCE_DIR_* lines from 1.7>
```

Measured on this machine, 12 cores: 8,343 build edges, 0 failures, producing a
92.4 MB `ps2EntryRunner.exe`.

---

## 2. The recompile step

```powershell
# 1. our analysis (Ghidra-free), produces a compatible CSV
python ..\ps2l\cli.py analyze "..\game\Resident Evil 4 (USA)\SLUS_211.34" --out ..\analysis

# 2. upstream analyzer for a second opinion on stubs
.\out\build\ps2_analyzer.exe `
  "..\game\Resident Evil 4 (USA)\SLUS_211.34" `
  ..\recomp\config_re4.toml

# 3. recompile
.\out\build\ps2_recomp.exe ..\recomp\config_re4.toml
```

### The config we generate

```toml
[general]
input = "SLUS_211.34"
output = "generated/SLUS_211.34"
ghidra_output = "analysis/functions.csv"
single_file_output = false
low_memory_mode = false
output_worker_threads = 0
patch_syscalls = false      # upstream default; keep
patch_cop0 = true           # upstream default; keep
patch_cache = true          # upstream default; keep
stubs = []                  # grows only from a traced fault
skip = []                   # ALWAYS EMPTY — see below
```

### Two traps in the TOML, from source

1. **`skip` is a legacy field.** `ExportPS2Functions.java` hardcodes
   `writer.println("skip = []")` and `skip_count = 0`. The analyzer no longer
   populates it. Do not plan around it; use `stubs`.
2. **`mmio` and `jump_tables` are read from the TOML ROOT only** — never from
   `[general]`. Every other list key tries `[general]` first and falls back to
   root (`config_manager.cpp:150-260`). Getting this wrong is a silent no-op.
3. `[performance] critical` is written by the analyzer and **read by nothing**.

---

## 3. Unhandled opcodes you will hit

Upstream emits a **runtime `throw` into the generated C++**, not a compile
error. So an unhandled opcode shows up as a crash at run time, not a build
failure. Grep the generated tree for `Unhandled` before you believe a build
is clean.

Known main-opcode gaps in `instruction_translator.cpp`:

| Opcode | Mnemonic | Note |
|---|---|---|
| `0x13` | COP3 | unused on PS2 |
| `0x32` | LWC2 | flagged `isVU` but still hits `default` |
| `0x34` | LLD | |
| `0x35` | LDC1 | |
| `0x3A` | SWC2 | flagged `isVU` but still hits `default` |
| `0x3C` | SCD | |
| `0x3D` | SDC1 | |
| `>= 0x40` | all | |

`LDC2`/`SDC2` (`0x36`/`0x3E`) **are** handled and are the real VU vector
load/store path. `LWC2`/`SWC2` being marked VU but unhandled is an upstream
inconsistency worth fixing in our fork.

---

## 4. Two upstream bugs worth fixing before anything else

Both were found the hard way by other projects and are core-level, so fixing
them serves every port.

### 4.1 `readWord()` resolves sections in header order
`elf_parser.cpp` builds `m_sections` with an un-sorted loop over the section
header table, and `readWord` returns the **first** section whose range covers
the address. It does not prefer `SHF_ALLOC` or `SHF_EXECINSTR`, and it silently
skips `SHT_NOBITS`.

RE4 is the pathological case: 93 `.DVP.overlay.*` sections all with
`sh_addr == 0`, plus `.reginfo`, `.DVP.ovlytab`, `.DVP.ovlystrtab` and
`.shstrtab` also at 0. Every one of them shadows low addresses.

`.hack//Recompilation` needed four iterations of a purpose-built script
(`build_mwo3_analysis_elf_v1..v4.py`) to work around the general form of this by
fabricating a synthetic ELF and neutralizing a huge non-alloc `.debug` section
that numerically covered the overlay region.

**Fix:** sort by address; prefer executable; prefer alloc; document the tie-break.
This is ~20 lines and it removes an entire class of per-project work.

### 4.2 The Ghidra handler snapshot is stale
The Java script embeds 656 handler names. The runtime actually has 658 unique
(121 syscall + 543 stub, 5 overlapping). Missing from the snapshot:
`GetOsdConfigParam2`, `SetOsdConfigParam2`.

**Fix:** generate the snapshot from `ps2_call_list.h` at build time.

---

## 5. Building the runtime for a Windows port

```powershell
cmake --build out/build --target ps2EntryRunner
```

Options that matter:

| Option | Default | Lodestone |
|---|---|---|
| `PS2X_ENABLE_DEBUG_UI` | ON | ON (need the panel) |
| `PS2X_ENABLE_AGRESSIVE_LOGS` | ON | OFF once triage works (upstream's spelling) |
| `PS2X_ENABLE_FFMPEG` | ON | Enables the `sceMpeg` HLE decoding backend; OFF in the diagnostic line above. RE4 SFD compatibility remains unverified. |
| `PS2X_IOP_BUILD_TESTS` | OFF | ON in CI |

Android builds are runtime-only, so `ps2xStudio` **cannot** be built there
(`ps2xRuntime` is added when `PS2X_BUILD_RUNTIME` is on, and Android forces
`PS2X_BUILD_STUDIO=OFF`).

---

## 6. Our own additions to the core (the actual work)

Everything above is configuration. These four are code we must write:

1. **Address-sorted section lookup** (§4.1). Do this first.
2. **`lodestone verify`** — external PCSX2 process, shared anchors, non-zero exit
   on divergence. GPL boundary: subprocess, never link.
3. **`lodestone triage`** — read the trace, classify the fault, propose a fix.
4. **Overlay loading** — RE4's 93 DVP overlays overwrite `.data` at runtime.
   SDBZ's `general.external_call_target_manifests` is the upstream mechanism for
   multi-binary recompilation and is the right model.

---

## 7. Citations

- `ran-j/PS2Recomp@main` — `CMakeLists.txt`, `ps2xRuntime/CMakeLists.txt`,
  `ps2xRecomp/src/lib/{config_manager,elf_parser,code_generator,
  instruction_translator,special_translator}.cpp`,
  `ps2xRecomp/include/ps2recomp/types.h`,
  `ps2xRecomp/tools/ghidra/ExportPS2Functions.java`,
  `ps2xRuntime/include/{ps2_call_list.h,game_overrides.h}`
- `hkmodd/ps2-recomp-Agent-SKILL` — `SKILL.md` §3–§4,
  `resources/03-ps2recomp-pipeline.md` §4
- `Red-tv141/DC2-PS2RECOMP` — `PS2_PROJECT_STATE.md`, `config_dc2_final.toml`
- `Scotho/socom-unzipped` — `docs/DEVELOPING.md`, `tools_py/`
- `dothacktranslate/dothack-recompilation` —
  `tools/scripts/build_mwo3_analysis_elf_v*.py`
- `TH3BACKLOG/SDBZ-Recomp` — `PS2_PROJECT_STATE.md`

# PlayStation 2 Static Recompilation: The Complete Architectural & Reverse-Engineering Encyclopedia
**Covering `urban-reign-recomp`, `ran-j/PS2Recomp`, `hkmodd/ps2-recomp-Agent-SKILL`, Deep Hardware Subsystems, and the `Resident Evil 4 (SLUS_211.34)` Porting Blueprint**

---

## Table of Contents
1. [Chapter 1: Theoretical Framework, Clean-Room Architecture & PS2 Hardware Topology](#chapter-1-theoretical-framework-clean-room-architecture--ps2-hardware-topology)
2. [Chapter 2: Case Study — `urban-reign-recomp` (`SLUS-21209`) End-to-End Architecture](#chapter-2-case-study--urban-reign-recomp-slus-21209-end-to-end-architecture)
3. [Chapter 3: The Open-Source PS2 Recompilation Toolchain & Libraries Encyclopedia](#chapter-3-the-open-source-ps2-recompilation-toolchain--libraries-encyclopedia)
4. [Chapter 4: Practical Engineering Guide — `ran-j/PS2Recomp` Step-by-Step Pipeline](#chapter-4-practical-engineering-guide--ran-jps2recomp-step-by-step-pipeline)
5. [Chapter 5: R5900 CPU Internals — `R5900Context`, Float Clamping & The 5 Hidden ISA Traps](#chapter-5-r5900-cpu-internals--r5900context-float-clamping--the-5-hidden-isa-traps)
6. [Chapter 6: Autonomous AI Reverse Engineering — `hkmodd/ps2-recomp-Agent-SKILL`](#chapter-6-autonomous-ai-reverse-engineering--hkmoddps2-recomp-agent-skill)
7. [Chapter 7: Deep Hardware Subsystems — `VU1`, `DMA`, `VIF1`, `GIF`, `SPU2`, `IPU` & `128MB` Expansion](#chapter-7-deep-hardware-subsystems--vu1-dma-vif1-gif-spu2-ipu--128mb-expansion)
8. [Chapter 8: OS Kernel, Cooperative `Win32 Fibers` & `SIF RPC` Callback Architecture](#chapter-8-os-kernel-cooperative-win32-fibers--sif-rpc-callback-architecture)
9. [Chapter 9: Advanced Tooling — Python VTable Scanner, Lockstep Trace Harness & CMake Chunking](#chapter-9-advanced-tooling--python-vtable-scanner-lockstep-trace-harness--cmake-chunking)
10. [Chapter 10: Target Blueprint — `Resident Evil 4 (SLUS_211.34)` & PS2 Scene Survey](#chapter-10-target-blueprint--resident-evil-4-slus_21134--ps2-scene-survey)

---

## Chapter 1: Theoretical Framework, Clean-Room Architecture & PS2 Hardware Topology

### 1.1 Architectural Taxonomy: Emulation vs. Decompilation vs. Static Recompilation

| Engineering Dimension | Dynamic Emulation (e.g., PCSX2) | Manual Decompilation (Matching Decomp) | Static Recompilation (AOT Binary Translation) |
| :--- | :--- | :--- | :--- |
| **Translation Timing** | At runtime via JIT (Just-In-Time) dynamic translation. | Offline manual human reverse engineering over years. | Ahead-of-Time (AOT) automated translation before build. |
| **CPU Execution Overhead** | High (JIT cache management, register mapping, MMU checks). | Zero (compiles directly to native host machine code). | Near-Zero (compiles generated C/C++ with `-O2`/`/O2` AVX2/SSE4.1). |
| **Engineering Time-to-Boot** | Immediate (if emulator supports hardware). | 2 to 5+ years of manual assembly matching. | Days to weeks using automated analyzers and AI triage. |
| **Code Modifiability** | Restricted to hex patches (`.pnach`) and memory hooks. | Unlimited (clean, human-readable C/C++ source code). | High (any function can be intercepted via `Game Overrides`). |
| **Native Feature Injection** | Limited by guest OS/hardware constraints. | Native 60+ FPS, ultrawide, ray tracing, custom netcode. | Native 60+ FPS, HD textures, expanded RAM (`128MB`), Lua mods. |

### 1.2 Legal Clean-Room Distribution Architecture
To remain 100% legal and immune to DMCA takedowns, modern static recompilation projects enforce a strict **Zero-Asset Clean-Room Pipeline**:
1. **No Copyrighted Binaries in Git:** Neither the original `.iso` nor the extracted `SLUS_xxx.xx` ELF binary—nor even the generated C++ files if the repo opts for client-side generation—are distributed in the public source tree.
2. **SHA-256 Verification Gate:** The build script (`build.py`) or launcher verifies the user's legally owned retail ISO/ELF via cryptographic hash before extracting or running.
3. **Runtime Asset Streaming:** At runtime, the native `.exe` mounts the retail `.iso` (or extracted folder) read-only to stream 3D models, textures, audio streams, and FMVs.

### 1.3 PlayStation 2 Hardware Architecture Overview
```text
+-----------------------------------------------------------------------------------+
|                        PLAYSTATION 2 MOTHERBOARD ARCHITECTURE                     |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +-------------------------------------+     +---------------------------------+  |
|  |     EMOTION ENGINE (MIPS R5900)     |     |   GRAPHICS SYNTHESIZER (GS)     |  |
|  |  - 294.912 MHz, 128-bit GPRs (x32)  |     |  - 147.456 MHz Fixed-Function   |  |
|  |  - Dual 64-bit Integer ALUs         |     |  - 4 MB Embedded eDRAM (VRAM)   |  |
|  |  - Dual Multiply/Divide (LO0/LO1)   |     |  - 2560-bit Wide Pixel Bus      |  |
|  |  - COP1 FPU (Non-IEEE 754 + ACC)    |     +----------------+----------------+  |
|  |  - 16 KB Scratchpad (0x70000000)    |                      ^                   |
|  +------+-----------------------+------+                      |                   |
|         | Coprocessor2          | 128-bit DMA Bus             | GIF Packet Stream |
|         v (Macro Mode)          v (10 Channels)               | (PATH1/PATH2/3)   |
|  +--------------+       +---------------+       +-------------+----------------+  |
|  |     VU0      |       |  32 MB RDRAM  |------>|   VU1 (Micro Mode) + VIF1    |  |
|  | 4KB Code/Data|       |  0x00000000   |       | 16KB Micro / 16KB Data + GIF |  |
|  +--------------+       +-------+-------+       +------------------------------+  |
|                                 |                                                 |
|                                 | SIF DMA / SIF RPC Bridge                        |
|                                 v                                                 |
|  +-----------------------------------------------------------------------------+  |
|  |               I/O PROCESSOR (IOP - MIPS R3000A @ 36.864 MHz)                |  |
|  |  - 2 MB IOP RAM, Executes Modular .IRX Drivers                              |  |
|  |  - Controls: SPU2 (48-ch ADPCM Audio), CDVD Drive, PADMAN, MTAPMAN, MCMAN   |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## Chapter 2: Case Study — `urban-reign-recomp` (`SLUS-21209`) End-to-End Architecture

### 2.1 Project Overview & Repository Layout (`thiagordsfx/urban-reign-recomp`)
`urban-reign-recomp` is a complete, production-ready static recompilation of Namco's 2005 brawler *Urban Reign* (USA release, `SLUS-21209`, executable `SLUS_212.09`) into a native 64-bit Windows application (`Urban Reign.exe`).
* **Language Breakdown:** `93.1% C++`, `3.5% Python`, `1.2% Java` (Ghidra export scripts), `1.0% CMake`, `1.0% C`.
* **Core Features:** Native 60 FPS (Progressive Scan) even in 8-fighter brawls, `1x` to `8x` internal resolution via transplanted `PCSX2 GS Renderer (DirectX 11)`, HD Texture Pack replacement (`game/textures/SLUS-21209/replacements`), PCSX2 `.pnach` mod support, up to 8-player local multiplayer via emulated Dual Multitap, and instant Save States (`F5` / `F9`).

```text
urban-reign-recomp/
├── .recomp.json          # Master metadata: target ELF hash, address ranges, compiler flags
├── CMakeLists.txt        # CMake build orchestration for runtime, renderer, and recomp code
├── build.py              # Interactive 3-step Python CLI builder (Extract -> Build -> Play)
├── docs/                 # Advanced architectural documentation and Sony SDK status map
├── game/                 # Runtime directory for user's retail .iso, mods (.pnach), and saves
├── recomp/               # Statically generated C++ files translated from SLUS_212.09 MIPS code
├── runtime/              # PS2 hardware abstraction layer (RDRAM, DMA, VIF, SIF, ps2xIOP)
├── src/                  # Game Overrides, Launcher UI, Input/Multitap, Save State engine
├── textures/             # Texture dumping and HD replacement hooks
├── thirdparty/           # PCSX2 GSdx (D3D11), SDL2, Dear ImGui, fmt, toml11, ELFIO
└── tools/                # Ghidra Java exporters, symbol scanners, and helper scripts
```

### 2.2 The 9-Stage Engineering Pipeline Used to Build `urban-reign-recomp`

#### Stage 1: ISO Mounting & ELF Extraction
The builder mounts the retail `Urban Reign (USA).iso` (`SLUS-21209`) using ISO9660 sector parsing, extracts `SLUS_212.09` and the `IOPRPxxx.IMG` / `.IRX` modules, and validates the binary hash.

#### Stage 2: Ghidra Static Analysis & Sony SDK Signature Matching
Because `SLUS_212.09` is a stripped retail binary (containing no symbol table), it is loaded into **Ghidra** with the `ghidra-emotionengine` language module.
1. `sce-symbol-scanner` matches byte-level instruction patterns against known Sony PS2 SDK libraries (`libkernel`, `libpad`, `libmtap`, `libcdvd`, `libsdr`, `libmc`, `libmpeg`).
2. A custom Java script (`ExportPS2Functions.java`) traverses the Control Flow Graph (CFG) to export all function boundaries (`start_vaddr`, `end_vaddr`), jump tables (`rodata` switch targets), and pointer references.

#### Stage 3: AOT Translation via `PS2Recomp`
The recompiler parses the ELF segments (`.text`, `.data`, `.rodata`, `.bss`, `.sdata`, `.sbss`) and translates every MIPS R5900 function into a C++ function accepting `(R5900Context& ctx, PS2Runtime* rt)`.

#### Stage 4: Branch Delay Slot & Indirect Jump Resolution
In MIPS, the instruction immediately following a branch or jump executes **before** the branch takes effect:
```mips
# Original MIPS R5900 Assembly in SLUS_212.09:
0x001A4200: bne   $a0, $zero, 0x001A4220
0x001A4204: addiu $v0, $a0, 1            # <-- Branch Delay Slot (Always executes!)
```
`PS2Recomp` lowers this safely by evaluating the branch condition into a temporary boolean, executing the delay slot instruction, and then branching:
```cpp
// Generated C++ Output:
bool cond_001A4200 = (ctx.r[4].u64[0] != 0);
ctx.r[2].s64[0] = static_cast<int64_t>(static_cast<int32_t>(ctx.r[4].u32[0] + 1)); // Delay slot
if (cond_001A4200) goto loc_001A4220;
```

#### Stage 5: Unified Flat Memory Map (`VirtToHost`)
The runtime allocates a contiguous `32 MB` buffer for Main RDRAM (`0x00000000 - 0x01FFFFFF`) and a `16 KB` buffer for the fast Scratchpad RAM (`0x70000000 - 0x70003FFF`).
```cpp
inline uint8_t* VirtToHost(uint8_t* rdram_base, uint8_t* scratch_base, uint32_t vaddr) {
    // Fast-path check for Scratchpad RAM (0x70000000 - 0x70003FFF)
    if ((vaddr & 0xFFFFC000U) == 0x70000000U) {
        return scratch_base + (vaddr & 0x3FFFU);
    }
    // Strip KSEG0 (0x80000000), KSEG1 (0xA0000000), and Uncached Accelerated (0x30000000) bits
    return rdram_base + (vaddr & 0x01FFFFFFU);
}
```

#### Stage 6: Sony SDK High-Level Emulation (HLE) & 8-Player Multitap Injection
Instead of recompiling Sony's low-level hardware polling loops inside `libpad` and `libmtap`, `urban-reign-recomp` intercepts them via `Game Overrides`:
* `sceMtapPortOpen`, `sceMtapGetConnection`: Intercepted to return `1` (Connected) for both controller ports, tricking the game into unlocking 8-player mode (`Port 0: Slots 0-3`, `Port 1: Slots 0-3`).
* `scePadRead`: Reads up to 8 modern XInput/SDL2 gamepads and writes the DualShock 2 button bitmasks and pressure-sensitive analog bytes directly into the guest DMA pad buffer in RDRAM.

#### Stage 7: `ps2xIOP` Subsystem & Audio Streaming
When the game sends `SIF RPC` commands to load `.IRX` modules or stream BGM/SFX from the ISO, `ps2xIOP` intercepts the `CDVD` sector requests and feeds ADPCM blocks to the SPU2 mixer without requiring a full BIOS boot.

#### Stage 8: Transplanting `PCSX2 GS Renderer (D3D11)` & 60 FPS Progressive Scan
* `DMA Channel 2 (GIF)` and `VIF1` packets are routed directly into a standalone build of PCSX2's hardware-accelerated DirectX 11 GS renderer.
* **The `GS_CSR.FIELD` VSync Fix:** Many PS2 games poll bit 13 (`FIELD`: Odd/Even interlace field) of the `GS_CSR` privileged register (`0x12001000`) to synchronize frame pacing. If `FIELD` does not toggle every `16.67ms`, the game hangs on a black screen. The runtime toggles `GS_CSR ^= (1 << 13)` on every `VBlank` interrupt and integrates Michael's **Force Progressive Scan** patch so the game renders full non-interlaced frames at a locked **60 FPS**.

#### Stage 9: Frame-Boundary Safe-Point Save States (`F5` / `F9`)
In a native C++ port, you cannot serialize the Windows `x86_64` CPU call stack to disk if the game is mid-execution inside nested functions.
* **The Engineering Solution:** When the user presses `F5`, the runtime sets an atomic `save_state_requested` flag. Execution continues until the main game thread hits the **Frame-Boundary Safe Point** (`sceGsSyncV` / `WaitSema` at the top of the main loop, where call stack depth is zero). At that exact instant, the runtime serializes:
  1. `32 MB` RDRAM + `16 KB` Scratchpad
  2. `R5900Context` registers for all active threads
  3. `4 MB` GS VRAM + privileged GS registers
  4. `SPU2` audio state and `IOP` file handles
  5. Compresses the snapshot with `LZ4`/`Zstd` to disk in under 50 milliseconds.

---

## Chapter 3: The Open-Source PS2 Recompilation Toolchain & Libraries Encyclopedia

| Tool / Library | Repository / Author | License | Exact Engineering Role in the Recompilation Pipeline |
| :--- | :--- | :--- | :--- |
| **`PS2Recomp`** | `ran-j/PS2Recomp` | MIT / GPLv3 | Core framework containing `ps2xAnalyzer`, `ps2xRecomp`, `ps2xRuntime`, and `ps2xIOP`. |
| **`ps2-recomp-Agent-SKILL`** | `hkmodd/ps2-recomp-Agent-SKILL` | Open Source | Autonomous AI reverse-engineering skill, cognitive guardrails, and 11 reference manuals. |
| **`Ghidra 11.4.2`** | `NationalSecurityAgency/ghidra` | Apache-2.0 | Reverse engineering suite used to disassemble ELFs, build CFGs, and recover jump tables. |
| **`ghidra-emotionengine`** | `beardypig` / `chaoticgd` | Apache-2.0 | Ghidra processor sleigh module adding 128-bit `MIPS R5900`, `MMI`, `VU0`, and `DMA` support. |
| **`GhydraMCP`** | `GhydraMCP` Extension | MIT | Model Context Protocol (MCP) server inside Ghidra (Port `8192`) for AI agent automation. |
| **`PCSX2-MCP`** | Custom PCSX2 DebugServer Build | GPL-3.0 | Instrumented PCSX2 build exposing live 128-bit registers and memory over Ports `21512` & `28011`. |
| **`PCSX2 GS Renderer`** | `PCSX2/pcsx2` (`GSdx`) | GPL-3.0 | Hardware-accelerated DirectX 11 / OpenGL / Vulkan Graphics Synthesizer backend. |
| **`paraLLEl-GS`** | `Themaister/parallel-gs` | MIT | Vulkan compute-shader GS renderer offering cycle-accurate hardware blending and post-processing. |
| **`sce-symbol-scanner`** | PS2 Recomp / OpenGOAL Scene | MIT | Pattern-matching scanner that identifies stripped Sony SDK library functions inside retail ELFs. |
| **`ELFIO`** | `serge1/ELFIO` | MIT | Header-only C++ library used to parse 32-bit MIPS ELF headers, sections, and relocations. |
| **`toml11` & `fmtlib`** | `ToruNiina/toml11` & `fmtlib/fmt` | MIT | Configuration parsing (`config.toml`) and high-speed C++ source code generation formatting. |
| **`Rabbitizer` & `Splat`** | `Decompollaborate` | MIT | MIPS instruction decoder and ROM/ELF splitter used in hybrid decomp/recomp workflows. |
| **`LLVM Clang-CL & Ninja`** | `llvm/llvm-project` | Apache-2.0 | Mandatory compiler/build system supporting `[[clang::musttail]]` and fast parallel builds. |

---

## Chapter 4: Practical Engineering Guide — `ran-j/PS2Recomp` Step-by-Step Pipeline

### 4.1 Architecture of `ran-j/PS2Recomp`
The framework is divided into four modular components:
1. **`ps2xAnalyzer`:** Inspects the input ELF, detects Sony SDK signatures, resolves basic block boundaries, and produces an initial `.toml` configuration file.
2. **`ps2xRecomp`:** Reads the ELF and `.toml` configuration, disassembles instructions, resolves jump tables, and emits C++ source files (`runner/*.cpp`) plus the function registration table.
3. **`ps2xRuntime`:** Provides the execution harness, memory management, `SYSCALL` dispatch, `DMA`/`VIF`/`GS` bridges, and the macro `PS2_REGISTER_GAME_OVERRIDE`.
4. **`ps2xIOP`:** Handles High-Level Emulation (HLE) of IOP `.IRX` modules (`CDVD`, `PADMAN`, `LIBSD`, `MCMAN`).

### 4.2 Step-by-Step Commands to Recompile Any PS2 Game from Scratch

#### Step 1: Clone and Build the Recompiler Toolchain (Using `Clang-CL` + `Ninja`)
```powershell
git clone --recursive [https://github.com/ran-j/PS2Recomp.git](https://github.com/ran-j/PS2Recomp.git)
cd PS2Recomp

# Configure using Ninja and Clang-CL (Mandatory for optimal compile times and tail-calls)
cmake -B build64 -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_C_COMPILER=clang-cl `
  -DCMAKE_CXX_COMPILER=clang-cl

cmake --build build64 --parallel
```

#### Step 2: Export Function Map & Jump Tables from Ghidra
1. Open your game's ELF (e.g., `SLUS_211.34`) in **Ghidra 11.4.2** with the `EmotionEngine` processor selected.
2. Run Auto-Analysis, then open **Script Manager** and run `ps2xRecomp/tools/ghidra/ExportPS2Functions.java`.
3. This exports `funcmap.csv` and jump table definitions.

#### Step 3: Create and Tune the Master Configuration File (`config.toml`)
```toml
[general]
game_name = "Resident_Evil_4_USA"
elf_path = "game/SLUS_211.34"
output_dir = "ps2xRuntime/src/runner"
single_file_output = false
functions_per_file = 250 # Prevents compiler OOM while keeping Ninja builds fast

[memory]
rdram_size = 0x02000000      # 32 MB standard (or 0x08000000 for 128 MB modded builds)
scratchpad_size = 0x00004000 # 16 KB fast memory at 0x70000000

# Explicitly force recompilation of indirect targets (C++ vtables, task callbacks)
entry_points = [
    "0x00100008", # _start
    "0x00100240", # main
    "0x001C2C70", # cPlayer damage / collision handler
    "0x001C1DD4"  # Virtual method target from vtable scan
]

# Functions to skip recompiling and replace with native C++ HLE handlers
[overrides]
"0x0028A100" = "HLE_sceSifBindRpc@0x0028A100"
"0x0028A240" = "HLE_sceSifCallRpc@0x0028A240"
"0x00291050" = "HLE_CRI_ADXT_GetStat@0x00291050"

# Recover switch/case jump tables (jr $reg) exported from Ghidra
[[jump_tables]]
address = "0x00145820" # Address of the 'jr $v0' instruction
register = "v0"
table_address = "0x00384100" # Base address in .rodata
num_entries = 18

# Binary instruction patches applied prior to C++ code generation
[[patches]]
address = "0x0027FF18"
value = 0x24020001 # addiu $v0, $zero, 1 (Force Progressive Scan 480p)
```

#### Step 4: Run `ps2_recomp` to Generate the C++ Codebase
```powershell
./build64/bin/ps2_recomp.exe --config config.toml
# Verify output count safely without listing 30,000 files in terminal:
(Get-ChildItem ps2xRuntime/src/runner -Filter *.cpp).Count
```

#### Step 5: Write Custom C++ Game Overrides (`game_overrides.cpp`)
```cpp
#include "ps2_runtime.h"
#include "ps2_game_overrides.h"
#include <cstdio>

namespace RE4Overrides {

    // Intercept a custom hardware polling function or middleware status check
    void HLE_CRI_ADXT_GetStat(R5900Context& ctx, PS2Runtime* rt) {
        uint32_t adxt_handle = ctx.r[4].u32[0]; // $a0: ADXT Handle pointer in RDRAM
        // Return status = 2 (ADXT_STAT_PLAYING / READY) in $v0 so the game never hangs waiting for IOP audio
        ctx.r[2].s64[0] = 2;
    }

    // Intercept main frame loop or specific game function
    void Hook_FrameTick(R5900Context& ctx, PS2Runtime* rt) {
        // Toggle GS_CSR FIELD bit (Bit 13) every frame to prevent VSync deadlock
        rt->gs().toggleFieldBit();
    }

    void RegisterAll(PS2Runtime& rt) {
        rt.bindAddressHandler(0x00291050, &HLE_CRI_ADXT_GetStat);
        rt.bindAddressHandler(0x00104500, &Hook_FrameTick);
    }
}

PS2_REGISTER_GAME_OVERRIDE("SLUS_211.34", RE4Overrides::RegisterAll);
```

### 4.3 Handling Dynamic Code: Overlays, Relocations & Self-Modifying Code (SMC)
1. **Dynamic Overlays (`.REL` / `.OVL` / Packed Modules):**
   Some PS2 games load stage-specific code modules from the ISO into a shared overlay region in RDRAM at runtime.
   * **Solution:** Extract all overlay binaries from the ISO ahead of time. Assign each overlay a unique virtual ID or non-overlapping synthetic base address in `PS2Recomp`, translate all of them into C++ functions, and hook `FlushCache(2)` (`Instruction Cache Flush`) or the game's overlay loader function to switch the active function pointer dispatch map in `runtime.callIndirect(ctx, vaddr)`.
2. **Packed ELFs & Self-Modifying Code (SMC):**
   If a retail ELF is compressed on disc (e.g., packer stub at `0x00100000` that unpacks the real game code into RAM and calls `FlushCache`), boot the game in **PCSX2**, wait until it reaches the title screen, dump the unpacked `32 MB` RDRAM (`0x00100000 - 0x01FFFFFF`), reconstruct an unpacked ELF header, and feed that clean unpacked binary into Ghidra and `PS2Recomp`.

---

## Chapter 5: R5900 CPU Internals — `R5900Context`, Float Clamping & The 5 Hidden ISA Traps

### 5.1 Complete `R5900Context` 128-bit Memory Layout
```cpp
#pragma once
#include <cstdint>
#include <immintrin.h>

// 16-byte aligned 128-bit register union matching the Toshiba MIPS R5900 Emotion Engine GPR
union alignas(16) Reg128 {
    uint8_t  u8[16];
    int8_t   s8[16];
    uint16_t u16[8];
    int16_t  s16[8];
    uint32_t u32[4];
    int32_t  s32[4];
    uint64_t u64[2];
    int64_t  s64[2];
    float    f32[4];
    __m128i  vec_i;
    __m128   vec_f;
};

struct alignas(64) R5900Context {
    Reg128   r[32];      // 32x 128-bit General Purpose Registers (r[0] wired to 0)
    uint64_t hi0, lo0;   // Pipeline 0 Multiply/Divide 64-bit results (MULT, DIV, MFHI, MFLO)
    uint64_t hi1, lo1;   // Pipeline 1 Multiply/Divide 64-bit results (MULT1, DIV1, MFHI1, MFLO1)
    uint32_t sa;         // Funnel Shift Amount register for QFSRV
    uint32_t pc;         // Current Program Counter

    // COP1 Single-Precision Floating-Point Unit (FPU)
    float    f[32];      // 32x 32-bit FPU registers ($f0..$f31)
    float    fpu_acc;    // Hidden R5900 FPU Accumulator register (ADDA.S, MULA.S, MADDA.S)
    uint32_t fcr31;      // FPU Control/Status condition bit register

    // COP2 Vector Unit 0 (VU0 Macro Mode)
    Reg128   vf[32];     // 32x 128-bit Vector Float registers ($vf0 = {0.0f, 0.0f, 0.0f, 1.0f})
    Reg128   vu0_acc;    // 128-bit VU0 Accumulator
    float    vu0_q;      // VU0 FDIV / SQRT quotient register
    float    vu0_p;      // VU0 EFU elementary function result register
    float    vu0_i;      // VU0 Immediate float register
    uint16_t vi[16];     // 16x 16-bit Vector Integer registers ($vi0 = 0)
    uint32_t vu0_mac_flags;
    uint32_t vu0_clip_flags;
};
```

### 5.2 Non-IEEE 754 Floating-Point Clamping (`NaN` / `Infinity` Saturation)
The PS2's `COP1` FPU and `VU0/VU1` units **do not support IEEE 754 `NaN` or `Infinity`**. Any exponent `0xFF` is interpreted as a normal finite floating-point number with magnitude up to `±3.4028235e+38` (`0x7FFFFFFF` / `0xFFFFFFFF`). On `x86_64`, dividing by zero or overflowing produces `Inf` or `NaN`, which propagates through camera and physics matrices and teleports characters out of bounds (`Black Screen / NaN Poisoning`).

```cpp
// 1. Call once at thread startup to enable hardware Flush-To-Zero and Denormals-Are-Zero:
inline void InitHostFPUMode() {
    _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_ON);
    _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_ON);
}

// 2. Branchless SSE4.1 Clamping function converting x86 NaN/Inf into PS2 clamped ±MAX_FLOAT:
inline float clamp_ps2_f32(float val) {
    uint32_t bits;
    std::memcpy(&bits, &val, sizeof(float));
    if ((bits & 0x7F800000U) == 0x7F800000U) {
        // Exponent is 0xFF (Inf or NaN on x86) -> Clamp mantissa to 0x7F7FFFFF preserving sign bit
        bits = (bits & 0x80000000U) | 0x7F7FFFFFU;
        std::memcpy(&val, &bits, sizeof(float));
    }
    return val;
}

// Vectorized 4-wide SIMD Clamping for VU0 / VU1 registers:
inline __m128 clamp_ps2_vec4(__m128 v) {
    const __m128 max_val = _mm_set1_ps(3.402823466e+38f);
    const __m128 min_val = _mm_set1_ps(-3.402823466e+38f);
    // Replace any NaN lanes with 0.0f, then clamp Inf to [min_val, max_val]
    __m128 valid_mask = _mm_cmpord_ps(v, v);
    v = _mm_and_ps(v, valid_mask);
    return _mm_min_ps(_mm_max_ps(v, min_val), max_val);
}
```

### 5.3 The 5 Hidden R5900 ISA Traps (Complete C++ Implementations)

#### Trap 1: The Second Multiplier Pipeline (`MULT1`, `DIV1`, `MADD1`, `MFHI1`, `MFLO1`)
Unlike standard MIPS, the R5900 has a second independent multiply/divide unit (`HI1/LO1`) AND writes the 32-bit product directly into `$rd` as well as `LO1/HI1`:
```cpp
inline void op_MULT1(R5900Context& ctx, int rd, int rs, int rt) {
    int64_t prod = static_cast<int64_t>(ctx.r[rs].s32[0]) * static_cast<int64_t>(ctx.r[rt].s32[0]);
    ctx.lo1 = static_cast<int64_t>(static_cast<int32_t>(prod & 0xFFFFFFFFULL));
    ctx.hi1 = static_cast<int64_t>(static_cast<int32_t>(prod >> 32));
    if (rd != 0) ctx.r[rd].s64[0] = ctx.lo1;
}

inline void op_MADD1(R5900Context& ctx, int rd, int rs, int rt) {
    int64_t acc = (static_cast<int64_t>(ctx.hi1 & 0xFFFFFFFFULL) << 32) | (ctx.lo1 & 0xFFFFFFFFULL);
    int64_t prod = acc + (static_cast<int64_t>(ctx.r[rs].s32[0]) * static_cast<int64_t>(ctx.r[rt].s32[0]));
    ctx.lo1 = static_cast<int64_t>(static_cast<int32_t>(prod & 0xFFFFFFFFULL));
    ctx.hi1 = static_cast<int64_t>(static_cast<int32_t>(prod >> 32));
    if (rd != 0) ctx.r[rd].s64[0] = ctx.lo1;
}
```

#### Trap 2: Mandatory 32-to-64-Bit Sign Extension on 32-Bit Ops
Every 32-bit arithmetic or load instruction (`ADDU`, `SUBU`, `ADDIU`, `SLL`, `LW`, `LH`, `LB`) **must sign-extend bit 31 into bits 32..63** because branch instructions (`BNE`, `BEQ`, `SLT`) compare the full 64-bit register `s64[0]`:
```cpp
// Correct implementation of ADDU $rd, $rs, $rt on R5900:
inline void op_ADDU(R5900Context& ctx, int rd, int rs, int rt) {
    if (rd == 0) return;
    uint32_t res = ctx.r[rs].u32[0] + ctx.r[rt].u32[0];
    ctx.r[rd].s64[0] = static_cast<int64_t>(static_cast<int32_t>(res)); // Mandatory Sign-Extend!
}
```

#### Trap 3: Unaligned Memory Access Pairs (`LWL`/`LWR` & `SWL`/`SWR`)
Used heavily by archive unpackers (`.AFS` in *Resident Evil 4*) and `memcpy`:
```cpp
inline void op_LWL(R5900Context& ctx, uint8_t* rdram, uint8_t* scratch, int rt, uint32_t addr) {
    uint32_t aligned = addr & ~3U;
    uint32_t shift   = (addr & 3U) * 8;
    uint32_t word    = *reinterpret_cast<uint32_t*>(VirtToHost(rdram, scratch, aligned));
    uint32_t mask    = 0x00FFFFFFU >> shift;
    uint32_t merged  = (ctx.r[rt].u32[0] & mask) | (word << (24 - shift));
    ctx.r[rt].s64[0] = static_cast<int64_t>(static_cast<int32_t>(merged));
}

inline void op_LWR(R5900Context& ctx, uint8_t* rdram, uint8_t* scratch, int rt, uint32_t addr) {
    uint32_t aligned = addr & ~3U;
    uint32_t shift   = (addr & 3U) * 8;
    uint32_t word    = *reinterpret_cast<uint32_t*>(VirtToHost(rdram, scratch, aligned));
    uint32_t mask    = 0xFFFFFF00U << (24 - shift);
    uint32_t merged  = (ctx.r[rt].u32[0] & mask) | (word >> shift);
    ctx.r[rt].s64[0] = static_cast<int64_t>(static_cast<int32_t>(merged));
}

inline void op_SWL(R5900Context& ctx, uint8_t* rdram, uint8_t* scratch, int rt, uint32_t addr) {
    uint32_t aligned = addr & ~3U;
    uint32_t shift   = (addr & 3U) * 8;
    uint32_t* ptr    = reinterpret_cast<uint32_t*>(VirtToHost(rdram, scratch, aligned));
    uint32_t mask    = 0xFFFFFF00U << shift;
    *ptr = (*ptr & mask) | (ctx.r[rt].u32[0] >> (24 - shift));
}

inline void op_SWR(R5900Context& ctx, uint8_t* rdram, uint8_t* scratch, int rt, uint32_t addr) {
    uint32_t aligned = addr & ~3U;
    uint32_t shift   = (addr & 3U) * 8;
    uint32_t* ptr    = reinterpret_cast<uint32_t*>(VirtToHost(rdram, scratch, aligned));
    uint32_t mask    = 0x00FFFFFFU >> (24 - shift);
    *ptr = (*ptr & mask) | (ctx.r[rt].u32[0] << shift);
}
```

#### Trap 4: 128-Bit Funnel Shift (`QFSRV`) & `SA` Register
```cpp
inline void op_QFSRV(R5900Context& ctx, int rd, int rs, int rt) {
    if (rd == 0) return;
    uint32_t bit_shift = ctx.sa & 0x7F;
    uint32_t byte_shift = bit_shift >> 3;
    alignas(16) uint8_t concat[32];
    std::memcpy(concat,      &ctx.r[rt], 16);
    std::memcpy(concat + 16, &ctx.r[rs], 16);
    std::memcpy(&ctx.r[rd],  concat + byte_shift, 16);
}
```

#### Trap 5: Hidden FPU Accumulator (`MULA.S`, `MADDA.S`, `MADD.S`)
```cpp
inline void op_MULAS(R5900Context& ctx, int fs, int ft) {
    ctx.fpu_acc = clamp_ps2_f32(ctx.f[fs] * ctx.f[ft]);
}
inline void op_MADDAS(R5900Context& ctx, int fs, int ft) {
    ctx.fpu_acc = clamp_ps2_f32(ctx.fpu_acc + clamp_ps2_f32(ctx.f[fs] * ctx.f[ft]));
}
inline void op_MADDS(R5900Context& ctx, int fd, int fs, int ft) {
    ctx.f[fd] = clamp_ps2_f32(ctx.fpu_acc + clamp_ps2_f32(ctx.f[fs] * ctx.f[ft]));
}
```

---

## Chapter 6: Autonomous AI Reverse Engineering — `hkmodd/ps2-recomp-Agent-SKILL`

### 6.1 Architectural Purpose
`hkmodd/ps2-recomp-Agent-SKILL` is an autonomous cognitive architecture and domain-expert skill designed for agentic IDEs (**Claude Code**, **Cursor**, **Antigravity**, **OpenCode**). It links the LLM directly to **Ghidra**, **PCSX2**, and the **CMake/Ninja** build pipeline via MCP servers so the AI acts as an autonomous reverse engineer.

### 6.2 Complete Map of the 11 Reference Modules (`resources/`)
| File Name | Engineering Scope | Mandatory Trigger Condition |
| :--- | :--- | :--- |
| **`SKILL.md`** | Master constitution, Boot Sequence (Phases A–C), MCP commands, and safety laws. | Read at the start of every session. |
| **`01-mips-r5900-isa.md`** | 128-bit GPRs, `MMI` instructions, branch delay slots, and `COP1`/`VU0` macro ops. | On unhandled opcodes or assembly verification. |
| **`02-ps2-hardware-architecture.md`** | Physical/Virtual memory maps, 10 `DMA` channels, `GIF`, `VIF1`, `SIF`. | When debugging hardware register I/O or DMA hangs. |
| **`03-ps2recomp-pipeline.md`** | `ps2_analyzer`, `ps2_recomp` CLI flags, `game.toml` schema, code emitter internals. | **Mandatory during Boot Phase B.** |
| **`04-runtime-syscalls-stubs.md`** | `ps2xRuntime` execution loop, syscall dispatch, writing HLE stubs & overrides. | **Mandatory during Boot Phase B.** |
| **`05-ghidra-ghydramcp-guide.md`** | Querying `GhydraMCP` (Port `8192`), decompiling functions, recovering jump tables. | During static function analysis. |
| **`06-game-porting-playbook.md`** | Unknown `sub_xxx` inference methodology, **Dynamic Probing (Empirical Telemetry)**. | During Cold Boot Triage (`Phase 4`). |
| **`07-ps2-code-patterns.md`** | Common compiler idioms: DMA tag builders, SIF RPC loops, VSync polling. | When diagnosing infinite loops or stalls. |
| **`08-infinite-knowledge-base.md`** | Master index routing queries to exact sections of `09-ps2tek.md`. | Before querying hardware edge cases. |
| **`09-ps2tek.md`** | Complete 230KB PS2 Hardware Technical Reference Manual (every register & bitfield). | When Circuit Breaker trips or hardware spec is needed. |
| **`10-agent-guardrails.md`** | AI Error Taxonomy, **Adversarial Split**, **Verification Ladder**, **Circuit Breakers**. | **Mandatory before writing any C++ fix.** |
| **`11-operational-phases.md`** | End-to-end state machine from `Phase 0` to `Phase 5` with entry/exit gates. | When transitioning project milestones. |

### 6.3 Exact MCP Server Configuration (`mcp_config.json`)
* **`GhydraMCP` Port:** `8192` (SSE endpoint inside Ghidra 11.4.2 CodeBrowser).
* **`PCSX2-MCP` Ports:** `21512` (DebugServer socket for 128-bit register inspection & breakpoints) and `28011` (Pine IPC).

```json
{
  "mcpServers": {
    "ghydramcp": {
      "url": "[http://127.0.0.1:8192/sse](http://127.0.0.1:8192/sse)"
    },
    "pcsx2-debug": {
      "command": "python",
      "args": ["tools/pcsx2_mcp_bridge.py", "--debug-port", "21512", "--pine-port", "28011"]
    }
  }
}
```

### 6.4 Cognitive Guardrails & Anti-Hallucination Laws
1. **The `runner/` Directory Crash Trap Protection:**
   `ps2xRuntime/src/runner/` contains up to **30,000+ generated `.cpp` files**. Running `ls`, `dir`, `find`, or file-tree indexing inside `runner/` will instantly overflow and crash the AI agent's context window. The agent is strictly restricted to running only:
   ```powershell
   Test-Path ps2xRuntime/src/runner
   (Get-ChildItem ps2xRuntime/src/runner -Filter *.cpp).Count
   ```
2. **External Hippocampus (`PS2_PROJECT_STATE.md`):**
   Every discovered function address, hooked syscall, register telemetry log, and failed hypothesis is committed to `PS2_PROJECT_STATE.md` in the workspace root so new chat sessions resume with zero context loss.
3. **3-Strike Circuit Breaker & Adversarial Split:**
   If a fix fails 3 times in a row, the agent is forbidden from guessing a 4th time. It must halt, perform an **Adversarial Split** (arguing against its own hypothesis using assembly evidence), and deploy **Dynamic Probing** (comparing live register values at `0xADDRESS` in `PCSX2-MCP` against the recompiled binary).

### 6.5 Universal Copy-Paste Starter Prompt
```text
Read the skill file `ps2-recomp-Agent-SKILL/SKILL.md` and BOTH boot sequence references (`resources/03-ps2recomp-pipeline.md` and `resources/04-runtime-syscalls-stubs.md`). Do NOT proceed until you have read all three files. Then execute this startup sequence:
1. INSPECT my workspace. Look for:
   - Any `PS2_PROJECT_STATE.md` (persistent memory from a previous session)
   - Any build directory (`build64/`, `build/`, etc.)
   - Any `game.toml` or ELF files (e.g., `SLUS_211.34`)
   DANGER: Do NOT list or search inside `runner/` directories! They contain 30,000+ files and WILL crash you. Instead use:
   Test-Path ps2xRuntime/src/runner
   (Get-ChildItem ps2xRuntime/src/runner -Filter *.cpp).Count
2. If a build directory exists, READ `CMakeCache.txt` and report Generator (Ninja?), Compiler (clang-cl?), and Build Type.
3. REPORT what phase we are in and the next concrete engineering step.
```

---

## Chapter 7: Deep Hardware Subsystems — `VU1`, `DMA`, `VIF1`, `GIF`, `SPU2`, `IPU` & `128MB` Expansion

### 7.1 Solving the `VU1 Microcode` Problem (Dual-Issue 64-bit Vector Programs)
Unlike `VU0` (which runs in Macro Mode inline with `R5900` instructions), **`VU1`** is an independent vector processor with `16 KB` Micro Memory and `16 KB` Data Memory. Games upload `VU1` microprograms dynamically via `DMA Channel 1 (VIF1)` and trigger them via `MSCAL` / `MSCNT`. Every `VU1` instruction is **64 bits wide (Dual-Issue)**:
* **Upper 32-bit word:** Vector Floating-Point MAC (`VMUL`, `VMADD`, `VCLIP`).
* **Lower 32-bit word:** Load/Store (`LQ`, `SQ`), Integer/Branch (`IBNE`, `B`, `BAL`), Special (`FDIV`, `XGKICK`).

#### The Production Solution: Census-Driven Offline `VU1` Recompilation + Hybrid Fallback
Pioneered by `sal063` in **Ace Combat 5 Static Recompilation** (`vurecomp`):
1. **Record (`PS2_VU_CENSUS=1`):** At runtime, whenever the game executes `MSCAL`/`MSCNT`, the runtime hashes the active `16 KB` `VU1` Micro Memory using **64-bit FNV-1a**. If unseen, it dumps `vu1_prog_<HASH>.bin` and records the entry point in `manifest.json`.
2. **Offline Compile (`vurecomp`):** Translates each dumped `.bin` microprogram into native C/C++ SSE4.1/AVX2 functions (`ps2_vu1_progs.inc`).
3. **Hybrid Dispatch:** At runtime, `vu1_execute(ctx, entry_pc)` checks the FNV-1a hash table. If a precompiled native function exists, it runs at native speed; if an unrecorded microprogram is encountered, it seamlessly falls back to the `VU1` interpreter so the game never crashes:

```cpp
uint64_t HashVU1MicroMem(const uint8_t* micro_mem_16kb) {
    uint64_t hash = 14695981039346656037ULL;
    for (size_t i = 0; i < 16384; i += 8) {
        uint64_t word = *reinterpret_cast<const uint64_t*>(micro_mem_16kb + i);
        hash ^= word;
        hash *= 1099511628211ULL;
    }
    return hash;
}

void ExecuteVU1Program(VU1State& vu1, uint32_t start_pc) {
    uint64_t hash = HashVU1MicroMem(vu1.micro_mem);
    if (auto native_fn = LookupCompiledVU1Program(hash, start_pc)) {
        native_fn(vu1); // Ultra-fast compiled C/SSE4.1 path
    } else {
        InterpretVU1Program(vu1, start_pc); // 100% safe fallback interpreter
    }
}
```

### 7.2 `Source-Chain DMA` Engine & The Scratchpad Bit-31 Trap
The PS2's 10-channel DMA controller executes linked lists of **64-bit DMA Tags** (`QWC` in bits `0..15`, `ID` in bits `28..30`, `IRQ` in bit `31`, and `ADDR` in bits `32..62`).
* **Critical Hardware Quirk:** In `ADDR` (or `MADR`/`TADR`), **Bit 31 (`0x80000000`) indicates that the DMA transfer is reading from or writing to the `16 KB Scratchpad (0x70000000)`**, NOT KSEG0!

```cpp
inline uint8_t* ResolveDMAPointer(uint8_t* rdram, uint8_t* scratch, uint32_t dma_addr) {
    if ((dma_addr & 0x80000000U) != 0 || (dma_addr & 0x70000000U) == 0x70000000U) {
        return scratch + (dma_addr & 0x3FFFU);
    }
    return rdram + (dma_addr & 0x01FFFFFFU);
}

void ProcessDMASourceChain(DMAChannel& ch, uint8_t* rdram, uint8_t* scratch, SubsystemFunc consumer) {
    uint32_t call_stack[2] = {0, 0};
    int sp = 0;
    bool end_chain = false;

    while (!end_chain) {
        uint64_t* tag_ptr = reinterpret_cast<uint64_t*>(ResolveDMAPointer(rdram, scratch, ch.tadr));
        uint64_t tag  = *tag_ptr;
        uint32_t qwc  = tag & 0xFFFFU;
        uint32_t id   = (tag >> 28) & 0x7U;
        bool     irq  = ((tag >> 31) & 0x1U) != 0;
        uint32_t addr = static_cast<uint32_t>((tag >> 32) & 0xFFFFFFFFU);

        // If TTE (Tag Transfer Enable) is set on VIF1/GIF, forward the upper 64 bits of the 128-bit tag quadword
        if (ch.chcr_tte()) consumer(reinterpret_cast<uint8_t*>(tag_ptr) + 8, 8);

        switch (id) {
            case 0: // REFE: Transfer QWC from ADDR, then end chain
                consumer(ResolveDMAPointer(rdram, scratch, addr), qwc * 16);
                ch.tadr += 16;
                end_chain = true;
                break;
            case 1: // CNT: Transfer QWC immediately following the tag
                consumer(ResolveDMAPointer(rdram, scratch, ch.tadr + 16), qwc * 16);
                ch.tadr = ch.tadr + 16 + (qwc * 16);
                break;
            case 2: // NEXT: Transfer QWC following tag, next TADR = ADDR
                consumer(ResolveDMAPointer(rdram, scratch, ch.tadr + 16), qwc * 16);
                ch.tadr = addr;
                break;
            case 3: // REF: Transfer QWC from ADDR, next TADR = TADR + 16
            case 4: // REFS: Same as REF with stall control
                consumer(ResolveDMAPointer(rdram, scratch, addr), qwc * 16);
                ch.tadr += 16;
                break;
            case 5: // CALL: Transfer QWC following tag, push return address, jump to ADDR
                consumer(ResolveDMAPointer(rdram, scratch, ch.tadr + 16), qwc * 16);
                if (sp < 2) call_stack[sp++] = ch.tadr + 16 + (qwc * 16);
                ch.tadr = addr;
                break;
            case 6: // RET: Transfer QWC following tag, pop TADR (or end if stack empty)
                consumer(ResolveDMAPointer(rdram, scratch, ch.tadr + 16), qwc * 16);
                if (sp > 0) ch.tadr = call_stack[--sp];
                else end_chain = true;
                break;
            case 7: // END: Transfer QWC following tag and terminate chain
                consumer(ResolveDMAPointer(rdram, scratch, ch.tadr + 16), qwc * 16);
                end_chain = true;
                break;
        }
        if (irq && ch.chcr_tie()) end_chain = true;
    }
    ch.clear_str_busy(); // Clear CHCR.STR (Bit 8) and trigger DMAC interrupt
}
```

### 7.3 `VIF1 UNPACK` Geometry Decompression & `GIF` Paths (`PATH1` / `PATH2` / `PATH3`)
1. **`VIF1 UNPACK` (`CMD 0x60..0x7F`):** Games compress 3D vertex positions and normals on disc as 8-bit (`V4-8`, `V3-8`) or 16-bit (`V3-16`, `V4-16`) integers. The `VIF1` state machine reads the `STCYCL` (`CL`/`WL`), `OFFSET`, `BASE`, and `ITOP` registers, expands the compressed integers into 128-bit quadwords (applying `USN` unsigned/signed extension and `FLG` `TOPS` double-buffering offset), and writes them directly into `VU1 Data Memory`.
2. **`GIF` Arbiter (`PATH1`, `PATH2`, `PATH3`) & `128-bit GIFTag`:**
   ```cpp
   struct GIFTag128 {
       uint64_t lo, hi;
       uint32_t nloop() const { return lo & 0x7FFFULL; }
       bool     eop()   const { return (lo >> 15) & 1ULL; }
       bool     pre()   const { return (lo >> 46) & 1ULL; }
       uint32_t prim()  const { return (lo >> 47) & 0x7FFULL; }
       uint32_t flg()   const { return (lo >> 58) & 0x3ULL; } // 0=PACKED, 1=REGLIST, 2=IMAGE
       uint32_t nreg()  const { uint32_t n = (lo >> 60) & 0xFULL; return n ? n : 16; }
       uint8_t  reg(int i) const { return (hi >> (i * 4)) & 0xFULL; }
   };
   ```

### 7.4 Tail-Call Elimination (`[[clang::musttail]]`) & The `128MB` Pointer Bit-Packing Trap
1. **Preventing Host Stack Overflow (`0xC00000FD`):**
   Compilers optimize MIPS functions using sibling tail-calls (`j target_func` instead of `jal`). If translated as normal C++ function calls, recursive state machines overflow the Windows stack. Enforce tail-call elimination with identical signatures:
   ```cpp
   #if defined(__clang__)
     #define PS2_TAILCALL [[clang::musttail]] return
   #elif defined(__GNUC__) && (__GNUC__ >= 15)
     #define PS2_TAILCALL [[gnu::musttail]] return
   #else
     #error "Use Clang-CL or GCC 15+ to guarantee tail-call optimization!"
   #endif

   void sub_001A2000(R5900Context& ctx, PS2Runtime* rt) {
       // ... delay slot execution ...
       PS2_TAILCALL sub_001A2450(ctx, rt); // Compiles to 'jmp', zero stack growth!
   }
   ```
2. **The `128MB` Memory Expansion Trap (`0x01FFFFFF` vs `0x07FFFFFF`):**
   When expanding RDRAM from `32 MB` to `128 MB` for heavy modding, never blindly replace every `0x01FFFFFF` mask in the game's code. Keep the game's original heap inside the lower `32 MB` (`0x00000000 - 0x01FFFFFF`) so legacy pointers that pack object flags into bits `25..27` continue to work, and allocate a dedicated **Extended High-Memory Arena (`0x02000000 - 0x07FFFFFF`)** managed by your custom C++ loader hooks!

---

## Chapter 8: OS Kernel, Cooperative `Win32 Fibers` & `SIF RPC` Callback Architecture

### 8.1 Complete Sony EE Kernel `SYSCALL` Reference Table (Positive & Negative IDs)
When a game executes `SYSCALL`, register **`$v1` (`ctx.r[3].s32[0]`)** holds the syscall number. A **negative** number (e.g., `-0x43` / `0xFFFFFFBD`) indicates an **interrupt-safe `i*` syscall** (`iSignalSema`, `iWakeupThread`).

| `$v1` Hex ID | Sony EE Kernel Syscall | Exact Runtime Implementation Requirement |
| :--- | :--- | :--- |
| **`0x02`** | `SetGsCrt(interlace, mode, ffmd)` | Configures `PCSX2 GS` display mode (`NTSC=2`, `PAL=3`, `480p=0x50`). |
| **`0x10` / `0x11`** | `AddIntcHandler` / `RemoveIntcHandler` | Registers guest callback function for `INTC_GS (0)`, `INTC_VBLANK_S (2)`, `INTC_VBLANK_E (3)`. |
| **`0x12` / `0x13`** | `AddDmacHandler` / `RemoveDmacHandler` | Registers guest callback function triggered when a `DMA` channel finishes transfer. |
| **`0x20` / `0x22`** | `CreateThread` / `StartThread` | Allocates a `Win32 Fiber` with its own `R5900Context` and sets `pc = entry_func`, `$gp`, `$sp`. |
| **`0x2B` / `-0x2B`** | `RotateThreadReadyQueue(prio)` | Cooperatively yields execution to the next ready fiber at priority `prio`. |
| **`0x32`** | `SleepThread()` | If `wakeup_count > 0`, decrements it and returns immediately; otherwise suspends fiber. |
| **`0x33` / `-0x34`** | `WakeupThread` / `iWakeupThread` | If target thread is sleeping, moves it to `READY`; otherwise increments `wakeup_count++`! |
| **`0x40` / `0x41`** | `CreateSema` / `DeleteSema` | Allocates kernel semaphore with `init_count` and `max_count`. |
| **`0x42` / `-0x43`** | `SignalSema` / `iSignalSema` | Increments semaphore count or wakes the highest-priority waiting thread fiber. |
| **`0x44` / `0x45`** | `WaitSema` / `PollSema` | `WaitSema` blocks and switches fibers if `count == 0`; `PollSema` returns `-1` immediately if `0`. |
| **`0x64` / `-0x64`** | `FlushCache(mode)` | `mode=0` (Data cache writeback), `mode=2` (Instruction cache invalidate — check for overlays!). |
| **`0x77` / `-0x77`** | `sceSifSetDma` / `isceSifSetDma` | Processes an array of `SifDmaTransfer_t` structs from EE RDRAM to IOP RAM and triggers SIF RPC. |

### 8.2 Cooperative Thread Scheduling via `Win32 Fibers`
```cpp
#include <windows.h>
#include <vector>

struct EEThread {
    int          thid;
    int          status;       // 1=RUN, 2=READY, 4=WAIT, 8=SUSPEND, 16=DORMANT
    int          priority;
    int          wakeup_count; // Crucial: prevents lost wakeups before SleepThread()
    int          wait_sema_id;
    LPVOID       fiber_handle;
    R5900Context ctx;
};

class EEScheduler {
public:
    void SleepCurrentThread() {
        EEThread& cur = threads_[current_tid_];
        if (cur.wakeup_count > 0) {
            cur.wakeup_count--;
            return; // Do not sleep! An interrupt already signaled wakeup.
        }
        cur.status = 4; // THS_WAIT
        SwitchToNextReadyFiber();
    }

    void WakeupThread(int target_tid) {
        EEThread& target = threads_[target_tid];
        if (target.status == 4) {
            target.status = 2; // THS_READY
        } else {
            target.wakeup_count++; // Buffer the wakeup!
        }
    }

    void SwitchToNextReadyFiber() {
        int next_tid = PickHighestPriorityReadyThread();
        if (next_tid != current_tid_) {
            current_tid_ = next_tid;
            threads_[current_tid_].status = 1; // THS_RUN
            SwitchToFiber(threads_[current_tid_].fiber_handle);
        }
    }
private:
    int current_tid_ = 0;
    std::vector<EEThread> threads_;
    int PickHighestPriorityReadyThread();
};
```

### 8.3 `SIF RPC` Interception & Mandatory Completion Callback Execution
When intercepting `sceSifCallRpc`, you **must** invoke the guest `end_func` callback passed in `$t3` (`ctx.r[11]`), because games use `end_func` to set a flag or signal a semaphore indicating the async IOP operation completed:
```cpp
void HLE_sceSifCallRpc(R5900Context& ctx, PS2Runtime* rt) {
    uint32_t client_ptr = ctx.r[4].u32[0];  // $a0: SifRpcClientData_t*
    uint32_t rpc_num    = ctx.r[5].u32[0];  // $a1: RPC Function ID
    uint32_t mode       = ctx.r[6].u32[0];  // $a2: Mode (0=Blocking, 1=Non-Blocking)
    uint32_t send_buf   = ctx.r[7].u32[0];  // $a3: Send buffer vaddr
    uint32_t send_size  = ctx.r[8].u32[0];  // $t0: Send size
    uint32_t recv_buf   = ctx.r[9].u32[0];  // $t1: Recv buffer vaddr
    uint32_t recv_size  = ctx.r[10].u32[0]; // $t2: Recv size
    uint32_t end_func   = ctx.r[11].u32[0]; // $t3: Guest completion callback vaddr
    uint32_t end_param  = *reinterpret_cast<uint32_t*>(rt->VirtToHost(ctx.r[29].u32[0] + 16));

    uint32_t server_id = *reinterpret_cast<uint32_t*>(rt->VirtToHost(client_ptr + 0x24));

    // Execute HLE service (e.g., CDVD, PADMAN, LIBSD, or CRI ADXT/AFS)
    rt->iop().dispatchRpc(server_id, rpc_num,
                          rt->VirtToHost(send_buf), send_size,
                          rt->VirtToHost(recv_buf), recv_size);

    // Crucial: Invoke guest completion callback if provided!
    if (end_func != 0) {
        uint64_t saved_a0 = ctx.r[4].u64[0];
        ctx.r[4].s64[0] = static_cast<int32_t>(end_param);
        rt->callIndirect(ctx, end_func);
        ctx.r[4].u64[0] = saved_a0;
    }
    ctx.r[2].s64[0] = 0; // Return 0 (Success)
}
```

---

## Chapter 9: Advanced Tooling — Python VTable Scanner, Lockstep Trace Harness & CMake Chunking

### 9.1 Standalone Python `ELF VTable & Function Pointer Scanner`
Heavily object-oriented C++ PS2 games (such as **Resident Evil 4**) store up to 40% of their functions inside `vtables` and task dispatch tables in `.rodata` and `.data`. Run this script on any PS2 ELF to extract all hidden function entry points into `vtable_entrypoints.toml`:

```python
#!/usr/bin/env python3
import struct
import sys

def scan_elf_function_pointers(elf_path: str, text_min: int = 0x00100000, text_max: int = 0x00400000):
    with open(elf_path, "rb") as f:
        data = f.read()

    if data[:4] != b"\x7fELF":
        raise ValueError("Not a valid ELF binary!")

    e_phoff = struct.unpack_from("<I", * + 0x1C)[0] 0x2A)[0] 0x2C)[0] 1 <6I"," <H"," and data, e_phentsize e_phnum="struct.unpack_from(" for i if in off="e_phoff" off) p_filesz p_filesz, p_memsz="struct.unpack_from(" p_offset, p_paddr, p_type="=" p_type, p_vaddr, range(e_phnum): segments="[]"> 0: # PT_LOAD
            segments.append((p_vaddr, data[p_offset : p_offset + p_filesz]))

    def read_u32(vaddr: int):
        for base, buf in segments:
            if base <= vaddr <= base + len(buf) - 4:
                return struct.unpack_from("<I", - None base)[0] buf, def int) is_mips_function_prologue(insn: return vaddr> bool:
        if insn is None:
            return False
        # 1. addiu $sp, $sp, -frame_size (0x27BD8000..0x27BDFFFF)
        if (insn & 0xFFFF8000) == 0x27BD8000:
            return True
        # 2. sd $ra, offset($sp) (0xFFBFxxxx) or sw $ra, offset($sp) (0xAFBFxxxx) or sq $ra (0x7FBFxxxx)
        if (insn & 0xFFFF0000) in (0xFFBF0000, 0xAFBF0000, 0x7FBF0000):
            return True
        # 3. Leaf getter/stub starting with lui $v0/$v1/$a0 or immediate jr $ra (0x03E00008)
        if insn == 0x03E00008 or (insn & 0xFFE00000) == 0x3C000000:
            return True
        return False

    candidates = set()
    for base, buf in segments:
        for rel in range(0, len(buf) - 4, 4):
            ptr = struct.unpack_from("<I", "0x{addr:08X}",\n') "__main__": "w", & (ptr ) )" 0: 3)="=" < Auto-generated C++ Found __name__="=" addr and as buf, callback candidates.add(ptr) encoding="utf-8" entry for function if in is_mips_function_prologue(read_u32(ptr)): len(sys.argv) open("vtable_entrypoints.toml", out.write("# out.write("]\n") out.write(f' out: pointer points\nentry_points="[\n" print(f"[+] rel)[0] sorted(candidates): target="sys.argv[1]" targets text_max text_min valid vtable with {elf_path}") {len(candidates)}> 1 else "SLUS_211.34"
    scan_elf_function_pointers(target)
```

### 9.2 Differential Lockstep Trace Harness (`A/B Register Checksum Logger`)
To isolate subtle math or pointer bugs across 10,000+ functions in minutes:
```cpp
inline uint64_t HashCPUState(const R5900Context& ctx) {
    uint64_t h = 14695981039346656037ULL;
    for (int i = 1; i < 32; ++i) {
        h = (h ^ ctx.r[i].u64[0]) * 1099511628211ULL;
        h = (h ^ ctx.r[i].u64[1]) * 1099511628211ULL;
    }
    for (int i = 0; i < 32; ++i) {
        uint32_t fb;
        std::memcpy(&fb, &ctx.f[i], 4);
        h = (h ^ fb) * 1099511628211ULL;
    }
    return h;
}
```
Log `[ENTER 0xADDR] HASH` and `[EXIT 0xADDR] HASH` for the first N frames and diff against `PCSX2-MCP`. The first function where `ENTER_HASH` matches PCSX2 but `EXIT_HASH` diverges is your exact bug location.

### 9.3 Optimal CMake Unity Chunking & Precompiled Headers (`PCH`)
```cmake
cmake_minimum_required(VERSION 3.24)
project(PS2RecompPort LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

file(GLOB RECOMP_CHUNKS CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/recomp/ps2_code_*.cpp")

add_executable(game_recomp
    src/main.cpp
    src/game_overrides.cpp
    ${RECOMP_CHUNKS}
)

# Precompile heavy headers once across all generated chunks (10x faster build)
target_precompile_headers(game_recomp PRIVATE
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/runtime/include/ps2_runtime.h>"
    <immintrin.h>
    <cstdint>
    <cstring>
)

target_compile_options(game_recomp PRIVATE
    /O2 /fp:fast /arch:AVX2
    -Wno-unused-variable -Wno-unused-label -Wno-parentheses-equality
)
```

---

## Chapter 10: Target Blueprint — `Resident Evil 4 (SLUS_211.34)` & PS2 Scene Survey

### 10.1 Forensic Profile of `Resident Evil 4` (USA v1.01 — `SLUS_211.34`)
* **Executable File:** `cdrom0:\SLUS_211.34;1`
* **Exact File Size:** `3,096,892 bytes` (`3.09 MB` Monolithic ELF — all core game, enemy AI, weapon, and room logic is statically linked into a single binary).
* **PCSX2 GameDB CRC:** `0x013E349D`
* **ELF Program Segment 0:** Loads at virtual address `0x00100000`, size `0x002C9F28` (`2.92 MB`).
* **Entry Point (`e_entry`):** `0x00100008`
* **Critical Header Quirk (`e_gp = 0x00000000`):** The ELF header records `$gp` as `0x00000000`. The true `$gp` value is initialized dynamically inside the first instructions at `0x00100008` (`_start`). Do **not** hardcode `$gp = 0`; let `_start` initialize `$gp` before jumping to `main`.

### 10.2 Known Memory Anchors & Patches in `SLUS_211.34`
| Address in `SLUS_211.34` | Engine Subsystem / Variable | Engineering Usage in Static Recompilation |
| :--- | :--- | :--- |
| **`0x00100008`** | `_start` (Entry Point) | Initializes `$gp`, `$sp`, clears `.bss`, and launches main thread. |
| **`0x0027FF18`** | Progressive Scan (`480p`) Gate | Patch instruction to `0x24020001` (`li $v0, 1`) to force native non-interlaced 480p output. |
| **`0x00431A5C`** | Frame Rate Limiter Divisor | Writing `0x00000001` unlocks **60 FPS**; trace all readers of `0x00431A5C` to fix delta-time physics! |
| **`0x0042DA78`** | `Global_Wk` / Leon Health Struct | Core global state structure holding player HP, coordinates, inventory, and room ID. |
| **`0x001C2C70` & `0x001C1DD4`** | Damage & Hitbox Routines | Anchor functions for mapping the `cPlayer` and `cEm` class hierarchies. |
| **`0x00430F66`** | Extra Modes Unlock Bitmask | Bitmask unlocking *Separate Ways*, *The Mercenaries*, *Assignment Ada*, and *Movie Browser*. |

### 10.3 Step-by-Step Boot Triage Plan for `Resident Evil 4 (SLUS_211.34)`
1. **Extract & Scan:** Extract `SLUS_211.34` from the USA ISO. Run the Python `scan_elf_function_pointers` script (Chapter 9.1) to capture all `cUnit` / `cModel` / `cEm` C++ virtual methods (`vtables`).
2. **Bypass CRI Middleware IOP Deadlocks (`CVFS` / `AFS` / `ADXT`):**
   * *Resident Evil 4* packs its assets inside `BIO4DAT.AFS`, `BIO4BGM.AFS`, `BIO4EVT.AFS`, and `BIO4MOV.AFS` using **CRI Middleware** (`CRI_ADXT.IRX`).
   * During cold boot, hook `sceSifBindRpc` and `sceSifCallRpc` to log the CRI RPC Server IDs, redirect sector reads directly to the `.AFS` files on the mounted ISO, and stub `ADXT_GetStat` to return `PLAYING/COMPLETED` so the game boots straight to the **CAPCOM** logo without waiting on IOP audio hardware.
3. **Bypass `.SFD` (CRI Sofdec MPEG-2) Cutscene Stalls:**
   * Hook the Sofdec player check (`MWPLY_GetStat` / `sceMpegGetPicture`) to either decode frames via `FFmpeg` or return `END_OF_STREAM` during early testing so pressing `New Game` jumps immediately into gameplay (`Stage r100` — Pueblo Village).

### 10.4 Comprehensive Survey of PlayStation 2 Recompilation & Decompilation Projects

| Game Title | Repository / Developer | Approach | Key Technical Milestones & Architecture |
| :--- | :--- | :--- | :--- |
| **Urban Reign** (`SLUS-21209`) | `thiagordsfx/urban-reign-recomp` | Static Recomp | **Released v1.0.0:** 60 FPS progressive scan, D3D11 PCSX2 GS, HD textures, 8-player Multitap, Save States. |
| **Ace Combat 5** (`SLUS-20851`) | `sal063/Ace-Combat-5-Static-recompilation` | Static Recomp | **Released v2.1:** 10,742 functions in 15s, `vurecomp` census VU1 compiler, native Vulkan 3D meshes, Lua 5.4 mods. |
| **DBZ: Budokai Tenkaichi 3** | `z3xox/BT3-Recomp` | Static Recomp | Recompiled dynamic `chr_s.pak` overlays, expanded RDRAM from `32MB` to `128MB` for 6-fighter (3v3) simultaneous battles. |
| **God of War** (`SCUS-97399`) | `KIexster/god-of-war-recomp` | Static Recomp | Built on `PS2Recomp`; 6,414 functions translated, custom `989NOMID.IRX` Screamer audio, `.PSS` FMVs, OpenGL GS. |
| **Dragon Quest VIII** | `Sinan-Karakaya/DQ8-Recompiled` | Static Recomp | Cross-platform target (`Windows`, `Linux`, `macOS`) translating Level-5's cel-shaded engine. |
| **ICO** | `nathanialf/ico-pc` | Source Port / Recomp | Playable (`v0.6.0`) across `Windows`, `Linux`, and `Android`. |
| **Ridge Racer V** | `danisandoval/fukami` | Static Recomp | Reached `v1.0.0` supporting `Linux` and `macOS`. |
| **Jak & Daxter Trilogy** | `open-goal/jak-project` | Custom Compiler | Full native PC ports of *Jak 1, 2, 3* via custom `OpenGOAL` (Lisp-to-x86-64) compiler. |
| **Ratchet & Clank 1, 2, 3** | `Lombyte`, `OpenRAC`, `vetusmagnus` | Decompilation | Active byte-matching decompilations and native Windows source port work (`ee-gcc 2.95.3`). |
| **Silent Hill 2 & 3** | `dreamingmoths/mirror-of-alessa` | Decompilation | Ongoing decompilation of Konami's survival horror engines (`mirror-of-alessa` & `memory-of-alessa`). |
| **Persona 4 & DDS 1/2** | `Raikaru` / `Megami-Decomps` | Decompilation | Active Atlus RPG decompilation projects recovering C/C++ source structures. |
# Architecture / Memory Map

Durable distillation of the PS2 reference corpus. Every address range below is quoted
verbatim from a source. Claims are tagged so you can tell measured fact from derivation.

| Tag | Meaning |
|-----|---------|
| `[doc:file]` | Quoted from that corpus file |
| `[code]` | Verified by reading this repo's runtime source |
| `[derived]` | Arithmetic/logic consequence of the above — not stated in any source |
| `[GAP]` | The four source files are silent or self-contradictory here |

Sources read in full for this note:
`resources/db-ps2-architecture.md`, `resources/db-memory-map.md`,
`resources/db-ps2-index.md`, `resources/db-vu-instructions.md`.

---

## Physical memory layout

All ranges as listed in `db-memory-map.md` §Physical Memory Layout (which describes the
layout "as modeled in ps2xRuntime"). Owner = the subsystem the range belongs to.

| Start | End | Size | Region | Owner / Runtime Handling |
|-------|-----|------|--------|-------------------------|
| `0x00000000` | `0x01FFFFFF` | 32 MB | **EE RDRAM** | `m_rdram[]` — main R/W memory |
| `0x10000000` | `0x10001FFF` | 8 KB | **EE Registers** | `m_ioRegisters{}` (see contradiction C5) |
| `0x10000000` | `0x10000FFF` | — | Timer registers | T0–T3 MODE/COUNT/COMP/HOLD |
| `0x10002000` | `0x10002030` | — | IPU registers | Write handler with IPU reset logic |
| `0x10003000` | `0x100030FF` | — | GIF registers | GIF_CTRL/MODE/STAT/TAG/CNT/P3CNT/P3TAG |
| `0x10003800` | `0x100039FF` | — | VIF0 registers | Store-only |
| `0x10003C00` | `0x10003DFF` | — | VIF1 registers | Full write handler for all VIF1 fields |
| `0x10004000` | `0x10004FFF` | — | VIF0 FIFO | 128-bit write FIFO for VIF0 |
| `0x10005000` | `0x10005FFF` | — | VIF1 FIFO | 128-bit write FIFO for VIF1 |
| `0x10006000` | `0x10006FFF` | — | GIF FIFO | 128-bit write FIFO for GIF PATH3 |
| `0x10007000` | `0x10007FFF` | — | IPU out FIFO | Read-back from IPU decode |
| `0x10008000` | `0x10008FFF` | — | DMA ch0 (VIF0) | D0_CHCR/MADR/QWC/TADR at +0x00/+0x10/+0x20/+0x30 |
| `0x10009000` | `0x10009FFF` | — | DMA ch1 (VIF1) | D1_CHCR/MADR/QWC/TADR |
| `0x1000A000` | `0x1000AFFF` | — | DMA ch2 (GIF) | D2_CHCR/MADR/QWC/TADR |
| `0x1000B000` | `0x1000B3FF` | — | DMA ch3 (IPU from) | D3_CHCR/MADR/QWC |
| `0x1000B400` | `0x1000B7FF` | — | DMA ch4 (IPU to) | D4_CHCR/MADR/QWC/TADR |
| `0x1000C000` | `0x1000CFFF` | — | DMA ch5 (SIF0) | D5_CHCR/MADR/QWC |
| `0x1000C400` | `0x1000C7FF` | — | DMA ch6 (SIF1) | D6_CHCR/MADR/QWC/TADR |
| `0x1000C800` | `0x1000CBFF` | — | DMA ch7 (SIF2) | D7_CHCR/MADR/QWC |
| `0x1000D000` | `0x1000D3FF` | — | DMA ch8 (SPR from) | D8_CHCR/MADR/QWC/SADR |
| `0x1000D400` | `0x1000D7FF` | — | DMA ch9 (SPR to) | D9_CHCR/MADR/QWC/TADR/SADR |
| `0x1000E000` | `0x1000E0FF` | — | DMAC global | D_CTRL, D_STAT with W1C/toggle logic |
| `0x1000F000` | `0x1000F010` | — | INTC | Interrupt controller (STAT, MASK) |
| `0x1000F200` | `0x1000F260` | — | SIF registers | SIF_SMFLG/CTRL have hardcoded reads |
| `0x11000000` | `0x11003FFF` | 16 KB | **VU0 Code** | Not modeled in runtime *(size disputed — C4)* |
| `0x11004000` | `0x11007FFF` | 16 KB | **VU0 Data** | Not modeled *(size disputed — C4)* |
| `0x11008000` | `0x1100BFFF` | 16 KB | **VU1 Code** | Not modeled |
| `0x1100C000` | `0x1100FFFF` | 16 KB | **VU1 Data** | Not modeled |
| `0x12000000` | `0x12001FFF` | 8 KB | **GS Privileged** | `gs_regs` struct with CSR W1C handling |
| `0x1C000000` | `0x1C1FFFFF` | 2 MB | **IOP RAM** | `iop_ram[]` — allocated, zero-filled |
| `0x70000000` | `0x70003FFF` | 16 KB | **Scratchpad** | `m_scratchpad[]` — fast R/W |
| `0xBFC00000` | `0xBFC7FFFF` | 512 KB | **Boot ROM** | Not modeled *(size disputed — C3)* |
| `0x1FC00000` | `0x1FC7FFFF` | 512 KB | **Boot ROM** (labelled "KSEG0 alias") | Same physical ROM, different mapping *(C3)* |
| (internal) | — | 4 MB | **GS VRAM** | `m_gsVRAM[]` — used by DMA GIF/VIF1 paths |

`[code]` Confirmed against `core/ps2xRuntime/include/runtime/ps2_memory.h`:
`PS2_RAM_SIZE = 32u*1024*1024`, `PS2_RAM_MASK = PS2_RAM_SIZE-1`,
`PS2_SCRATCHPAD_BASE = 0x70000000`, `PS2_SCRATCHPAD_SIZE = 16u*1024`,
`PS2_IO_BASE = 0x10000000`, `PS2_IO_SIZE = 0x10000`,
`PS2_BIOS_BASE = 0x1FC00000`, `PS2_BIOS_SIZE = 4u*1024*1024`,
`PS2_GS_PRIV_REG_BASE = 0x12000000`, `PS2_GS_VRAM_SIZE = 4*1024*1024`.
VU0 code/data are 4 KB each (`PS2_VU0_CODE_SIZE`, `PS2_VU0_DATA_SIZE`); VU1 16 KB each.

**Critical structural fact for tooling:** GS VRAM is `(internal)` — it is **not** in the EE
physical address space and **not** inside RDRAM. `[code]` `m_gsVRAM` is a distinct
allocation from `m_rdram` (`ps2_memory.h:384` vs `:364`). Anything that wants the framebuffer
must ask for VRAM directly; scanning RDRAM will never find pixels.

### Key runtime constants `[doc:db-memory-map.md]`

```cpp
constexpr uint32_t PS2_RAM_SIZE         = 0x02000000;  // 32 MB
constexpr uint32_t PS2_RAM_MASK         = 0x01FFFFFF;  // 32 MB - 1
constexpr uint32_t PS2_IO_BASE          = 0x10000000;
constexpr uint32_t PS2_IO_SIZE          = 0x00010000;  // 64 KB
constexpr uint32_t PS2_SCRATCHPAD_SIZE  = 0x00004000;  // 16 KB
constexpr uint32_t PS2_GS_PRIV_REG_BASE = 0x12000000;
constexpr size_t   PS2_GS_VRAM_SIZE     = 4u * 1024u * 1024u;  // 4 MB
```

### Memory access alignment rules `[doc:db-memory-map.md]`

| Width | Alignment | Runtime Check |
|-------|-----------|---------------|
| 8-bit | None | — |
| 16-bit | 2-byte | `address & 1` → throws |
| 32-bit | 4-byte | `address & 3` → throws |
| 64-bit | 8-byte | `address & 7` → throws |
| 128-bit | 16-byte | `address & 15` → throws |

### Caches and scratchpad `[doc:db-ps2-architecture.md §2]`

| Cache | Size | Associativity | Line Size | Fill | Notes |
|-------|------|--------------|-----------|------|-------|
| I-Cache | 16 KB | 2-way set-assoc | 64 bytes | RDRAM refill | |
| D-Cache | 8 KB | 2-way set-assoc | 64 bytes | Write-back | Sub-block ordering + hit-under-miss |
| Scratchpad | 16 KB | Direct-mapped | — | Software managed | Mapped at `0x70000000` |

Quoted: *"Scratchpad is NOT a cache — it's CPU-local SRAM at `0x70000000–0x70003FFF`."*
DMA can reach it as channels 8 (fromSPR) and 9 (toSPR).

### Exception vectors `[doc:db-ps2-architecture.md §9]`

| Vector | BEV=0 (Normal) | BEV=1 (Bootstrap) | Trigger |
|--------|----------------|-------------------|---------|
| Reset | — | `0xBFC00000` | Hardware reset |
| TLB Refill | `0x80000000` | `0xBFC00200` | Translation Lookaside Buffer miss |
| Counter | `0x80000080` | `0xBFC00280` | Performance counter overflow |
| Debug | `0x80000100` | `0xBFC00300` | Hardware breakpoint / debug exception |
| Common | `0x80000180` | `0xBFC00380` | All other exceptions (general exception handler) |
| Interrupt | `0x80000200` | `0xBFC00400` | Hardware interrupt exception |

### Where a game ELF's sections land

Source: `db-memory-map.md` §ELF Loading Layout. **The doc's own caveat, quoted:**
*"Actual addresses vary per game. Use the ELF program headers (`readelf -l`) to determine
exact mappings. The recompiler loads segments directly into `m_rdram`."*
The `X` digits below are wildcards in the source, not literal hex.

| Typical Range | Section | Notes |
|---------------|---------|-------|
| `0x00100000–0x001XXXXX` | `.text` | Game code (entry point usually here) |
| `0x002XXXXX–0x003XXXXX` | `.data` / `.rodata` | Initialized data, read-only constants, string literals |
| `0x004XXXXX–...` | `.bss` | Zero-initialized data (filled with 0 at runtime) |
| `0x00FXXXXX–0x01FFFFFF` | Heap/Stack | Game-managed, grows from InitHeap |
| `0x70000000` | SPR | Scratchpad (separate from RDRAM) |

- **Entry point**: *"Look at the ELF header. Typically `0x00100008` (skips the crt0 `nop`)."*
  `[derived]` `0x00100008` = `.text` base `0x00100000` + 8.
- **Discovery**: the main ELF is listed in `SYSTEM.CNF` under `BOOT2`; stripped executables
  are named `SLUS_XXX.XX` / `SLES_XXX.XX` rather than `.elf`.
- **Multi-binary**: *"Many large games use a tiny 'launcher' ELF (~1 MB) that loads the actual
  game engine from a massive `.BIN` file containing raw, stripped MIPS bytecode directly into
  RAM."* Such `.BIN` files must be wrapped in dummy ELF headers for Ghidra / `ps2_analyzer`.

---

## Address translation

### Segments

Two things are named here — the MIPS segment table and the runtime's translation rule.
They disagree; see C2.

Segment ranges `[doc:db-memory-map.md §Virtual → Physical Address Translation]`:

| Virtual Range | Segment | Translation (as documented) |
|---------------|---------|-------------|
| `0x00000000–0x7FFFFFFF` | KUSEG | `addr & 0x1FFFFFFF` (strip TLB bits, mask to physical) |
| `0x80000000–0x9FFFFFFF` | KSEG0 | `addr & 0x1FFFFFFF` (cached, no TLB) |
| `0xA0000000–0xBFFFFFFF` | KSEG1 | `addr & 0x1FFFFFFF` (uncached, no TLB) |
| `0xC0000000–0xDFFFFFFF` | KSSEG | TLB mapped (not used in practice) |
| `0xE0000000–0xFFFFFFFF` | KSEG3 | TLB mapped (not used in practice) |
| `0x70000000–0x70003FFF` | Scratchpad | Detected by `isScratchpad()` before translation |

`db-ps2-architecture.md §14` gives the same five ranges, with `0xC0000000–0xDFFFFFFF`
labelled *"KSSEG (supervisor, TLB)"* and `0xE0000000–0xFFFFFFFF` *"KSEG3 (kernel, TLB)"*.

Note `0x70000000` falls **inside KUSEG**, which is exactly why the doc insists scratchpad
detection must happen *before* translation.

### The mask — what the code actually does `[code]`

`core/ps2xRuntime/include/runtime/ps2_address.h`:

```cpp
static inline constexpr uint32_t PS2_KSEG0_BASE        = 0x80000000u;
static inline constexpr uint32_t PS2_KSEG0_KSEG1_SIZE  = 0x40000000u;   // -> 0x80000000..0xBFFFFFFF
static inline constexpr uint32_t PS2_KSEG2_BASE        = 0xC0000000u;
static inline constexpr uint32_t PS2_EE_UNCACHED_RAM_MIRROR_BASE = 0x20000000u;
static inline constexpr uint32_t PS2_EE_UNCACHED_RAM_MIRROR_SIZE = 0x20000000u;

Ps2IsUncachedRamMirrorAddress(a) => (a - 0x20000000u) < 0x20000000u
Ps2IsKseg01Address(a)            => (a - 0x80000000u) < 0x40000000u
Ps2IsKseg23Address(a)            => a >= 0xC0000000u
Ps2DirectMappedPhysicalAddress(a)=> a & 0x1FFFFFFFu        // <-- 25-bit, 32 MB
```

`PS2Memory::translateAddress()` (`src/lib/ps2_memory.cpp:568`) resolves in this order:

1. `isScratchpad(addr)` → scratchpad offset (checked **first**).
2. `0x20000000–0x3FFFFFFF` uncached RAM mirror → `addr & PS2_RAM_MASK`.
3. `0x80000000–0xBFFFFFFF` KSEG0/KSEG1 → `addr & 0x01FFFFFF`.
4. `addr < 0x80000000` → returned **unchanged** (treated as already-physical).
5. `addr >= 0xC0000000` → TLB walk; on miss **throws**
   `std::runtime_error("TLB miss for address: 0x...")`.

### The mask — the two recorded facts this note must preserve

- **Our runtime maps KSEG0 with `addr & 0x01FFFFFF` against a 32 MB RDRAM buffer.**
  `[code]` Verified: `Ps2DirectMappedPhysicalAddress() = addr & 0x1FFFFFFFu`, and
  `PS2_RAM_MASK = 0x01FFFFFF`. The window is **32 MB**, not 512 MB.
- **Our runtime treats KSEG2 as `>= 0xC0000000`.** `[code]` `Ps2IsKseg23Address(a) = a >= 0xC0000000u`,
  i.e. one test covers both `0xC0000000–0xDFFFFFFF` and `0xE0000000–0xFFFFFFFF`.

### Direct-mapping rule

Quoted `[doc:db-ps2-architecture.md §9]`: *"Most PS2 games run in KSEG0/KSEG1
(direct-mapped segments that bypass the TLB), but the kernel and some games use TLB-mapped
KUSEG space."*

So the direct-mapping rule is: **for `0x80000000–0xBFFFFFFF`, translate arithmetically and
never consult the TLB.** The TLB is consulted only for `0xC0000000–0xFFFFFFFF` in our runtime.
There is no TLB for `0x00000000–0x7FFFFFFF` here — low addresses pass through as physical.

The R5900 has a **48-entry fully-associative TLB**; page sizes 4KB, 16KB, 64KB, 256KB,
1MB, 4MB, 16MB via `PageMask`. `[code]` Our TLB match uses `entry.mask & 0x01FFE000` and
`~(mask | 0xFFFu)`, i.e. a 4 KB base page with the PageMask applied above 4 KB.

### Scratchpad detection

- Documented: *"Detection: `isScratchpad()` checks `(addr & 0x7FFFC000) == 0x70000000`"*
  `[doc:db-memory-map.md]` — a 16 KB-aligned mask test.
- `[code]` Implemented as a **range test** `addr >= 0x70000000 && addr < 0x70004000`,
  plus an alias test: if bit 31 is set, `addr & 0x7FFFFFFF` in the scratchpad range also
  matches. Behaviourally equivalent for the documented window, but it is not the documented
  check (C2).

### The project's measured KSEG0 finding (recorded fact)

A guest code search over the KSEG0 range **`0x80000000..0x80080000` resolves to physical
`0x0..0x80000`**, which lies **entirely below** the game's `.text` at `0x00100000`, so it
contains **no part of the game image**.

`[derived]` Restating it as a rule: physical `0x00100000` appears at KSEG0 `0x80100000`
(`| 0x80000000`). To search the first 1 MB of `.text` you must scan KSEG0
`0x80100000..0x80200000`, not `0x80000000..0x80080000`.

---

## IOP / DMAC / interrupt model

### What runs on the IOP

`db-ps2-architecture.md §1` labels the IOP block *"I/O Processor — 36.864 MHz"*; `§8` says
*"The IOP runs a **MIPS I (R3000A)** at 36.864 MHz with 2 MB RAM."*
The block diagram labels the core `R3000A (MIPS I) / 33 MHz` — **the two clocks disagree
within the same file**; recorded, not resolved.

IOP responsibilities `[doc:db-ps2-architecture.md §8]`:

| Subsystem | Connection | Purpose |
|-----------|-----------|---------|
| Controllers | SPI (250 KHz) | DualShock2 gamepad, multitap |
| Memory Cards | SPI (250 KHz) | 8 MB save storage |
| CD/DVD | ATAPI-like | Game data, streaming FMV |
| USB 1.1 | Host controller | Peripherals |
| IEEE 1394 | i.LINK | Network adapter (early model) |
| Ethernet | SMAP (PCMCIA) | Network play (expansion) |
| HDD | ATAPI | PS2 HDD (expansion bay) |
| SPU2 | DMA | Sound RAM access |

`[code]` Our runtime allocates `iop_ram[]` (2 MB at `0x1C000000`) zero-filled but **does not
execute R3000A code**; there is no IOP CPU. Anything IOP-side is stubbed at the RPC boundary.

### How EE and IOP synchronise `[doc:db-ps2-architecture.md §8]`

Quoted, EE ↔ IOP communication via shared registers:

- **SIF0**: IOP → EE DMA (channel 5) — IOP sends data to EE
- **SIF1**: EE → IOP DMA (channel 6) — EE sends commands to IOP
- **SIF2**: Bidirectional (channel 7) — rarely used
- **SMFLG**: Shared mailbox flags (`0x1000F230`) — used for synchronization
- **SIF RPC**: High-level RPC mechanism built on SIF DMA — games call IOP modules this way

The physical path in the block diagram is `SIF → MBUS` and `SIF → IOPDMA`.
Register range: `0x1000F200–0x1000F260`, noted as *"SIF_SMFLG/CTRL have hardcoded reads."*

### DMAC `[doc:db-ps2-architecture.md §3]`

10 channels:

| Ch | Target | Dir |
|----|--------|-----|
| 0 | VIF0 | to VIF0 |
| 1 | VIF1 | to VIF1 |
| 2 | GIF | to GIF |
| 3 | fromIPU | IPU → memory |
| 4 | toIPU | memory → IPU |
| 5 | SIF0 | IOP → EE |
| 6 | SIF1 | EE → IOP |
| 7 | SIF2 | bidirectional |
| 8 | fromSPR | scratchpad |
| 9 | toSPR | scratchpad |

Transfer modes (Dn_CHCR.MOD): **Normal** `00` (single block, Dn_QWC quadwords from Dn_MADR),
**Chain** `01` (linked tag+data packets; GIF path 1/2, VIF streams), **Interleave** `10`
(transfer `D_SQWC.TQWC` qwords, skip `D_SQWC.SQWC`, repeat — designed for interlaced video).

128-bit DMA tag: `ADDR` [127:96], reserved [95:80], IRQ+PCE [79:78], ID [77:74]
(`0=REFE, 1=CNT, 2=NEXT, 3=REF, 4=REFS, 5=CALL, 6=RET, 7=END`), reserved [63:32],
ADDR upper/reserved [31:16], `QWC` [15:0].

Priority `[doc]`: stall-control channels first; default **Ch5 (SIF0) > Ch0 > Ch1 > Ch2 > others**;
drain channels (fromIPU, SIF0) must be serviced or they stall the source; `D_SQWC` prevents
bus starvation.

`[doc]` DMA start control flow: on `CHCR.STR` write → detect start → read MADR/QWC → for GIF
(ch2) and VIF1 (ch1) parse chain tags if mode=1 → enqueue `PendingTransfer` →
`processPendingTransfers()` submits GIF packets / VIF1 data.

### Interrupt model `[doc:db-ps2-architecture.md §4]`

Sources (INTC_STAT bits): `0:GS`, `1:SBUS (SIF)`, `2:VB_ON (VBlank start)`, `3:VB_OFF (VBlank end)`,
`4:VIF0`, `5:VIF1`, `6:VU0`, `7:VU1`, `8:IPU`, `9–12:TIM0–TIM3`, `13:SFIFO (SIF FIFO)`,
`14:VU0WD (watchdog)`.

Registers: `INTC_STAT` at `0x1000F000` (write 1 to clear), `INTC_MASK` at `0x1000F010`
(write 1 to toggle). Signal path: `STAT → AND with MASK → COP0 Status.IM[2]` (IP2) →
exception if `Status.IE=1 AND Status.EXL=0 AND Status.ERL=0`.

Quoted flow: hardware sets `INTC_STAT` bit → if enabled in `INTC_MASK`, asserts INT0 to EE →
EE COP0 sees IP2 in Cause → if IE/EXL/ERL permit, exception taken → `EPC` = current PC,
`ExcCode = 0` → jump to vector → handler reads `INTC_STAT`, clears by writing 1.

Exception entry (`§9`): `EPC` ← PC, `Cause.ExcCode` ← code, `Status.EXL` ← 1, PC ← vector.
*"For **interrupt exceptions** specifically, the handler reads `INTC_STAT` and/or
`DMAC D_STAT` to identify the specific interrupt source."*

### What a recompiler must emulate — derived from the above

1. **DMA as a state machine, not a call.** Chain mode means one `STR` write expands into many
   memory reads plus GIF/VIF packet emission. Cycles consumed are bus-dependent and the docs
   give no cycle counts for DMA — timing must be approximated.
2. **`INTC_STAT`/`INTC_MASK` W1C / write-1-to-toggle semantics.** A handler that reads STAT
   and writes it back verbatim will clear *every* asserted source.
3. **The full 15-bit source set**, including `VB_ON`/`VB_OFF` — the frame-diff tool needs
   VBlank edges, and a game that gates its whole loop on `VB_ON` will hang if bit 2 never fires.
4. **Scratchpad aliasing before translation**, or 0x70000000 lands in RDRAM.
5. **SIF RPC as a black box.** SIF0/SIF1/SMFLG must be modelled well enough that an RPC
   round-trip returns a plausible result; the real R3000A is not present in our runtime.
   `[GAP]` — the four files do not give the RPC packet layout; `db-ps2-index.md` routes
   "IOP RPC mechanism" and "SIF RPC" to `db-syscalls.md` and `db-sdk-functions.md`, which
   were **not read for this note**.
6. **FPU non-IEEE behaviour** (`db-ps2-architecture.md §10`) if game logic is being
   recomputed: denormals flushed to zero, NaN always `0x7FBFFFFF`, ±Infinity →
   ±MAX_FLOAT (`0x7F7FFFFF` / `0xFF7FFFFF`), round-to-zero only, **no FP exceptions**,
   some ops reduced precision.

---

## GS / rendering

### What a frame-diff tool actually needs

**GS VRAM is a separate 4 MB buffer, `(internal)` to the runtime — not in the EE address
space and not in RDRAM.** `[code]` `m_gsVRAM` (`ps2_memory.h:384`) is distinct from `m_rdram`
(`:364`). Frame-diff tooling must read VRAM explicitly.

### GS hardware `[doc:db-ps2-architecture.md §1]`

- Graphics Synthesizer — **147.456 MHz**; Pixel Engine, **16 parallel pipelines**.
- **4 MB eDRAM**, 2560-bit internal bus, **48 GB/s**.
- PCRTC (CRT Controller) drives `video out` → Display.
- VRAM → texture read loops back into the texture stage (feedback read via `EXTBUF`).

### Pixel storage formats `[doc:db-ps2-architecture.md §5]` — verbatim

| PSM | Value | BPP | Description | VRAM per 64×32 block |
|-----|-------|-----|-------------|---------------------|
| PSMCT32 | 0x00 | 32 | RGBA 8888 | 8 KB |
| PSMCT24 | 0x01 | 24 | RGB 888 (packed, no alpha) | 6 KB |
| PSMCT16 | 0x02 | 16 | RGBA 5551 | 4 KB |
| PSMCT16S | 0x0A | 16 | RGBA 5551 (swizzled layout) | 4 KB |
| PSMT8 | 0x13 | 8 | 8-bit indexed (CLUT) | 2 KB |
| PSMT4 | 0x14 | 4 | 4-bit indexed (CLUT) | 1 KB |
| PSMT8H | 0x1B | 8 | 8-bit in upper 8 bits of 32-bit | 8 KB (shares with CT32) |
| PSMT4HL | 0x24 | 4 | 4-bit in bits [7:4] of 32-bit | 8 KB (shares) |
| PSMT4HH | 0x2C | 4 | 4-bit in bits [11:8] of 32-bit | 8 KB (shares) |
| PSMZ32 | 0x30 | 32 | 32-bit depth buffer | 8 KB |
| PSMZ24 | 0x31 | 24 | 24-bit depth buffer | 6 KB |
| PSMZ16 | 0x32 | 16 | 16-bit depth buffer | 4 KB |
| PSMZ16S | 0x3A | 16 | 16-bit depth (swizzled) | 4 KB |

### Framebuffer layout — page / block structure `[doc:db-ps2-architecture.md §5]`

Quoted: *"VRAM is addressed in **pages** of 2048 pixels."*

```
PSMCT32 page: 64 columns × 32 rows = 2048 pixels = 8192 bytes
  - 1 page = 32 blocks of 8×8 pixels (256 bytes each)
  - Block arrangement within page: Block[0..31] in 4 rows of 8

Pixel layout WITHIN a block is NOT linear — it's swizzled for bandwidth.
For PSMCT32, an 8×8 block stores pixels in column-interleaved order.
```

Quoted note: *"Most games use `TEX0.TBW` (buffer width) aligned to page boundaries."*

**Frame-diff implication** `[derived]`: a framebuffer is **not** contiguous row-major.
Converting VRAM → image requires (a) stepping by page, (b) stepping by 8×8 block inside the
page, (c) un-swizzling column-interleaved order inside the block. A naive linear read of a
`FRAME`-selected region yields a scrambled image, not a sheared one. The source says
"column-interleaved" but **does not give the exact permutation**, so the block decode must
come from elsewhere (see `[GAP]` below).

### Display buffers

**What the sources actually say:**

- The GS maintains **two independent rendering contexts** (Context 1 / Context 2) — each with
  its own `FRAME`, `ZBUF`, `TEX0`, `ALPHA`, `TEST`, `SCISSOR`, `XYOFFSET`. `PRIM.CTXT`
  selects the context for the current primitive. *"This allows two geometry engines (EE+VU0
  and VU1) to interleave drawing commands without re-setting all state registers."*
  **These are drawing-state contexts, not display buffers.**
- The *only* buffering documented is on the **RDRAM side**, in `§12` Optimization Patterns:
  - **Double buffering**: Frame N — CPU builds display list → Buffer A, DMA sends Buffer B →
    GIF/VIF; Frame N+1 swaps.
  - **Triple buffering**: Buffer A (CPU writing), Buffer B (DMA transferring), Buffer C
    (VU1 processing); rotate A→B→C→A. *"Triple buffering prevents all stalls when the three
    stages have variable latency."*
  - **VU1 double buffer** inside VU1 data memory: `0x000–0x1FF` Buffer A,
    `0x200–0x3FF` Buffer B.
- Back-pressure: *"The GIF has a **GS FIFO** ... When the GS is busy rasterizing and cannot
  accept new data, the GS FIFO fills up, which back-pressures the GIF→DMA chain. Monitoring
  `GIF_STAT` and avoiding GS FIFO overflow is important for maintaining throughput."*

`[GAP]` — **None of the four files describe VRAM-level double buffering.** Specifically
absent: the `FRAME` register's double-buffer mode (DBM) bit, the `PSMCT`/`PSMZ` framebuffer
selectors, the fixed second-buffer VRAM offset used with DBM, the `TBP0`/`TBP1` vs. `TBP2`
buffer-address pairing, and the scanout interleave/offset applied during VRAM→display read.
`db-ps2-index.md` routes "GS general registers bit-fields" to `db-registers.md` and
"sceGsSyncV / sceGsSyncPath" to `db-sdk-functions.md`; **neither was read for this note**.
A frame-diff tool must not assume the display buffer is derivable from what is written here.

### How a frame becomes visible

**What the sources actually say:**

- `VRAM → PCRTC → "video out" → Display` (§1 mermaid). PCRTC is the only named scanout stage.
- VBlank is observable as two INTC sources: **bit 2 `VB_ON` (VBlank start)** and
  **bit 3 `VB_OFF` (VBlank end)**.
- GS writes land in VRAM through the `FRAME` register ("Pixel Write / FRAME register", §5).
- `sceGsSyncV` / `sceGsSyncPath` are the game's synchronization calls — listed in
  `db-ps2-index.md` as living in `db-sdk-functions.md` (not read here).

`[GAP]` — **There is no description in these four files of the actual visibility transition.**
Absent: TV mode / interlace configuration, display resolution and pixel clock, the VRAM
addresses PCRTC scans out per frame, whether scanout reads through the swizzled layout, the
VB_ON→VB_OFF interval in cycles, and whether `sceGsSyncPath` blocks on GIF FIFO drain.
**A frame-diff tool cannot be built to spec from this corpus alone.**

What *is* safe to assert `[derived]`: `VB_ON` is the only per-frame "something was drawn"
signal available at the EE, and it is an `INTC_STAT` bit the guest must enable in
`INTC_MASK` itself. A frame-diff tool that captures on `VB_ON` without the guest unmasking
bit 2 will see nothing.

### Rasterization notes relevant to pixel output

- **16 parallel pixel pipelines**, one pixel per cycle each, all sharing the 2560-bit eDRAM bus.
- Pipeline order: vertex processing → scissor (`SCISSOR_1/_2`) → triangle setup → pixels →
  **Z test** → texture → fog (`FOGCOL`) → alpha (`ALPHA_1/_2`) → dither (`DTHE`) →
  color clamp (`COLCLAMP`) → framebuffer write.
- **Depth convention is inverted**: `TEST.ZTST` — `0 NEVER`, `1 ALWAYS`, `2 GEQUAL`, `3 GREATER`.
  *"The PS2's default depth convention is reversed from typical APIs — closer objects have
  **larger** Z values."* A frame-diff tool that mirrors OpenGL's LESS test will match the
  wrong triangles.
- Filtering: `MMAG/MMIN=0` nearest, `=1` bilinear, `MMIN=2..5` trilinear; mipmap base
  pointers in `MIPTBP1`/`MIPTBP2`, up to 7 levels, `TEX0.TBP0` = level 0.
- GS coordinate space: GS expects **12.4 fixed-point XY + 24-bit Z**.
- Primitives: POINT 0, LINE 1, LINESTRIP 2, TRIANGLE 3, TRISTRIP 4, TRIFAN 5, SPRITE 6.
- GIF paths: **PATH1** VU1 `XGKICK` → GIF; **PATH2** DMA ch2 RDRAM → GIF;
  **PATH3** VIF1 `DIRECT`/`DIRECTHL` passthrough → GIF.

---

## Contradictions

Listed only. No other file was edited.

### C1 — KSEG0 guest-code search window finds no game code *(project measurement vs. the implied "KSEG0 = game code" reading)*

A guest code search over **`0x80000000..0x80080000`** resolves to physical **`0x0..0x80000`**,
entirely **below** the game's `.text` at `0x00100000`, so it contains **no part of the game
image**.

`[derived]` Translation: `0x80000000 & 0x01FFFFFF = 0x00000000`;
`0x80080000 & 0x01FFFFFF = 0x00080000`. The window is 512 KB below `.text`.
**Correction to tooling:** physical `0x00100000` is at KSEG0 `0x80100000`; scan
`0x80100000..0x80200000` for the first MB of `.text`, not `0x80000000..0x80080000`.

### C2 — The translation mask: 25 bits (32 MB) in code, 29 bits (512 MB) in the doc

| Source | Says |
|--------|------|
| `db-memory-map.md` translation table | `addr & 0x1FFFFFFF` for KUSEG, KSEG0 **and** KSEG1 |
| `db-memory-map.md` constants block, same file | `PS2_RAM_MASK = 0x01FFFFFF` |
| `db-ps2-architecture.md §14` | KSEG0 *"Maps to physical 0x00–0x1F / 512 MB window"* |
| `[code]` `ps2_address.h:36` | `return addr & 0x1FFFFFFFu;` — **25 bits, 32 MB** |

- **Our runtime maps KSEG0 with `addr & 0x01FFFFFF` against a 32 MB RDRAM buffer.** The
  `0x1FFFFFFF` in the doc's table describes a 512 MB window and is wrong for this runtime —
  `db-memory-map.md` contradicts **itself** between its table and its constants block.
- `db-ps2-architecture.md §14`'s *"physical 0x00–0x1F"* is truncated/garbled — 0x1F is not a
  512 MB endpoint either. No source states a 4 MB ROM + 512 MB RAM configuration.

### C3 — KSEG2 naming: docs say "KSSEG", runtime and MIPS say KSEG2

- `db-memory-map.md` and `db-ps2-architecture.md §14` both name `0xC0000000–0xDFFFFFFF`
  **"KSSEG"**. Standard MIPS/R5900 nomenclature (and our runtime) is **KSEG2**; **KSEG3** is
  `0xE0000000–0xFFFFFFFF`, which both docs agree on.
- `[code]` `PS2_KSEG2_BASE = 0xC0000000u`.
- **Our runtime treats KSEG2 as `>= 0xC0000000`** — a single test spanning both
  `0xC0000000–0xDFFFFFFF` and `0xE0000000–0xFFFFFFFF`, so the docs' split has no runtime
  counterpart.

### C4 — Scratchpad detection: documented mask vs. implemented range test

- `db-memory-map.md`: *"`isScratchpad()` checks `(addr & 0x7FFFC000) == 0x70000000`"*.
- `[code]` `ps2_memory.h:89` implements a range check plus a 31-bit alias test. Not the
  documented check; behaviourally equivalent over the documented window, but any code that
  depends on the masked form (e.g. non-16 KB-aligned addresses aliasing) will not match.

### C5 — Undocumented address windows in our runtime

None of these appear in `db-memory-map.md`:
- **Uncached RAM mirror** `0x20000000–0x3FFFFFFF` → `addr & PS2_RAM_MASK`.
- `addr < 0x80000000` is returned **unchanged** as physical — so KUSEG is not translated at
  all in our runtime, contradicting the doc's KUSEG row.
- Scratchpad **alias** `PS2_SCRATCHPAD_ALIAS_BASE = 0xF0000000`.

### C6 — IOP RAM at `0x1C000000` collides with RDRAM under the documented KUSEG rule

`[derived]` The doc places IOP RAM at `0x1C000000–0x1C1FFFFF` in a **separate** `iop_ram[]`
array, while documenting KUSEG as *"strip TLB bits, mask to physical"*. Both documented
masks collapse it: `0x1C000000 & 0x1FFFFFFF = 0x00000000` and
`0x1C000000 & 0x01FFFFFF = 0x00000000`. The doc's KUSEG row is therefore wrong as written;
our runtime sidesteps it via the "`< 0x80000000` passes through unchanged" rule (C5).

### C7 — Boot ROM size: 512 KB vs 4 MB

| Source | Range | Size |
|--------|-------|------|
| `db-memory-map.md` | `0xBFC00000–0xBFC7FFFF` | 512 KB |
| `db-memory-map.md` | `0x1FC00000–0x1FC7FFFF` | 512 KB, labelled *"(KSEG0 alias)"* |
| `db-ps2-architecture.md §14` | `0x1FC00000–0x1FFFFFFF` | 4 MB |
| `[code]` `ps2_memory.h:34-35` | `PS2_BIOS_BASE = 0x1FC00000` | `PS2_BIOS_SIZE = 4 MB` |

- The two 512 KB rows in `db-memory-map.md` are the outliers. **4 MB is corroborated twice.**
- The *"(KSEG0 alias)"* label is **wrong**: `0x1FC00000` is not in KSEG0
  (`0x80000000–0x9FFFFFFF`). `0xBFC00000 & 0x01FFFFFF = 0x1FC00000`, so it is a **KSEG1**
  (`0xA0000000–0xBFFFFFFF`) alias.

### C8 — EE register window: 8 KB vs 64 KB

`db-memory-map.md`'s table says `0x10000000–0x10001FFF` = 8 KB **EE Registers**, but the
same file's constants say `PS2_IO_SIZE = 0x00010000` (64 KB), and `db-ps2-architecture.md §14`
says `0x10000000–0x1000FFFF`. The 8 KB row is too narrow — and would exclude the SIF range
`0x1000F200–0x1000F260` sitting elsewhere in the same table. `[code]` `PS2_IO_SIZE = 0x10000`.

### C9 — VU0 memory size: 16 KB vs 4 KB

| Source | VU0 Code | VU0 Data |
|--------|----------|----------|
| `db-memory-map.md` | `0x11000000–0x11003FFF`, **16 KB** | `0x11004000–0x11007FFF`, **16 KB** |
| `db-ps2-architecture.md §6` | 4 KB (256 instructions) | 4 KB (256 QW) |
| `db-vu-instructions.md §VU Memory` | 4 KB (`0x000–0xFFF`) | 4 KB (`0x000–0xFFF`) |
| `[code]` `ps2_memory.h:39-40` | `PS2_VU0_CODE_SIZE = 4 KB` | `PS2_VU0_DATA_SIZE = 4 KB` |

Bases agree across all four (`0x11000000` / `0x11004000` / `0x11008000` / `0x1100C000`);
only the VU0 **sizes** are wrong in `db-memory-map.md`. VU1 (16 KB each) is uncontested.

### C10 — IOP clock: 36.864 MHz vs 33 MHz

`db-ps2-architecture.md §1` block label says *"R3000A (MIPS I) / 33 MHz"* while its own §8
prose says *"**MIPS I (R3000A)** at 36.864 MHz"*. The SIF bandwidth row also uses 37 MHz.
Unresolved in the source. Immaterial to us (no IOP CPU is executed), but the doc is
self-inconsistent.

### C11 — KSEG0 exception vectors land in physical zero under our mask

`[derived]` `db-ps2-architecture.md §9` places the BEV=0 **TLB refill** vector at
`0x80000000` and the **common** handler at `0x80000180`. Under `addr & 0x01FFFFFF` these
resolve to physical `0x00000000` and `0x00000180` — RDRAM low addresses, not game code.
The vectors are legal (KSEG0 bypasses the TLB, as §9 itself states), but no source says
where a typical game's handlers actually live. Since most games run entirely in
KSEG0/KSEG1 and never take a TLB refill, this is likely unexercised — unconfirmed.
**Do not assume a KSEG0-range exception lands on anything meaningful.**

### C12 — Documentation gaps that block a frame-diff tool

Not contradictions, but the corpus is silent where the work needs answers:
- **VRAM double-buffering / display buffer** (DBM, PSMCT/PSMZ, second-buffer offsets) — see
  GS §Display buffers. Routed by `db-ps2-index.md` to `db-registers.md` (not read).
- **Exact 8×8 block swizzle permutation** — `"column-interleaved order"` only.
- **The frame-visibility transition** — no VBlank timing, no scanout description.
- **IOP RPC packet layout** — `db-ps2-index.md` routes it to `db-syscalls.md` (not read).
- **DMA timing** — no cycle counts anywhere; transfer cost cannot be derived from this corpus.

---

## Cross-reference index (from `db-ps2-index.md`)

Files referenced by the corpus but **not read for this note** — listed so the next reader
knows exactly which gaps are closable:

| Needed for | File (per `db-ps2-index.md`) |
|-------------|------|
| Hardware register bit-fields, GS general registers, `FRAME`/DBM | `db-registers.md` |
| `sceGsSyncV` / `sceGsSyncPath`, `sceGs*`, `sceDma*` | `db-sdk-functions.md` |
| IOP RPC, syscall table, stub linking | `db-syscalls.md` |
| R5900 instruction set, COP2 macro mode | `db-isa.md` |
| Complete register-level memory map | `db-memory-map.md` → `db-registers.md` |
| Hardware diagrams (80 classified) | `images/IMAGE_CATALOG.md` |
| Deep register/format reference (~232 KB) | `09-ps2tek.md` |

The corpus defers register *bit-fields* uniformly to `db-registers.md`, and every register
range quoted in this note came from `db-memory-map.md` plus `db-ps2-architecture.md`. No
bit-level claim has been made here.
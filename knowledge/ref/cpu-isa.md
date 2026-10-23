# CPU / ISA

Distilled, machine-checkable notes on the R5900 (EE) instruction set, register file, delay-slot behaviour and MMU/cache model, for the PS2 static recompiler.

Scope of this file: distilled **only** from `resources/01-ps2-hardware-bible.md`, `resources/02-mips-r5900-isa.md`, `resources/db-isa.md`, `resources/db-registers.md`. Anything those files do not state is marked `NOT STATED` — it is a gap to be closed from the EE Core User's Manual, not a fact.

---

## Verified facts

### Core and register file

1. The EE core is the **R5900**, described as "Enhanced MIPS III/IV". — `source: 01-ps2-hardware-bible.md:23`
2. There are **32 GPRs**, and they are **128-bit wide**. "Lower 64 bits are standard MIPS; upper 64 bits are used by Multimedia Instructions (MMI)." — `source: 01-ps2-hardware-bible.md:24-25`, repeated at `source: db-isa.md:576` (`## 8. GPR Register Map (128-bit wide on PS2)`) and `source: db-isa.md:595`
3. The C++ context representation uses `uint128_t gpr[32]` and **`uint128_t lo, hi, lo1, hi1`** — i.e. the multiply/divide accumulators are 128-bit too, and there are two independent accumulator pairs. — `source: 01-ps2-hardware-bible.md:89-99` (`struct R5900Context`)
4. Narrow (32-bit) GPR access in generated/hand-written C++ is `ctx.gpr[N].words[0]`; full-width access is `ctx.gpr[N]`. — `source: 02-mips-r5900-isa.md:25-31`, `source: db-isa.md:597`
5. O32 conventions with a PS2 extension: `$a0-$a3` = args 1–4, **`$t0-$t3` = args 5–8**, `$v0-$v1` = return values. — `source: 02-mips-r5900-isa.md:11-13`, `source: db-isa.md:583-584`
6. Coprocessors: **COP0** = system control (exceptions, MMU/TLB, PRID); **COP1** = FPU; **COP2** = VU0 Macro Mode, "closely tied to EE pipeline". — `source: 01-ps2-hardware-bible.md:27-30`
7. Ghidra pseudocode artifacts `afff()` / `qword` "usually indicate a 128-bit MMI register access or `lq`/`sq`". — `source: 02-mips-r5900-isa.md:78-81`

### Instruction encoding

8. Decode order: opcode bits [31:26] → SPECIAL/REGIMM/MMI/COPx sub-tables; SPECIAL and MMI dispatch on bits [5:0]; REGIMM and BCx dispatch on bits [20:16]; MMI sub-tables dispatch on **bits [10:6]**. — `source: db-isa.md:7-12`
9. Formats: R-Type `[opcode:6][rs:5][rt:5][rd:5][sa:5][function:6]`, I-Type `[opcode:6][rs:5][rt:5][immediate:16]`, J-Type `[opcode:6][target:26]`. Field-extraction macros: `OPCODE(i)=(i>>26)&0x3F`, `RS=(i>>21)&0x1F`, `RT=(i>>16)&0x1F`, `RD=(i>>11)&0x1F`, `SA=(i>>6)&0x1F`, `FUNCTION=i&0x3F`, `TARGET=i&0x3FFFFFF`. — `source: db-isa.md:14-36`
10. **PS2-only primary opcodes**: `MMI` 0x1C, `LQ` 0x1E, `SQ` 0x1F, `LQC2` 0x36, `SQC2` 0x3E. `LQ`/`SQ` **require 16-byte alignment or SIGBUS**. — `source: db-isa.md:98-100`
11. `MOVZ` (SPECIAL 0x0A) and `MOVN` (SPECIAL 0x0B) are PS2-only conditional moves. — `source: db-isa.md:116-117`
12. `MFSA` (SPECIAL 0x28) / `MTSA` (SPECIAL 0x29) and `MTSAB` (REGIMM 0x18) / `MTSAH` (REGIMM 0x19) move the **SA register**; `MTSAB`/`MTSAH` move a byte/halfword. — `source: db-isa.md:140-141`, `source: db-isa.md:181-182`
13. `EI` / `DI` are COP0 CO functions **0x38 / 0x39** (interrupt enable/disable). — `source: db-isa.md:355-356`, `source: db-isa.md:611`

### MMI

14. MMI is primary opcode **0x1C**, and *all* of its entries are PS2-specific. Sub-table selectors: **MMI0 = function 0x08, MMI1 = 0x28, MMI2 = 0x09, MMI3 = 0x29**. — `source: db-isa.md:186`, `source: db-isa.md:195-196`, `source: db-isa.md:207-208`, `source: db-isa.md:229`, `source: db-isa.md:259`, `source: db-isa.md:282`, `source: db-isa.md:309`
15. MMI provides a **second multiply/divide pipeline** using HI1/LO1: `MULT1` 0x18, `MULTU1` 0x19, `DIV1` 0x1A, `DIVU1` 0x1B, `MADD1` 0x20, `MADDU1` 0x21, `MFHI1` 0x10, `MTHI1` 0x11, `MFLO1` 0x12, `MTLO1` 0x13. — `source: db-isa.md:197-206`
16. `PMFHL` (0x30) / `PMTHL` (0x31) select variants via the **sa field, bits [10:6]**: 0 LW, 1 UW, 2 SLW, 3 LH, 4 SH. — `source: db-isa.md:209-210`, `source: db-isa.md:218-225`
17. The MMI set is **"80+ parallel SIMD instructions operating on 128-bit registers"**, including saturation (`PADDSW`/`PADDSH`/`PADDSB`), pack/extend (`PPACW`/`PEXTLW`, …), funnel shift (`QFSRV`), and horizontal multiply-add (`PHMADH`/`PHMSBH`). — `source: db-isa.md:623-624`, `source: db-isa.md:186-326`

### COP0 / MMU / TLB

18. `Cause` bits **6:2 = ExcCode**; `Cause` bit **31 = BD** (level-1 exception in a branch delay slot) and bit **30 = BD2** (NMI/PerfC/Debug in a delay slot). — `source: db-registers.md:407-408`, `source: 01-ps2-hardware-bible.md:78-82`
19. ExcCode values: `0 Int`, `1 Mod`, `2 TLBL`, `3 TLBS`, `4 AdEL`, `5 AdES`, `6 IBE`, `7 DBE`, `8 Sys`, `9 Bp`, `10 RI`, `11 CpU`, `12 Ov`, `13 Tr`. — `source: db-registers.md:416-433`, `source: 01-ps2-hardware-bible.md:78-82`
20. `Status` bit fields: `CU[3:0]` 31:28, `DEV` 23, `BEV` 22, `CH` 18, `EDI` 17, `EIE` 16, `IM` (15, 11:10), `BEM` 12, `KSU` 4:3, `ERL` 2 (**init 1**), `EXL` 1, `IE` 0. COP0 is always usable in Kernel mode; **COP3 is always unusable**. — `source: db-registers.md:386-401`
21. The TLB has **48 entries**: `Index` is 6 bits, range 0–47. — `source: db-registers.md:473-478`
22. `Random` is read-only, 6 bits, counts **down each instruction**, wraps to 47; invariant `Wired ≤ Random ≤ 47`. Entries `0..Wired-1` are never replaced by `TLBWR`. — `source: db-registers.md:480-486`, `source: db-registers.md:529-533`
23. TLB ops: `TLBR` 0x01, `TLBWI` 0x02, `TLBWR` 0x06, `TLBP` 0x08; `ERET` is COP0 CO 0x18. — `source: db-isa.md:347-357`
24. `EntryLo0/1` layout: bit 31 **S** (Scratchpad — EntryLo0 only), PFN 25:6, **C 5:3**, **D** 2, **V** 1, **G** 0. `G` must be set in *both* EntryLo0 and EntryLo1 to ignore ASID match. — `source: db-registers.md:488-497`
25. `EntryLo` C-field cache modes: **010 = Uncached, 011 = Cached write-back with write allocate, 111 = Uncached Accelerated**, others reserved. — `source: db-registers.md:462-469`
26. `EntryHi`: **VPN2 31:13, ASID 7:0**. — `source: db-registers.md:499-504`
27. `PageMask` MASK values map to pages **4 KB / 16 KB / 64 KB / 256 KB / 1 MB / 4 MB / 16 MB** (`0x000, 0x003, 0x00F, 0x03F, 0x0FF, 0x3FF, 0xFFF`). — `source: db-registers.md:513-527`
28. `Context`: PTEBase 31:23, BadVPN2 22:4 (read-only, auto-set). — `source: db-registers.md:506-511`
29. `Count` is a free-running timer; when `Count == Compare`, `IP[7]` is set in `Cause`; writing `Compare` clears the pending bit. — `source: db-registers.md:541-553`
30. `EPC` "points to faulting instruction or **preceding branch** (if BD=1)", and is **not updated when `Status.EXL = 1`**. `ErrorEPC` is the level-2 equivalent, keyed on `BD2`. — `source: db-registers.md:555-561`, `source: db-registers.md:576-580`
31. Exception vectors — normal: `0xBFC00000` (Reset/NMI), `0x80000000` (TLB Refill), `0x80000080` (Counter), `0x80000100` (Debug), `0x80000180` (all other L1), `0x80000200` (Interrupt); bootstrap (`BEV=1`/`DEV=1`): `0xBFC00200/280/300/380/400`. — `source: db-registers.md:449-460`
32. PS2-only COP0 registers: **23 BadPAddr**, **24 Debug**, **25 Perf**. `PRId` `Imp` = **0x2E** for the EE Core. — `source: db-isa.md:375-379`, `source: db-registers.md:370-378`

### Cache

33. `Config` cache bits: **`ICE` 17 (I-cache enable, init 0), `DCE` 16 (D-cache enable, init 0), `NBE` 13 non-blocking load, `BPE` 12 branch prediction, `IC` 11:9 (=010 → 16 KB), `DC` 8:6 (=001 → 8 KB), `K0` 2:0 (kseg0 cache mode: 010 uncached, 011 cached WB, 111 uncached accel; init "Undef")**, `DIE` 18 dual-issue, `EC` 30:28. — `source: db-registers.md:435-447`
34. `Status.CH` (bit 18) reports hit/miss of the **last `CACHE` instruction**. `CACHE` is primary opcode 0x2F. — `source: db-registers.md:392`, `source: db-isa.md:89`
35. `TagLo` = `PTagLo` 31:12, `D` 6 (dirty), `V` 5 (valid), `R` 4 (LRF), `L` 3 (lock); used with `CACHE` ops **DXLTG/DXSTG, IXLTG/IXSTG**; `TagHi[31:2]` holds the BTAC target address. — `source: db-registers.md:652-662`

### FPU

36. The PS2 FPU is **single-precision only** (`.S`); double-precision (D/L) ops are "defined but unused". `f0-f31`. — `source: db-isa.md:388-389`, `source: 02-mips-r5900-isa.md:43-47`
37. PS2 FPU extensions: `RSQRT.S` 0x16, `ADDA.S` 0x18, `SUBA.S` 0x19, `MULA.S` 0x1A, `MADD.S` 0x1C, `MSUB.S` 0x1D, `MADDA.S` 0x1E, `MSUBA.S` 0x1F, `MAX.S` 0x28, `MIN.S` 0x29. — `source: db-isa.md:425-435`

### COP2 / VU0

38. COP2 is primary opcode **0x12**. Format field [25:21]: `QMFC2` 0x01 (move quadword from VU0), `CFC2` 0x02, `QMTC2` 0x05, `CTC2` 0x06, `BC2` 0x08, `CO` 0x10+. — `source: db-isa.md:450-460`
39. VU0 macro CO has **two sub-tables selected by bit 0 of opcode2**: bit0 = 0 → Special1, bit0 = 1 → Special2. — `source: db-isa.md:470`, `source: db-isa.md:503`
40. VU0 control registers (for CFC2/CTC2): 0 Status, 1 MAC, 2 VPU-STAT, 3 R, 4 I, 5 Clip, 6 TPC, 7 CMSAR0, 8 FBRST, **20 ACC**, **26 P**, 27 XITOP, 28 ITOP, 29 TOP. — `source: db-isa.md:541-557`
41. `LQC2`/`SQC2` move **128 bits** between memory and VU0 vector registers. — `source: db-isa.md:92`, `source: db-isa.md:95`
42. VU0 is used in **Macro Mode**, "directly extending the EE instruction set via COP2"; VU1 runs in Micro Mode, fed by VIF1 DMA. — `source: 01-ps2-hardware-bible.md:68-70`

### Memory map and syscalls

43. EE memory map (as given): `0x00000000` 32 MB RDRAM (cached, EE-accessible); `0x10000000` 64 KB EE hardware I/O; `0x10008000-0x1000E0FF` DMAC; `0x11000000`/`0x11004000` VU0 code/data 16 KB each; `0x11008000`/`0x1100C000` VU1 code/data 16 KB each; `0x12000000` GS privileged; `0x1C000000` 2 MB IOP RAM; `0x70000000` 16 KB Scratchpad; `0xBFC00000` 512 KB Boot ROM. — `source: 01-ps2-hardware-bible.md:32-45`
44. **Vague:** "Addresses above `0x20000000` mirror the lower 512MB space with different cache configurations (kseg0, kseg1)." No mask, no segment boundaries are given. — `source: 01-ps2-hardware-bible.md:47`
45. `SYSCALL` jumps to the BIOS exception handler which uses mapping tables; in PS2Recomp these are trapped and routed to `ps2_syscalls.cpp`. — `source: 01-ps2-hardware-bible.md:83-84`, `source: db-isa.md:118`

### Vagueness / gaps (things these sources do NOT establish)

46. **The R5900 "short loop" branch erratum is not documented anywhere in this corpus.** A case-insensitive search of `resources/` for `errat|erratum|short loop` returns zero hits. Do not encode erratum behaviour on the strength of these files; obtain the exact conditions from the EE Core User's Manual errata sheet. — `source: grep over resources/ (0 matches)`
47. These sources never state the **KUSEG/KSEG0/KSEG1/KSEG2 segment boundaries** or the `addr & 0x01FFFFFF` RDRAM translation rule. Only the vague note at `01-ps2-hardware-bible.md:47` and the KSEG0-derived exception vectors (`0x80000000`) / bootstrap addresses (`0xBFC00xxx`) are present.
48. These sources never state the **sign/zero-extension rule for narrow (32/64-bit) GPR writes** into the 128-bit register. Only the 32-bit access *syntax* is given.
49. These sources never state whether the KSEG0 data cache is **direct-mapped**; only the `Config.K0` mode field and the `EntryLo` C-field table are given.

---

## Recompiler-relevant rules

Why a static recompiler must diverge from a dynamic emulator: the EE is **not** a stock MIPS core. It has 128-bit GPRs, a second accumulator pipeline, 80+ SIMD instructions, an attached vector coprocessor, a 48-entry TLB with a writable-cache-policy field, and non-standard cache-control behaviour. A `uint32_t reg[32]` MIPS translator, or an ISA table lifted from a generic MIPS III core, silently corrupts state.

### 1. Register width — the single highest-impact rule

- Model GPRs as **128-bit**, not 32 or 64. `uint128_t gpr[32]`. Narrow reads/writes go through a word view (`gpr[N].words[0]`), full-width through `gpr[N]`. — `01:24-25`, `db-isa.md:595-597`
- Model **four** accumulators, each 128-bit: `lo`, `hi`, `lo1`, `hi1`. Omitting `lo1`/`hi1` corrupts any MMI sequence — `MULT1`/`DIV1`/`MADD1` write a *different* accumulator pair from `MULT`/`DIV`/`MADD`. — `01:92`, `db-isa.md:197-206`
- **Do not assume a narrow write zero- or sign-extends.** The sources show only `words[0]` access syntax and never state the extension rule. Any codegen that infers "implicit zero-extend" from the struct layout is an unverified assumption; flag it. — `02:25-31`, `db-isa.md:597`, gap #48 above

### 2. Delay slots

- Every jump/branch has a one-instruction delay slot, and the slot instruction executes **before** the branch takes effect. For a call this means the slot instruction must execute **before the callee body** — the ordering is observable. — `02:65-75`
- Because translation target is C++, the delay-slot instruction of `jal sub_123456` must be emitted *above* the call to `sub_123456(ctx)`, not after it. — `02:71-75`
- The `BC0F/T`, `BC1F/T`, `BC2F/T` coprocessor branches exist and also have delay slots (they are branches in the decode tables), but their slot behaviour is `NOT STATED` in these sources. — `db-isa.md:339-345`, `402-408`, `462-468`
- `Cause.BD` / `Cause.BD2` exist precisely because instructions *in* delay slots can raise exceptions, and `EPC` is restored to the **branch**, not the slot. — `db-registers.md:407-408`, `555-561`

### 3. MMI

- Decode `0x1C` three levels deep: primary opcode → function [5:0] → sub-table selector [10:6] (`MMI0`=0x08, `MMI1`=0x28, `MMI2`=0x09, `MMI3`=0x29). A two-level MIPS decoder will mis-dispatch these. — `db-isa.md:7-12`, `195-196`, `207-208`
- MMI ops are **128-bit lane-parallel** (word/halfword/byte lanes) and must not be narrowed to 32/64-bit. Saturation ops (`PADDSW/H/B`), pack/extend pairs, and horizontal multiply-add (`PHMADH`/`PHMSBH`) have no scalar equivalent. — `db-isa.md:186-326`, `623-624`
- `PMFHL`/`PMTHL` are **variant instructions selected by the sa field [10:6]** — a single decode entry is wrong. — `db-isa.md:218-225`
- `LQ`/`SQ` are 128-bit memory ops and **must be 16-byte aligned or they raise SIGBUS**. Alignment faults must be modelled, not assumed away. — `db-isa.md:100`, `02:53`
- HI1/LO1 writes are semantically distinct from HI/LO writes; a recompiler that funnels `MULT1` into `MULT` is wrong. — `db-isa.md:613-616`

### 4. COP2 / VU0

- COP2 is not a floating-point coprocessor — it is **VU0 in Macro Mode, wired into the EE pipeline**. An unmapped `0x12` opcode cannot be stubbed as "FPU unavailable"; it is a vector-unit instruction. — `01:30`, `01:69`, `db-isa.md:450`
- `QMFC2`/`QMTC2` move **quadwords** (128 bits) between GPRs and VU0 vector registers; `LQC2`/`SQC2` move 128 bits between memory and VU0. — `db-isa.md:455-457`, `92`, `95`
- The `CO` space has **two sub-tables chosen by bit 0 of opcode2**. Emitting a single VU0 macro dispatcher keyed only on [5:0] will decode every Special2 op as its Special1 namesake (e.g. `VADDx` vs `VADDAx`, `VLQI` vs `VSQI`). — `db-isa.md:470`, `503`
- VU0 has **its own control-register file with a sparse numbering** (0–8 plus 20, 26–29). A contiguous 0–31 assumption mis-maps `ACC` (20) and `P` (26). — `db-isa.md:541-557`
- `02:62` states COP2 macro translation is "extremely difficult … usually requires figuring out the high-level matrix/vector operation". That is a **hand-patching note, not a specification** — it gives no per-opcode semantics.

### 5. MMU / TLB

- TLB is **48 entries**, indices 0–47, with a *random* replacement index that counts down every instruction and is constrained to `[Wired, 47]`. A static recompiler that never fills the TLB is fine; one that *does* must reproduce `Random` countdown or `TLBWR` targets will drift from hardware. — `db-registers.md:473-478`, `480-486`
- `EntryLo` has a **per-entry cache-policy field (C, bits 5:3)** with three legal values (2 uncached, 3 write-back + write-allocate, 7 uncached-accelerated) — there is no single global cache mode for TLB-mapped pages. — `db-registers.md:462-469`, `488-497`
- `EntryLo0` bit 31 **S** redirects the entry to Scratchpad RAM instead of the physical page. — `db-registers.md:471`, `492`
- Page size is **variable** (4 KB … 16 MB) via `PageMask`, so TLB refill/translate code must not assume 8 KB. — `db-registers.md:513-527`
- `EntryHi` carries an **8-bit ASID**; `G` must be set in *both* EntryLo0 and EntryLo1 to bypass ASID matching. — `db-registers.md:497`, `499-504`
- `EPC` must be set to the **branch address**, not the delay-slot address, when `BD=1`; and must not be updated when `EXL=1`. Getting this wrong corrupts exception return. — `db-registers.md:555-561`
- `ERL` **initialises to 1** on reset, so interrupts are masked until code clears it. A recompiler that assumes `ERL=0` at first exception will take phantom interrupts. — `db-registers.md:399`

### 6. Cache

- **`ICE` (bit 17) and `DCE` (bit 16) both initialise to 0** — caches are off at reset and must be enabled by software. — `db-registers.md:441-442`
- Cache **sizes** are reported in `Config` (`IC` = 16 KB, `DC` = 8 KB) independently of the enable bits; do not infer "cache active" from a non-zero size field. — `db-registers.md:445-446`
- Cache **policy** lives in `Config.K0` (bits 2:0, kseg0 mode; init **Undef**) and, for TLB pages, in `EntryLo.C`. There are two independent knobs; `Config.K0` init being "Undef" means the *hardware's* KSEG0 policy is not pinned by these sources. — `db-registers.md:447`, `462-469`
- `CACHE` is a real instruction (opcode 0x2F) with observable effect via `Status.CH` (bit 18) and `TagLo`/`TagHi` via `DXLTG/DXSTG/IXLTG/IXSTG`. A static recompiler may treat these as no-ops only if no game code reads back `Status.CH` or the tags. — `db-isa.md:89`, `db-registers.md:392`, `652-662`
- `DI`/`EI` are COP0 `CO` 0x39/0x38, gated by `Status.EDI` — but see Contradiction B5: the two COP0 tables in `db-registers.md` **swap the meanings of bits 16 and 17**. Do not implement `EDI` from either table until resolved. — `db-isa.md:355-356`, `db-registers.md:393-394` vs `db-registers.md:1245-1246`

### 7. Other emitter-relevant rules

- FPU is **single-precision only**; emitting a double-precision decoder path is dead code, and any D/L instruction seen in the wild is suspect. — `db-isa.md:388-389`
- `SYSCALL` (SPECIAL 0x0C) must be trapped, not emulated as a BIOS call — it is the syscall vector into the runtime. — `01:83-84`
- `MOVZ`/`MOVN` (SPECIAL 0x0A/0x0B) are conditional moves, not branches — they have **no delay slot**. — `db-isa.md:116-117`
- Branch-likely opcodes must be tagged `IS_LIKELY` at decode: `0x14` BEQL, `0x15` BNEL, `0x16` BLEZL, `0x17` BGTZL, REGIMM `0x02` BLTZL, `0x03` BGEZL, `0x12` BLTZALL, `0x13` BGEZALL, BC0 `0x02` BC0FL / `0x03` BC0TL, BC1 `0x02` BC1FL / `0x03` BC1TL, BC2 `0x02` BC2FL / `0x03` BC2TL. — `db-isa.md:63-66`, `169-170`, `179-180`, `342-345`, `405-408`, `464-468`

---

## Branch semantics

**Column meanings.** "Slot executes" = the instruction physically after the branch is retired before control transfers.
Every row's TAKEN/NOT-TAKEN cell is filled **only** where these four sources state behaviour. Cells reading `NOT STATED` are genuine gaps — see the Branch semantics row notes after the table.

| Branch form | Encoding | Slot executes when TAKEN | Slot executes when NOT TAKEN | R5900 erratum |
|---|---|---|---|---|
| `BEQ` | opcode `0x04`, I-type | Yes (`02:65`) | Yes (`02:65`, stated unconditionally) | none documented in corpus |
| `BNE` | `0x05` | Yes (`02:65`) | Yes (`02:65`) | none documented |
| `BLEZ` | `0x06` | Yes (`02:65`) | Yes (`02:65`) | none documented |
| `BGTZ` | `0x07` | Yes (`02:65`) | Yes (`02:65`) | none documented |
| `BEQL` | `0x14` | **NOT STATED** | **NOT STATED** — `02:65` states "jump/branch" with no exception, which contradicts the project fact if read as universal | none documented |
| `BNEL` | `0x15` | **NOT STATED** | **NOT STATED** (same as BEQL) | none documented |
| `BLEZL` | `0x16` | **NOT STATED** | **NOT STATED** (same as BEQL) | none documented |
| `BGTZL` | `0x17` | **NOT STATED** | **NOT STATED** (same as BEQL) | none documented |
| `BLTZ` | REGIMM RT `0x00` | Yes (`02:65`) | Yes (`02:65`) | none documented |
| `BGEZ` | REGIMM RT `0x01` | Yes (`02:65`) | Yes (`02:65`) | none documented |
| `BLTZL` | REGIMM RT `0x02` | **NOT STATED** | **NOT STATED** | none documented |
| `BGEZL` | REGIMM RT `0x03` | **NOT STATED** | **NOT STATED** | none documented |
| `BLTZAL` | REGIMM RT `0x10` | **NOT STATED** | **NOT STATED** (incl. whether `$ra` is written when not taken — `NOT STATED`) | none documented |
| `BGEZAL` | REGIMM RT `0x11` | **NOT STATED** | **NOT STATED** (same as BLTZAL) | none documented |
| `BLTZALL` | REGIMM RT `0x12` | **NOT STATED** | **NOT STATED** | none documented |
| `BGEZALL` | REGIMM RT `0x13` | **NOT STATED** | **NOT STATED** | none documented |
| `J` | `0x02`, J-type | Yes (`02:65` covers "jump") | N/A — unconditional | none documented |
| `JAL` | `0x03` | Yes (`02:65`); writes `$ra` (`db-isa.md:47`) | N/A — unconditional | none documented |
| `JR` | SPECIAL `0x08` | Yes (`02:65`) | N/A — unconditional | none documented |
| `JALR` | SPECIAL `0x09` | Yes (`02:65`) | N/A — unconditional | none documented |
| `BC0F` | COP0 `0x08` / cond `0x00` | **NOT STATED** | **NOT STATED** | none documented |
| `BC0T` | cond `0x01` | **NOT STATED** | **NOT STATED** | none documented |
| `BC0FL` | cond `0x02` (likely) | **NOT STATED** | **NOT STATED** | none documented |
| `BC0TL` | cond `0x03` (likely) | **NOT STATED** | **NOT STATED** | none documented |
| `BC1F` / `BC1T` | COP1 `0x08` / cond `0x00`,`0x01` | **NOT STATED** | **NOT STATED** | none documented |
| `BC1FL` / `BC1TL` | cond `0x02`,`0x03` (likely) | **NOT STATED** | **NOT STATED** | none documented |
| `BC2F` / `BC2T` | COP2 `0x08` / cond `0x00`,`0x01` | **NOT STATED** | **NOT STATED** | none documented |
| `BC2FL` / `BC2TL` | cond `0x02`,`0x03` (likely) | **NOT STATED** | **NOT STATED** | none documented |
| `ERET` | COP0 CO `0x18` | **NOT STATED** (whether it has a delay slot is `NOT STATED`) | **NOT STATED** | none documented |
| `SYSCALL` | SPECIAL `0x0C` | **NOT STATED** (its exception is ExcCode 8, `db-registers.md:428`) | — | none documented |
| `BREAK` | SPECIAL `0x0D` | **NOT STATED** (ExcCode 9, `db-registers.md:429`) | — | none documented |
| *(not branches)* `MOVZ` / `MOVN` | SPECIAL `0x0A` / `0x0B` | **No delay slot** — conditional *moves*, not branches (`db-isa.md:116-117`) | — | n/a |

**Errata — exact conditions.** The task brief expects a "short loop" erratum to be captured here. **It is not present in any of the four sources.** A case-insensitive search of the whole `resources/` tree for `errat`, `erratum`, `short loop`, `shortloop` returns **zero** hits; the only branch-slot statement outside these four files is `resources/db-ps2-architecture.md:138-139` ("Branch delay slot: always executed" / "Branch likely instructions: delay slot **nullified** if branch not taken"), which *agrees* with our project fact but is out of scope for this file. **Consequence: the exact conditions of the short-loop erratum are currently undocumented in this project and must be sourced from the EE Core User's Manual errata sheet before any erratum-dependent codegen is written.** Do not infer them from these files. — `source: grep over resources/ (0 matches)`

**Slot-existence evidence.** Even where behaviour is `NOT STATED`, the slot is architecturally real: `Cause.BD` is "set when a level 1 exception occurs in a delay slot" and `Cause.BD2` for NMI/PerfC/Debug in a delay slot, and `EPC` is restored to the *preceding branch*. — `db-registers.md:407-408`, `555-561`, `576-580`

---

## Contradictions

### A. Against our already-recorded project facts

**A1 — Branch-likely delay slot (CONTRADICTION BY OVER-GENERALISATION).**
- *Our verified fact*: "MIPS branch-likely nullifies its delay slot when the branch is NOT TAKEN (verified against the MIPS IV spec, Microsoft R4000 notes, Microchip PIC32 guide). PCSX2 tags them IS_LIKELY."
- *What the source says, verbatim*: `resources/02-mips-r5900-isa.md:65` — "MIPS has a **Branch Delay Slot**. The instruction immediately following a jump/branch is executed *before* the branch actually takes effect." (`## 3. Emulating Branch Delay Slots`, lines 64-76.)
- *The conflict*: `02-mips-r5900-isa.md` states the delay slot rule as **unconditional**, with no carve-out for likely branches. `resources/db-isa.md` names all twelve likely-branch encodings (`0x14` BEQL, `0x15` BNEL, `0x16` BLEZL, `0x17` BGTZL at `db-isa.md:63-66`; REGIMM `0x02` BLTZL, `0x03` BGEZL at `db-isa.md:169-170`; `0x12` BLTZALL, `0x13` BGEZALL at `db-isa.md:179-180`; BC0FL/BC0TL at `db-isa.md:344-345`; BC1FL/BC1TL at `db-isa.md:407-408`; BC2FL/BC2TL at `db-isa.md:467-468`) but **never says what happens to the delay slot of any of them.** `01-ps2-hardware-bible.md` and `db-registers.md` are silent on delay-slot nullification entirely.
- *Verdict*: **the sources do not refute the fact, they contradict it by asserting the general rule without exception.** Treat our fact as authoritative; treat `02:65` as incomplete. This is the single place where blindly trusting `02-mips-r5900-isa.md` would produce wrong codegen.

**A2 — GPR width (NO CONTRADICTION; a gap).**
- *Our verified fact*: "GPRs are 128-bit wide holding 64-bit values; a 32-bit write sign-extends or zero-extends depending on the operation."
- *What the sources say*: `01-ps2-hardware-bible.md:25` — "**Crucially, GPRs on PS2 are 128-bit wide**. Lower 64 bits are standard MIPS; upper 64 bits are used by Multimedia Instructions (MMI)." `db-isa.md:595` — "All GPRs are **128-bit wide**. Lower 64 bits are standard MIPS III; upper 64 bits used by MMI/parallel instructions."
- *Verdict*: the sources **confirm** the 128-bit width. They say **nothing** about the sign/zero-extension behaviour of a 32-bit write. That half of our fact is unverified here and remains an open item.

**A3 — EE virtual-memory segments (VAGUE, AND PARTIALLY INCONSISTENT).**
- *Our verified fact*: "EE virtual memory: KUSEG 0x00000000-0x7FFFFFFF, KSEG0 0x80000000-0x9FFFFFFF (cached, direct-mapped), KSEG1 0xA0000000-0xBFFFFFFF (uncached), KSEG2 >= 0xC0000000. KSEG0/KSEG1 translate with `addr & 0x01FFFFFF` (32 MB RDRAM)."
- *What the source says, verbatim*: `resources/01-ps2-hardware-bible.md:47` — "*Note: Addresses above `0x20000000` mirror the lower 512MB space with different cache configurations (kseg0, kseg1).*"
- *Conflicts*:
  1. The note places the mirroring threshold at **`0x20000000`**, not at the KSEG0 base `0x80000000`. Read literally, `0x80000000`-`0x9FFFFFFF` is simultaneously "kseg0" and a "mirror above 0x20000000" — the note cannot be reconciled with the standard segment map as a statement about where mirroring *starts*.
  2. It states **no mask**. The `addr & 0x01FFFFFF` rule has **no support in any of these four sources**. The only supporting datum nearby is the 32 MB RDRAM size at `01-ps2-hardware-bible.md:35`.
  3. The word **"direct-mapped"** (our KSEG0 claim) appears **nowhere** in these sources; the closest is the `Config.K0` cache-mode field and the `EntryLo` C-field table.
- *Verdict*: `01:47` is too vague to be a specification and its `0x20000000` threshold conflicts with the segment boundaries we already record. Our fact stands; this note must not be cited in its favour.

### B. Conflicts *between* these sources (do not silently pick one)

**B1 — `Status` bits 16 and 17 are SWAPPED between two COP0 tables in `db-registers.md`.**
- `db-registers.md:393-394`: `16 | EIE | Enable IE bit (0=all interrupts disabled regardless of IE)` and `17 | EDI | EI/DI instruction enable (0=Kernel only, 1=all modes)`.
- `db-registers.md:1245-1246`: `16 | EIE | EI/DI instruction Enable (R5900 extension)` and `17 | EDI | EI/DI valid in user mode`.
- The first table makes `EDI` a *mode gate* and `EIE` a *global interrupt gate*; the second makes `EIE` the `EI`/`DI` gate and `EDI` its user-mode extension. These are **not** the same register layout. This directly affects the PS2-only `EI`/`DI` instructions (`db-isa.md:355-356`). **Unresolved — needs the EE Core User's Manual.**

**B2 — `Count` clock rate is stated twice, differently, in the same file.**
- `db-registers.md:545`: "Count | Free-running timer, **increments every CPU clock cycle**".
- `db-registers.md:1218`: "9 | 0 | Count | Timer tick count (**halfclock**)".

**B3 — `Config` cache-size fields are at different bit positions in the same file.**
- `db-registers.md:445-446`: `11:9 | IC | I-cache size (010=16KB)` and `8:6 | DC | D-cache size (001=8KB)`.
- `db-registers.md:1309-1310`: `6:4 | DC | Data cache size (= 2^(12+DC) bytes, typically 6=8KB)` and `9:7 | IC | Instruction cache size (= 2^(12+IC) bytes, typically 6=16KB)`.
- The second table is additionally **internally inconsistent**: `2^(12+6) = 256 KB`, not the 8 KB it claims for `DC = 6`.

**B4 — `Config` bit 28 is two different things.**
- `db-registers.md:439`: `30:28 | EC | Bus clock ratio (000 = CPU/2)`.
- `db-registers.md:1316`: `28 | EC | Endian Config (0=little endian)`.

**B5 — `Cause` bit 10 is `IP[2]` in one table and `EXC2` in the other.**
- `db-registers.md:413-414`: `11:10 | IP[3:2] | Int[1:0] interrupt pending`, and `18:16 | EXC2` (`db-registers.md:410`).
- `db-registers.md:1262-1264`: `10 | EXC2 | Level 2 exception (R5900)`, `12:11 | — | Reserved`, `15:13 | IP[7:2] | Hardware interrupt pending`.

**B6 — Level-2 exceptions are described as an `EXC2` field and as `ExcCode` values.**
- `db-registers.md:410`: `18:16 | EXC2 | Level 2 exception code (0=Reset, 1=NMI, 2=PerfC, 3=Debug)`.
- `db-registers.md:1290-1293`: ExcCode table rows `0x12 RESET`, `0x13 NMI`, `0x14 PERF`, `0x15 DBG`.
- These are mutually exclusive encodings of the same events. The first table (`db-registers.md:416-433`) stops ExcCode at `13 Tr`.

**B7 — `Status.CU[3]`: "COP3 always unusable" vs "Reserved".**
- `db-registers.md:389`: "CU[3:0] | Coprocessor usability (0=unusable, 1=usable). COP0 always usable in Kernel. **COP3 always unusable**".
- `db-registers.md:1253`: `31 | CU[3] | **Reserved**`.

**B8 — VIF1 register range.**
- `01-ps2-hardware-bible.md:111`: VIF1 at "`0x10003C00-0x10003FFF`".
- `db-registers.md:22`: VIF1 is "`0x10003C00–0x10003DFF`" (and its highest register, VIF1_TOP, is `0x10003D30`).

**B9 — `PRId`: full register value vs implementation field (reconcilable, but pick one).**
- `db-isa.md:375`: "15 | PRId | Processor revision ID (**R5900 = 0x2E20**)" — a full 16-bit register value, implying `Rev = 0x20`.
- `db-registers.md:1300`: "15:8 | Imp | Implementation: `0x2E` = R5900 (EE)" and `db-registers.md:1299`: "7:0 | Rev | Revision (**varies**)".
- Not strictly contradictory (`0x2E20 = Imp 0x2E | Rev 0x20`), but a PRId comparison must know whether to expect the constant `0x2E20` or the field `Imp == 0x2E` with a chip-specific `Rev`.

*(No other file in this project was modified.)*
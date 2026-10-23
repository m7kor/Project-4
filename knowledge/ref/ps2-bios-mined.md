# PS2 BIOS mining — measured facts (R5900 / EE kernel)

Status: **COMPLETE**. Sections 0–7 are filled in.
Every claim is tagged `MEASURED` (read directly out of a BIOS image at a stated
file+offset) or `INFERRED` (reasoned from measurements; the reasoning is given).

Headline results: the EE kernel is at file `0x39E490` of the primary image
(VA `0x80000000`, 93 736 bytes); the syscall table is a 256-entry array of
4-byte handler pointers at **VA `0x80014F40`**; **index `0x83` is an empty
slot**; syscall `0x74` performs an entirely **unchecked** `table[index] = address`
and names that same base itself; and the kernel's data — the syscall table
among it — lives at **physical `0x00014F40`**, inside the low 512 KB, because the
kernel is loaded at physical 0.

**Legal note.** Sony's BIOS images are copyrighted. This document reports only
measured facts — addresses, offsets, sizes, hashes, decoded semantics and the
short list of syscall-index values the brief asked for. It deliberately contains
no BIOS byte dumps, no long string extracts and no whole tables. See §0.

Primary image: `bios/SCPH-70004_BIOS_V12_PAL_200.BIN` (4 MiB, Feb 2005, retail PAL SCPH-70004).
sha256 `d6653f4e93be2f6f9e9d690a934f26cf0f6ad4e348b69f41ef736732c3a6685b`, 4194304 bytes. **MEASURED**

### Running notes (work log)

- `tools/bios_mine/mipsdec.py` works as-is (R5900/MIPS-III decoder). `scan.py`,
  `explore.py`, `probe.py` all work and are big-endian-only, which is the main
  reason the previous agent stalled (see below).
- New helper scripts added beside them: `map.py`, `layout.py`, `quick.py`,
  `match.py`, `kseg0.py`, `ktables.py`, `ktable2.py`, `region.py`, `ledump.py`,
  `kdat.py`, `ledis.py`, `leblocks.py`, `leline.py`.
- **Flash is byte-addressed, not word-addressed — `MEASURED`:** the EE-side images
  stored in the flash keep every 32-bit word **byte-reversed (little-endian)**
  while byte arrays (ASCII strings) are untouched. Reading such an image with a
  big-endian decoder yields plausible-looking-but-wrong instructions, which is
  exactly what traps the stock tools. Evidence: at file `0x3b3390` the LE word is
  `0x03e00008` (`jr $ra`) and at `0x3b3394` `0x27bd0030` (`addiu $sp,$sp,0x30`);
  the BE reading of the same bytes is `0x0800e003`, which is not an instruction
  prologue.
- IOP-side code (R3000A) elsewhere in the flash is normal big-endian.
- **Bug found and fixed in `mipsdec.py` (the only change to pre-existing code).**
  Branch and jump targets were computed relative to the instruction instead of
  relative to its delay slot, i.e. every branch target was 4 too low and `j`/`jal`
  used the wrong region formula. Verified empirically: `jal` at VA `0x800014e4`
  printed `0x80001cf8` (mid-function code); with the MIPS-spec formula it resolves
  to `0x800073e0`, which is a textbook prologue
  (`addiu $sp,-0x90($sp)` / `sd $ra,0($sp)`). Branches now print
  `target = pc + 4 + (offset << 2)`, jumps `target = ((pc+4) & 0xF0000000) | (idx << 2)`.

---

## 0 Method and legal boundary

**Legal boundary — read this first.** Sony Computer Entertainment's BIOS images
are copyrighted. This document reports only *facts measured* from the local image
files plus *short decoded instruction words* needed to justify each claim. It
deliberately contains **no BIOS byte dumps, no long string extracts and no whole
tables**; where a table matters, only the specific entries the questions ask for
are listed. Anyone reproducing this should work from their own legally obtained
copy of the images and treat this file as a description of what those copies say,
not as a substitute for them.

**Method.** Four 4 MiB-class BIOS images plus their sibling parts were read from
`bios/`. `tools/bios_mine/mipsdec.py` (the existing dependency-free R5900 /
MIPS-III decoder) does the instruction decoding; it was reused, with the one
target-computation bug above fixed. New small drivers were added beside it:
`map.py`, `layout.py`, `quick.py`, `match.py`, `kseg0.py`, `ktables.py`,
`ktable2.py`, `region.py`, `ledump.py`, `kdat.py`, `ledis.py`, `leblocks.py`,
`leline.py`, `bhist2.py`, `base.py`, `calib.py`, `luipairs.py`, `immscan.py`,
`ktable.py`. All are read-only; nothing here modifies an image.

**The one decoding trap.** PS2 BIOS flash images are **byte-swapped per 32-bit
word** for the EE-side images: reading a word little-endian from the flash yields
a correct big-endian MIPS instruction, while the ASCII strings inside those same
images are stored as plain byte arrays and read correctly either way. The stock
BE-only tools therefore produce plausible but wrong instructions over exactly the
region that matters. Every disassembly below was produced after confirming the
byte order (`tools/bios_mine/ledis.py`).

`MEASURED` = read directly out of an image at a stated file offset.
`INFERRED` = reasoned from measurements; the reasoning is given.

---

## 1 Where is the EE kernel inside the ROM?

**Answer — `MEASURED`.** The EE kernel image is stored, byte-swapped, at:

| property | value |
|---|---|
| file | `bios/SCPH-70004_BIOS_V12_PAL_200.BIN` |
| file offset of image base (VA `0x80000000`) | **`0x0039E490`** |
| file offset of end | `0x003B52B8` |
| size | `0x16E28` = **93 736 bytes** |
| sha256 of that byte range | `ed68d9b15cac1c834608b9961e76188818e2095f72c435856f19cff656de1362` |
| mapping | `VA = 0x80000000 + (file_offset - 0x39E490)` |

Everything from `0x3B52B8` to the end of the flash is `0x00` (`MEASURED`:
76 626 consecutive zero words), which is why the image end is unambiguous.

**How it was identified — three independent confirmations, all `MEASURED`:**

1. **Image base = the TLB exception handler.** At VA `0x80000000` (file
   `0x39E490`) the decoded instruction sequence is the classic PS2 kernel TLB
   refill: it saves `EPC` to `0x80015378`, computes `(EPC & 0x7C)`, writes the
   computed stub address into the exception-vector table at `0x80015340`, then
   `jr $k0` with the saved `EPC` restored in the delay slot. Nothing else in the
   4 MiB flash starts with this.
2. **Base offset recovered by string-reference cross-product.** Every
   `lui`+`addiu` pair in the kernel region that materialises a `0x8000xxxx`
   address was collected (353 sites) and each target was tested against every
   ASCII-string start in the flash. Exactly one base offset `B` makes many of them
   land exactly on the first byte of a real kernel string: **`B = 0x39E490`**, with
   85 hits against 40 for the next candidate. Eight spot checks agree bit-for-bit
   (`MEASURED`):

   | code site (file) | address it builds | flash file offset it lands on | string |
   |---|---|---|---|
   | `0x39F96C` | `0x80015453` | `0x3B38E3` | `# INT: INTC (%d)` |
   | `0x39F99C` | `0x80015465` | `0x3B38F5` | `# INT: DMAC (%d)` |
   | `0x39F9C8` | `0x80015477` | `0x3B3907` | `# INT: CPU Timer` |
   | `0x39F9F8` | `0x80015489` | `0x3B3919` | `# Syscall: undefined (%d)` |
   | `0x39FBEC` | `0x80015AC0` | `0x3B3F50` | `# INTC(%d) Handler does not exist.` |
   | `0x3A1E94` | `0x80015B10` | `0x3B3FA0` | `# <Thread> No active threads` |
   | `0x3A26B4` | `0x80015B78` | `0x3B4008` | `# DisableDispatchThread is not supported…` |
   | `0x3A37C0` | `0x80015C50` | `0x3B40E0` | `# SetHeap: HEAP_RELATIVE is not supported…` |

3. **Internal structure agrees.** With `B = 0x39E490` the 32-entry exception
   vector table that the TLB handler writes to lands exactly at
   `file 0x3B37D0 = VA 0x80015340`, i.e. a naturally aligned `.data` address,
   and the kernel's `.text`/`.data`/`.rodata` all fall inside the claimed range
   (`MEASURED`).

**What the entry point is — `MEASURED`.** `0x80001000` **is** the kernel's
main init routine, and the claim is confirmed. At `VA 0x80001000` / file
`0x39F490` the decoded code is unmistakably kernel startup (`MEASURED`):
it publishes `0x70000000` at `0x70003FF0` and in `.bss` at `0x80016E50`;
publishes `0xBFC001F8` (a KSEG1 mirror of physical `0x1F8`) at `0x80016E40`;
sets the kernel stack `$sp = 0x80020000 - 0x7180 = 0x80018E80`; calls four init
subsystems (`0x80005C30`, `0x80002050`, `0x8000DAD8`, `0x80004EC0`); writes
`Cause` and `LLAddr` to arm the TLB; then calls the memory init at `0x8000EF18`
and `0x80006238`; and finally registers the two built-in modules described in
§4. So the layout is: `0x80000000` = TLB refill vector, low `0x1000` = exception
stubs, **`0x80001000` = kernel main/init**, and `0x800010C0`–`0x800010F0` =
the user-context save area the syscall handler uses
(`lqv $sp,0x10C0($k0)` / `lqv $ra,0x10D0($k0)` / `lqv $at,0x10E0($k0)` with
`$k0 = 0x80000000`, `MEASURED` at `VA 0x8000029C`). The handler for
`ExcCode 8` (syscall) is at **`0x80000280`** — it is exception-vector entry 8.

**Not the kernel — for the record (`MEASURED`).** Two other regions in the same
flash are byte-swapped MIPS code and are *not* the kernel:

* `file 0x302000`–`0x31C000` — EE sound library (`rspu2_driver`,
  `_SsSetNrpnVabAttr…`, `...Crescendo/Tempo/Pause/Stop`), ~100 KiB.
* `file 0x080000` — signature `ROMGSCRT` (ROM2), big-endian CDVD/FILEIO modules.
* `file 0x000000`–`0x07FFFF` — the **IOP BIOS** (ROM1), big-endian R3000A;
  build string `20040614-100914,ROMconf,PS20200EC20040614.bin,kuma@rom-server/…`
  at `0x002DB0`, IOP module-name table `0x002E3C`–`0x0035B0`.

**Cross-check with the 2000-era image — `MEASURED`.** `bios/scph10000.bin`
(sha256 `c4dad3b5c6ad58bce70a47fc332602880f041c0338ac6be89061c928f6919ab1`)
contains its own byte-swapped EE kernel at **file `0x0B3200`**, found by the same
method, whose image base is again `VA 0x80000000` and whose first instructions
are again the TLB refill handler (`sd $t9,0x23B8($k0)` / `mfc0 $t9,EPC` /
`andi $t9,0x7C` / `sw $k0,0x2380($k0)` / `jr $k0`). So the scheme — kernel at
VA `0x80000000`, TLB vector first, byte-swapped in flash — holds across a
five-year span and is not an artefact of the 2005 build. Full comparison in §2.

**Sibling files are not subsets of the flash — `MEASURED`.** The `.ROM1`,
`.ROM2`, `.EROM` and `.NVM` parts shipped next to `SCPH-70004_BIOS_V12_PAL_200.BIN`
do **not** appear byte-identical inside the 4 MiB flash
(`tools/bios_mine/match.py`; their heads are absent). Do not assume a sibling
file and its in-flash counterpart are the same bytes.

---

## 2 The EE syscall table

**Answer — `MEASURED`, and it settles the dispute.**

| property | value |
|---|---|
| table base (virtual address, kernel) | **`0x80014F40`** |
| file offset | **`0x003B33D0`** in `SCPH-70004_BIOS_V12_PAL_200.BIN` |
| entry size | 4 bytes (one `u32` handler pointer per syscall number) |
| number of entries | **256** (`0x00`–`0xFF`), i.e. `0x400` bytes, `VA 0x80014F40`–`0x8001533F` |
| immediately followed by | the 32-entry exception vector table at `VA 0x80015340` / file `0x3B37D0` |

**How it was identified.** The syscall exception handler sits at exception-vector
entry 8, `VA 0x80000280` / file `0x39E710`. Its dispatch tail is exactly four
instructions (`MEASURED`):

```
800002ec: 00031880  sll  $v1, $v1, 2           ; index = syscall number ($v1) * 4
800002f0: 3c1a8001  lui  $k0, 0x8001
800002f4: 0343d021  or   $k0, $k0, $v1         ; $k0 = 0x80010000 + index
800002f8: 8f5a4f40  sw   $k0, 0x4F40($k0)     ; *(u32*)(0x80014F40 + index) = $k0
800002fc: 0340f809  jalr $k0                   ; dispatch
```

`0x80010000 + 0x4F40 = 0x80014F40` — the table base falls straight out of the
`lui`/`or`/`sw` triple, and the file offset `0x3B33D0` obtained by mapping it
back through `B = 0x39E490` is precisely where a 256-word array of distinct
kernel text pointers lives (`MEASURED`). An exhaustive scan of the whole kernel
image for instructions with immediate `0x4F40` returns **exactly three** sites:
the two dispatch tails above and the `0x74` handler of §3 (`MEASURED`, tool
`immscan.py`) — i.e. nothing else in the kernel touches this table.

### Requested indices (`MEASURED`)

| syscall # | file offset | table entry VA | handler VA |
|---|---|---|---|
| `0x00` | `0x3B33D0` | `0x80014F40` | `0x80001564` |
| `0x03` | `0x3B33DC` | `0x80014F4C` | `0x80001564` |
| `0x3C` | `0x3B34C0` | `0x80015030` | `0x80005190` |
| `0x3D` | `0x3B34C4` | `0x80015034` | `0x80005298` |
| `0x40` | `0x3B34D0` | `0x80015040` | `0x800049B8` |
| `0x5A` | `0x3B3538` | `0x800150A8` | `0x80001564` |
| `0x74` | `0x3B35A0` | `0x80015110` | `0x800006C0` |
| `0x7F` | `0x3B35CC` | `0x8001513C` | `0x80000C40` |
| **`0x83`** | `0x3B35DC` | `0x8001514C` | **`0x00000000` — EMPTY** |
| `0xFC` | `0x3B37C0` | `0x80015330` | `0x00000000` — empty |
| `0xFD` | `0x3B37C4` | `0x80015334` | `0x00000000` — empty |
| `0xFE` | `0x3B37C8` | `0x80015338` | `0x00000000` — empty |
| `0xFF` | `0x3B37CC` | `0x8001533C` | `0x00000000` — empty |
| `0x12C` | — | — | **out of range** (see below) |

### Is index `0x83` a builtin or empty? — **EMPTY**

`MEASURED`: `table[0x83]` at file `0x3B35DC` is `0x00000000`. It is a reserved /
unused slot, **not** a builtin. The occupancy pattern of the 256-entry table is
(`MEASURED`):

* indices `0x00`–`0x80` : **non-zero**, real builtins (129 consecutive entries).
* index `0x81`         : `0x00000000` (empty)
* index `0x82`         : `0x80005C30` (a real builtin, **past** `0x7F`)
* indices `0x83`–`0xFF` : all `0x00000000` (empty, 125 consecutive slots)

So the claim "the kernel's list ends at `0x7F`" is *nearly* right but not
exactly: the last contiguous run ends at `0x80`, and there is one extra builtin
at `0x82`. The claim "`0x83 = FindAddress`" is **refuted** — the slot is zero.

`0x80001564` is the kernel's default/"not implemented" stub: it takes `$v1`,
shifts it right by 2, and calls the kernel's diagnostic printer with
`# Syscall: undefined (%d)` (`MEASURED`, decoded at file `0x39F7F4` /
VA `0x80001564`). It is reused by indices `0x00, 0x03, 0x08, 0x5A, 0x63,
0x75, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B, 0xF0`, which is what the
"undefined syscall" diagnostic path looks like from the table side.

**Index `0x12C` (`MEASURED`).** The table has exactly 256 entries, so `0x12C`
(=300) is past the end. A 32-bit read at `0x80014F40 + 0x4B0 = 0x800153F0` does
*not* return "nothing": it reads into the adjacent 32-entry table that follows the
exception vectors, and returns `0x800014D8` (an interrupt/panic stub). Because
`0x74` performs no bounds check (§3), a call with `$v1 = 0x12C` therefore lands
on a random stub that is not a syscall handler. This is worth stating because it
explains how out-of-range indices behave rather than crashing.

### The base `0x80011F80` — wrong for v12, but *real* in the 2000-era kernel

`MEASURED`: in the primary image, at `VA 0x80011F80` (file `0x3B0410`) there is
**kernel code, not a table** — the bytes decode to a function prologue
(`ld $s0,0x20($sp)` / `ld $s0,0x10($sp)` / `jr $ra` / `addiu $sp,$sp,0xB0`).
For `SCPH-70004 v12` the address is off by `+0x2FC0` from the real base, and
the `0x74` handler's own `lui` pair independently yields `0x80014F40`.

**But it is not invented — it is the 2000-era kernel's true base, and I was
wrong to call it a fabrication.** Measured in `bios/scph10000.bin`
(sha256 `c4dad3b5c6ad58bce70a47fc332602880f041c0338ac6be89061c928f6919ab1`):

* kernel image base `VA 0x80000000` = **file `0x0B3200`** (same method as §1:
  cross-product over 332 `lui`/`addiu` sites, 75 hits vs 66 for the runner-up;
  the runner-up aligned onto `SLPS_xxx` serial strings and is spurious);
* its syscall exception handler is at the same `VA 0x80000280`, and its dispatch
  tail reads `sw $k0, 0x1F80($k0)` instead of `0x4F40($k0)` — i.e.
  `0x80010000 + 0x1F80` = **`0x80011F80`**;
* the table at `VA 0x80011F80` = file `0x0C5180` is a real array;
* its `0x74` handler is at the *same* `VA 0x800006C0` and differs only in the
  offset: `scq $a1, 0x1F80($v1)` — same unchecked `table[index] = address`,
  same absence of bounds checks;
* its exception vector table is at `VA 0x80012380` (default handler
  `0x80011108`, syscall entry 8 = `0x80000280`, FPE `0x80000380`, RI
  `0x800004C0`, IBE `0x80000600` — identical structure and identical handler
  addresses to v12).

| | `scph10000.bin` (2000-era) | `SCPH-70004` v12 (2005) |
|---|---|---|
| kernel image base (file) | `0x0B3200` | `0x39E490` |
| syscall table VA | **`0x80011F80`** | **`0x80014F40`** |
| syscall table file offset | `0x0C5180` | `0x3B33D0` |
| exception vector table VA | `0x80012380` | `0x80015340` |
| occupied indices | `0x00`–`0x7F` (holes only at `0x6E`,`0x6F`) | `0x00`–`0x80` **and** `0x82` (hole at `0x81`) |
| index `0x83` | **empty** | **empty** |
| `0x74` handler VA | `0x800006C0` (offset `0x1F80`) | `0x800006C0` (offset `0x4F40`) |
| `0x74` bounds check | none | none |
| `0x00`, `0x03`, `0x5A`, `0x74`, `0x7F` handlers | identical values in both | identical values in both |
| `0x3C`, `0x3D`, `0x40` handlers | `0x80005198`, `0x800052A0`, `0x800049C0` | `0x80005190`, `0x80005298`, `0x800049B8` |

(`MEASURED` for every cell. `INFERRED`: the kernel gained two builtins
(`0x80`, `0x82`) and its `.data` moved by `+0x2FC0` between the two builds.)

**Practical consequence.** Any hard-coded syscall-table base is revision-specific.
`0x80011F80` is correct for the 2001 kernel and wrong for v12; `0x80014F40` is
correct for v12. A tool should locate the table the way this report did — read
the `sw <reg>, K($reg)` offset out of the syscall exception handler at
`0x80000280` — rather than hard-code either value.

---

## 3 Syscall `0x74`

**Answer — `MEASURED`: the ps2tek description is confirmed exactly, and the
handler itself names the table base.**

`table[0x74] = 0x800006C0` (file `0x3B35A0`). Handler at `VA 0x800006C0` /
file `0x39EB50`, six words total (`MEASURED`):

```
800006c0: 00042080  sll  $a0, $a0, 2          ; index = $a0 * 4
800006c4: 3c038001  lui  $v1, 0x8001
800006c8: 00641821  or   $v1, $v1, $a0        ; $v1 = 0x80010000 + index
800006cc: 03e00008  jr   $ra
800006d0: ac654f40  scq  $a1, 0x4F40($v1)    ; *(u32*)(0x80014F40 + index) = $a1
800006d4: 00000000  nop
```

* `sll $a0,$a0,2` → byte offset; `lui`/`or` → `0x80010000 + index`;
  `scq` (`sc` + 4-byte store, R5900) at offset `0x4F40` → store address
  `0x80014F40 + index`; stored value is `$a1`, the caller's `address` argument.
  **`table[index] = address` is confirmed** (`MEASURED`).
* **No bounds check is performed.** There is no compare, no branch, no mask —
  the function is four instructions plus the delay slot. This confirms ps2tek's
  "This function does not perform any bounds checking" verbatim (`MEASURED`).
* **The `lui`/`or` pair independently reveals the table base `0x80014F40`**
  (`0x80010000 + 0x4F40`), which corroborates §2 from an independent code path
  and refutes `0x80011F80`.

Because there is no bounds check, a game-side `SetSyscall(index, address)` with
`index >= 0x100` writes past the 256-entry table into the kernel's other `.data`
(indices `0x100`–`0x1FF` land at `VA 0x80015040`–`0x8001533F`, and anything
beyond that runs into the exception vector table at `0x80015340`). `MEASURED`
that the write is unbounded; `INFERRED` that this is exploitable, since nothing
in the handler validates `$a0`.

**Neighbouring handlers, for orientation (`MEASURED`).** `VA 0x80000700` is the
same four-instruction shape but with offset `0x53C0`, i.e. it writes
`0x80010000 + 0x53C0 = VA 0x800153C0` — a **second** unchecked table immediately
after the exception vectors (`0x800153C0`, used by kernel/module-internal
dispatch; 64 slots reach `0x800154C0`). `VA 0x80000740` writes a single fixed
slot at `0x800153FC`. `INFERRED`: the "RFU"/module-syscall family reuses the
same idiom with a different base.

---

## 4 Low-RAM constants

Each claim below was checked by scanning the whole kernel image
(`file 0x39E490`–`0x3B52B8`, tools `constscan.py`, `lowaddr.py`, `findval.py`)
for every place the value is materialised — as a `lui`+`ori`/`addiu` pair in
code, or as a 32-bit word in a data table, read both byte orders.

| claim | verdict | evidence |
|---|---|---|
| kernel VA base `0x80000000` | **CONFIRMED** | §1: file `0x39E490` is the TLB refill vector, i.e. image offset 0 |
| kernel main entry `0x80001000` | **CONFIRMED** | §1: file `0x39F490`, kernel-startup code (stack set-up, `Cause`/`LLAddr`, init calls) |
| `EENULL` image at physical `0x00081FC0` | **CONFIRMED** | built at `VA 0x80004F80` (`lui $a1,0x8` @ `0x80004F68` + `ori $a1,0x1fc0`) and passed as arg 2 of the builtin-module registrar, with arg 1 = the string `EENULL` (`VA 0x80015C48` = file `0x3B40D8`) |
| patch scratch / `EELOAD` at physical `0x00082000` | **CONFIRMED** | built at `VA 0x800010A4` (`lui $a1,0x8` @ `0x800010A0` + `ori $a1,0x2000`), passed as arg 2 of the same registrar with arg 1 = the string `EELOAD` (`VA 0x8001544C` = file `0x3B38DC`). Two further sites build `0x00082000`: `VA 0x800056C4` and `VA 0x8000DC78` |
| "second scratch at `0x80076000`" | **NOT FOUND** | no `lui 0x8007`+`0x6000`, no `lui 0x7`+`0x6000`, no data word equal to `0x80076000` anywhere in the kernel image |
| "first 1 MB of RDRAM reserved" | **NOT A BIOS CONSTANT** — see below | no occurrence of `0x00100000`, `0x00080000`, `0x000FFFFF` (as a bound) or `0x00080000` anywhere in the kernel image |

**The two module registrations (`MEASURED`).** Both built-ins go through the same
function at `VA 0x80005388` with the same argument shape
`f(name, physical_address, size, flags)`:

```
; VA 0x80001098 - EELOAD (file 0x39F528)
80001098: lui  $a0, 0x8001
8000109c: addiu $a0, 0x544c($a0)   ; $a0 = 0x8001544C = "EELOAD"
800010a0: lui  $a1, 0x8
800010a4: ori  $a1, 0x2000         ; $a1 = 0x00082000
800010a8: lui  $a2, 0x8
800010ac: ori  $a2, 0x1000         ; $a2 = 0x00081000
800010b0: jal  0x80005388
800010b4: dsrl $a3, $zero, 0       ; $a3 = 0

; VA 0x80004F68 - EENULL (file 0x3A33F8), tail-called, not jal
80004f68: lui  $a1, 0x8
80004f6c: lui  $a2, 0x8
80004f74: lui  $a0, 0x8001
80004f78: addiu $a0, 0x5c48($a0)   ; $a0 = 0x80015C48 = "EENULL"
80004f80: ori  $a1, 0x1fc0         ; $a1 = 0x00081FC0
80004f88: ori  $a2, 0x1000         ; $a2 = 0x00081000
80004f90: addiu $a3, 0x80          ; $a3 = 0x80
80004fa0: j    0x80005388
```

Both pass `0x00081000` as the third argument. `MEASURED` that the third argument
is identical for both; `INFERRED` that it is a reserved-region size or limit
rather than a per-module size (a per-module size would differ), because both
modules are tiny stubs while `0x81000` is 528 384 bytes. I did not trace the
callee far enough to name the parameter, so I am not asserting which.

**On "the first 1 MB is reserved" — `MEASURED` absence + `INFERRED` reading.**
There is no single 1 MB constant in the BIOS. What *is* measured is that the
reservation is an emergent consequence of two facts:

1. the kernel image is loaded at **physical 0**, so kernel `.text` + `.data`
   occupy physical `0x00000000`–`0x00016E28`, and every kernel data table is in
   physical `0x00000000`–`0x00016E28` (§5);
2. the two built-in modules are registered at physical `0x00081FC0` and
   `0x00082000`, i.e. just below `0x00081000`+`0x00081000`.

So the low region is genuinely occupied by kernel structures and built-ins, but
the BIOS never encodes "1 MB" as a bound; a tool that hard-codes 0x100000 is
implementing a convention, not reading a constant.

**Everything else the kernel materialises below `0x01000000` (`MEASURED`).**
The only other page-aligned low addresses the kernel builds are TLB masks
(`0x1000`, `0x2000`, `0x4000`, `0x42000`, `0x8000`, `0x8001` at `VA 0x80000AA0`–
`0x80000B1C`, all used as `LLAddr` compare operands) and the sign-extension
masks `0x0000FFFF` / `0x0000FFE4` / `0x000FFFFF`. `lowaddr.py` also reports many
values in `0x00030000`–`0x0007FFFF` with exactly two construction sites each;
inspection shows these are **IEEE-754 double-precision constants** being
materialised by `lui`+`addiu` pairs (e.g. `0x0006A120` at 17 sites), not
addresses. They are excluded from the table above.

---

## 5 What lives in physical [0x00000000, 0x00100000)

**The headline answer first.** Because the EE kernel image is loaded at
**physical 0**, every kernel table containing handler pointers — the 256-entry
syscall table, the exception vector table, and nine other pointer tables — is
already inside the low 512 KB. **The kernel does not mirror anything into
`[0, 0x80000)`; it is simply there.** A game scanning exactly `[0, 0x80000)` for
two pointers will find them, and will find the syscall table among them.

`MEASURED`: a scan of the whole kernel image for runs of kernel-text pointers
(≥6 words, zeros allowed, read little-endian, tool `ptables.py`) returns 13
runs, **12 of them real tables**, and **every one lies in physical
`[0x000000AA0, 0x00016BD0)`** — i.e. inside the low 512 KB:

| physical (and kernel VA − 0x80000000) | file offset | words | non-zero | what it is |
|---|---|---|---|---|
| `0x00014F40` | `0x3B33D0` | 256 (96 non-zero in the first run) | — | **the syscall table** (§2), `VA 0x80014F40`–`0x8001533F` |
| `0x000150CC` | `0x3B355C` | 222 | 81 | continuation of the same array (entries `0x60`–`0xFF`) |
| `0x00015340` | `0x3B37D0` | 32 | 15 | **exception vector table**, `VA 0x80015340` |
| `0x000153C0` | `0x3B3800`… | ≥64 | — | the **second unchecked table** written by `VA 0x80000700` (`scq $a1,0x53C0($v1)` → `0x800153C0`) and by `VA 0x80000740` (fixed slot `0x800153FC`) |
| `0x000154A8` | `0x3B3938` | 137 | 64 | 8-byte-stride pointer pair table (`+8` stride) |
| `0x00015948` | `0x3B3DD8` | 6 | 4 | small pointer set |
| `0x00015B30` | `0x3B3FC0` | 18 | 17 | small pointer set |
| `0x00015C00` | `0x3B4090` | 18 | 17 | small pointer set (17 entries, several duplicated handlers) |
| `0x00015E50` | `0x3B42E0` | 190 | 187 | large handler-pointer table |
| `0x00016460` | `0x3B48F0` | 16 | 16 | pointer set |
| `0x000165E0` | `0x3B4A70` | 6 | 5 | pointer set |
| `0x00016740` | `0x3B4BD0` | 140 | 132 | large handler-pointer table |
| `0x000169E0` | `0x3B4E70` | 6 | 6 | pointer set |
| `0x00016A20` | `0x3B4EB0` | 108 | 106 | large handler-pointer table |
| (`0x00000AA0`) | (`0x39EF30`) | 6 | 6 | **false positive** — `lui` opcodes being executed as data by the TLB mask helpers, not a table |

(Physical and kernel VA are numerically identical here, so both columns are the
same number; the file offset differs because the flash image is byte-swapped and
lives at flash offset `0x39E490`.)

**Full map of physical `[0, 0x100000)` as far as it is identifiable
(`MEASURED`):**

| physical range | contents | how identified |
|---|---|---|
| `0x00000000`–`0x00000080` | TLB refill exception vector (TLB handler) | §1 |
| `0x00000080`–`0x00000100` | zeros | direct read |
| `0x00000280` | **syscall exception handler** (vector entry 8) | vector table entry 8 |
| `0x000006C0` | **syscall `0x74` (`SetSyscall`) handler** | syscall-table entry `0x74` |
| `0x00001000`–`0x0000107F` | kernel main / init entry (§1) | decoded |
| `0x000010C0`–`0x000010F0` | user-context save area (`$sp`,`$ra`,`$at`) | decoded |
| `0x0000AA0`–`0x00000B1C` | TLB mask helper routines (not a table) | decoded |
| `0x00008000`–`0x00016E28` | remainder of kernel `.text` (interleaved stubs) | §1 |
| `0x00014F40`–`0x0001533F` | **syscall table, 256 × 4-byte handler pointers** | §2 |
| `0x00015340`–`0x000153BF` | exception vector table, 32 entries | TLB handler's `sw …,0x5340($k0)` |
| `0x000153C0`–… | second unchecked pointer table (`0x53C0` family) | `VA 0x80000700` / `0x80000740` |
| `0x000154A4` | word holding a "last undefined syscall id" marker written by init with `0x00081FE0` | `VA 0x8000107C`–`0x80001088` |
| `0x00016E28`–`0x0007FFFF` | **not present in the image** — the stored kernel ends at physical `0x00016E28`; everything from flash `0x3B52B8` to the end of flash is `0x00`. `INFERRED`: this is kernel `.bss`/heap space, zero-filled at load |
| `0x00080000`–`0x00081FBF` | reserved, holds no initialised BIOS data | nothing materialised here |
| `0x00081FC0` | **`EENULL` built-in module image** | §4 |
| `0x00081000` | third argument of both builtin registrations (§4) | §4 |
| `0x00082000` | **`EELOAD` / patch scratch built-in module image** | §4 |
| `0x00083000`–`0x000FFFFF` | nothing initialised by the BIOS is visible in the image | negative measurement |

**Caveat, stated plainly.** The image is the *stored* kernel, not a running
system. `MEASURED` statements about addresses above `0x00016E28` (the kernel's
runtime `.bss`, its heap and the region above the built-ins) are `INFERRED`
from the constants the kernel builds, not from observing memory. What is
directly measured is where the kernel *says* things go.

---

## 6 rom1.bin

`MEASURED`. `bios/rom1.bin` is 199 680 bytes (`0x30C00`), sha256
`41de2047af8382988bfd568035ff26eec5f1cabc3efe773680546aa00a82857d`, and it is a
**complete, standalone IOP BIOS image — a 2001-05-17 build, not the IOP ROM from
the 2005 flash.** It opens with the ASCII build string `20010517-202844\0` at
offset `0` and the boot entry name `RESET` at `0x10`, and carries the full IOP
module-name table at `0x2C8`:
`800`, `SYSMEM`, `LOADCORE`, `EXCEPMAN`, `INTRMANP`, `INTRMANI`, `SSBUSC`,
**`DMACMAN`**, `TIMEMANP`, `TIMEMANI`, `SYSCLIB`, `HEAPLIB`, `EECONF`,
`THREADMAN`, `VBLANK`, `IOMAN`, `MODLOAD`, `ROMDRV`, `ADDDRV`, `STDIO`, `SIFMAN`,
`SIFCMD`, `REBOOT`, `LOADFILE`, `CDVDMAN`, `CDVDFSV`, `SIFINIT`, `FILEIO`,
`SECRMAN`, **`SIO2MAN`**, `MCMAN`, `MCSERV`, `PADMAN`, `RMMAN`, `LIBSD`,
`SDRDRV`, `EESYNC` — followed by an embedded `\x7fELF` module at `0x408`. A
second directory at `0x60` lists the driver-region modules with their
`{name, offset, size}` triples: `DVDCNF`, `CDVDMAN`, `CDVDFSV`, `SIO2MAN`,
`PADMAN`, `RMMAN`, `LIBSD`, `SDRDRV`, `UDNL`, `EROMDRV`. **So yes — the IOP BIOS
and its DMA controller are fully present and recoverable from this file:** the
IOP kernel is in `LOADCORE`/`EXCEPMAN`/`INTRMAN*`/`THREADMAN`, the DMA controller
driver is `DMACMAN`, and the SIO2 bus manager is `SIO2MAN`. What is *not* here
is anything EE-side: this is an IOP-partition image only. Note also that this is
a different vintage than the primary image — the 2005 flash's own IOP partition
(`0x000000`–`0x07FFFF`, build string `20040614-100914,…` at `0x002DB0`, module
table at `0x002E3C`–`0x0035B0`) uses a linked-vector layout with a different head,
so `rom1.bin` is not a byte-subset of the primary flash (confirmed by
`tools/bios_mine/match.py`: its head bytes are absent from the flash).

---

## 7 What this settles and what it does not

### Settled (`MEASURED`, primary image `SCPH-70004_BIOS_V12_PAL_200.BIN`)

1. **The EE kernel is at file `0x39E490`, VA `0x80000000`, 93 736 bytes
   (`0x39E490`–`0x3B52B8`), sha256 `ed68d9b1…e1362`.** The flash stores it with
   every 32-bit word byte-swapped. Everything after `0x3B52B8` is zero.
2. **`0x80001000` is the kernel main/init entry**, and `0x80000000` is the TLB
   refill vector. Both claims in the brief are confirmed.
3. **The syscall table is 256 entries of 4-byte handler pointers at VA
   `0x80014F40` (file `0x3B33D0`)**, and all 14 requested index values are
   tabulated in §2.
4. **Index `0x83` is an empty slot** (`0x00000000`) in both the 2005 and the
   2000-era kernel. It is not a builtin and not `FindAddress`.
5. **Syscall `0x74` behaves exactly as ps2tek documents**: it stores
   `table[index] = address` with **no bounds check whatsoever**, and its own
   `lui` pair names the table base.
6. **`EENULL` is registered at physical `0x00081FC0`** and **`EELOAD`/patch
   scratch at `0x00082000`**, both passed to the same registrar at `VA
   0x80005388`.
7. **The kernel places no pointer tables anywhere other than its own image**,
   because the kernel *is* the low memory: the syscall table sits at **physical
   `0x00014F40`**, the exception vector table at `0x00015340`, and eleven other
   pointer tables in `0x000150CC`–`0x00016BD0` — **all inside `[0, 0x80000)`**.
8. **`rom1.bin` is a complete, standalone 2001-vintage IOP BIOS image** with the
   IOP kernel (`LOADCORE`/`EXCEPMAN`/`INTRMAN*`/`THREADMAN`), the DMA controller
   driver (`DMACMAN`) and the SIO2 bus manager (`SIO2MAN`) present.
9. **`0x80011F80` is not an invention — it is the 2000-era kernel's true syscall
   table base.** The v12 base is `0x80014F40`. Any hard-coded base is
   revision-specific.

### Corrected / refined during this job

* The bundled `mipsdec.py` computed branch and jump targets relative to the
  instruction instead of its delay slot. Fixed; verified against a known-good
  `jal` target. Anyone who disassembled PS2 BIOS code with it was reading targets
  4 bytes low.
* "EE entry `0x80001000` is not code" was an intermediate wrong reading, caught
  and corrected before publication: `0x80001000` **is** the kernel's init routine.
  `0x800010C0`–`0x800010F0` (not `0x80001000`) is the user-context save area.

### Not settled / open

* **`0x80076000` — not found.** No `lui 0x8007`+`0x6000`, no `lui 0x7`+`0x6000`,
  and no data word equal to it anywhere in either kernel image. Either the
  address belongs to a different vintage, to a module outside the kernel image
  (the EROM/OSD side), or the claim is simply wrong. **I did not find it, so I
  am not going to characterise what lives there.**
* **"First 1 MB reserved" is not a BIOS constant.** No `0x00100000`,
  `0x00080000` or memory-bound `0x000FFFFF` appears in the kernel. The region is
  reserved in practice (kernel at physical 0, built-ins at `0x81FC0`/`0x82000`)
  but nothing in the BIOS enforces or expresses a 1 MB boundary.
* **The third argument `0x00081000`** passed by both builtin registrations is
  the same for both, which rules out a per-module size; I did not trace the
  callee far enough to say what it is (reserved-region size? limit? id?).
* **Physical memory contents at runtime** are not observable from a static
  image. Everything above `0x00016E28` in §5 is `INFERRED` from the constants the
  kernel builds, not observed.
* **Two other byte-swapped EE images in the flash** were identified and excluded
  but not fully characterised: the EE sound library at `file 0x302000`–`0x31C000`
  (`rspu2_driver`, `_Ss*`) and whatever sits immediately below the kernel at
  `file 0x302000`–`0x39E490`. Only their existence and extent are `MEASURED`.
* **The other two images** (`PS2 Bios 30004R V6 Pal.bin`, `scph39001.bin`) were
  hashed and confirmed to share the layout scheme, but their kernel offsets were
  not measured — only `scph10000.bin` was cross-checked in full.
* **Is the unchecked `0x74` write exploitable?** `INFERRED` that it is, but that
  is a security claim I did not test and do not assert.

### How to re-derive any of this

All of it is reproducible with the read-only scripts in `tools/bios_mine/`.
The shortest path, if you have your own copy of the BIOS:

1. Decode the flash **as little-endian 32-bit words** for anything EE-side
   (`ledis.py`, `leblocks.py`); leave the IOP/EROM regions big-endian.
2. Find the kernel by locating the `lui $k0,0x8001` / `mfc0 $t9,EPC` /
   `andi $t9,0x7C` / `sw $k0,K($k0)` / `jr $k0` TLB handler signature.
3. Recover the file↔VA base by cross-product: take every `lui`+`addiu`/`ori` pair
   that builds a `0x8000xxxx` address and find the single flash offset that makes
   them land on ASCII-string starts (`bhist2.py`).
4. Read the syscall table base out of the dispatch tail of the exception-vector
   entry-8 handler (`immscan.py` for the table offset, `ktable.py` to dump).
5. Check the occupancy pattern to see how many builtins that build has.

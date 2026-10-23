# ps2tek mined notes

Source: `resources/09-ps2tek.md` (225,008 bytes; 7,165 lines).
Method: read in chunks + exhaustive grep sweep for `syscall|Syscall`, `Find|83h|82h|break|exception`, `heap|root|EENULL|preserve|clobber`, `v0|v1|a0|RFU`, `Kernel|BIOS|boot`, `at_exit|atexit|constructor|crt|init_array|__libc|crt0`, `400000|0x80000|KSEG|RDRAM`, and a full enumeration of the document's 203 section headers.

The document's own self-description (line 17-20):

> This document, inspired by nocash's websites for various consoles, aims
> to be a comprehensive reference for the PlayStation 2 hardware. While it
> is far from complete, it is usable as a reference for what information
> is documented.

Line numbers below are from that file.

---

## Answers

### 1. The EE kernel syscall ABI

**Section: `> BIOS EE Syscalls` (line 4866). This is the whole of what the file says — four sentences:**

> When a SYSCALL instruction is executed, the EE jumps to 80000180h and
> sets COP0.Cause to 08h. The kernel syscall handler retrieves the syscall
> number from the v1 register. (lines 4868-4870)

> Negative syscalls use the current thread's stack for internal operations
> and are meant to be used in interrupt handlers. Positive syscalls use
> the kernel stack, and some of them can trigger thread reschedules.
> (lines 4872-4874)

Supporting, generic MIPS ABI context — `> EE Registers` naming table (lines 331-333):

> v0-v1 Return register, holds values returned by functions
>
> a0-a3 Argument registers, holds first four parameters passed to a
> function

And `> EE Registers`, saved-register rule (lines 337-338):

> t0-t7 Temporary registers. t0-t3 may also be used as additional
> argument registers s0-s7 Saved registers. Functions must save and
> restore these before using them

**What this does NOT establish:** the file nowhere states which registers the syscall
entry/exit path preserves versus clobbers, and nowhere states that `$v0` carries a
syscall's return value. `$a0`-`$a3` are only described by the generic MIPS convention
above, not by a syscall-specific rule. The claim that arguments come in via `a0`-`a3`
and results come back in `v0` is *inferred* from MIPS convention and is **not stated
here** — see `## Not found`.

One relevant indirect fact: `struct thread_context` (line 4795-4809) shows which
registers the kernel materialises when it saves a thread's CPU state onto the user
stack, and the return-value slot is present:

> u128 at, v0, v1, a0, a1, a2, a3; u128 t0, t1, t2, t3, t4, t5, t6, t7;
> (line 4803)

> u128 gp, sp, fp, ra; u32 fp_regs\[32\]; (line 4807)

### 2. Kernel memory layout at boot

The file has **no physical-address map of the first 512 KB**. The relevant statements:

**Section: `> BIOS Boot Process` → `**EE** **boot** **process**` (lines 4696-4711):**

> \- The EE clock speed is measured. (SCPH-10000 uses COP0.Count;
> SCPH-39001 counts HBLANKs using one of the timers. Unknown what other
> BIOSes use.) - The memory controller is initialized, giving access to
> the 32 MB of RDRAM. (lines 4698-4701)

> \- The EE kernel is copied into RAM starting at virtual address
> 80000000h. The BIOS jumps to the entry point at 80001000h. - The TLB and
> PGIF handler are initialized and various hardware components are reset.
> (lines 4703-4705)

> \- EENULL, an idle loop thread, is loaded into 00081FC0h. (line 4707)

**Section: `> Memory Map` → `**EE** **Virtual/Physical** **Memory** **Map**` (line 75):**

> 00000000h 00000000h 32 MB Main RAM (first 1 MB reserved for kernel) (line 75)

**Section: `> BIOS EE Patches` → `**Alarm** **Patches**` (lines 5268-5270)** — the only
other fixed low-memory addresses mentioned anywhere for the EE:

> Using SetSyscall, games first set syscall 5Ah to be a memcpy with kernel
> privileges. 5Ah is then used to copy the real patch and EENULL to
> 80076000h and 00082000h respectively. (lines 5268-5270)

So the only concrete facts are: kernel loaded at VA 0x80000000 with entry at 0x80001000,
first 1 MB of the 32 MB RDRAM reserved for kernel, EENULL image at physical 0x00081FC0,
patch scratch at 0x00082000, and a second scratch area at 0x80076000.

### 3. `FindAddress` / system data / physical 0x400000-0x500000

**Nothing. This is the single biggest gap in the file.**

- The literal string `FindAddress` does not appear anywhere in the 7,165 lines
  (confirmed by grep for `Find|83h|82h|0x83` — the only `Find` hits are `SifFind`-adjacent
  prose such as line 4683 `To find the start of ROMDIR` and line 4686
  `To find a specific file in the BIOS`).
- The syscall list ends at **`7Fh` `GetMemorySize` (lines 5256-5258)**; there is no 80h,
  81h, 82h or 83h entry, and the list is explicitly non-contiguous (it skips 47h-63h,
  75h, 79h-7Ah, 7Ch, 80h+). For context on what the list's last entry is:

> **7Fh** **int** **GetMemorySize()**
>
> Returns the amount of RDRAM on the console in bytes. (lines 5256-5258)

- Nothing is documented at physical 0x400000-0x500000. Every `400000` grep hit is a
  **SIF RPC server ID** (e.g. line 4387 `it would use 0x80000001, the ID of FILEIO`,
  line 6583 `**LOADFILE** **RPC** **(0x80000006)**`, lines 6805-6830 CDVDMAN/CDVDFSV/
  IOPHEAP/FILEIO IDs) — none describe EE RAM contents. The nearest memory-region entries
  in the EE map are IOP RAM at `1C000000h` (2 MB, line 84) and BIOS at `1FC00000h`
  (4 MB, lines 86-88).

The file's memory-map table does state the EE map is **virtual/physical**, i.e. a plain
physical-address inventory of the first MB simply was not transcribed into this document.

### 4. `SetSyscall` and the syscall table

**Section: `> BIOS EE Syscalls`, entry 74h (lines 5212-5216) — the complete description:**

> **74h** **void** **SetSyscall/RFU116(int** **index,** **int**
> **address)**
>
> Replaces an entry on the syscall table with the specified address. This
> function does not perform any bounds checking. (lines 5212-5216)

**Section: `> BIOS EE Patches` → `**Alarm** **Patches**` (lines 5266-5275)** — the only
worked example of a guest replacing and then invoking a table entry:**

> Using SetSyscall, games first set syscall 5Ah to be a memcpy with kernel
> privileges. 5Ah is then used to copy the real patch and EENULL to
> 80076000h and 00082000h respectively.
>
> The patch contains syscalls FCh-FFh, which are SetAlarm, iSetAlarm,
> ReleaseAlarm, and iReleaseAlarm respectively. It also patches the
> interrupt handler for timer 3 (INTC12) by setting "syscall" 12Ch, which
> is out of bounds. (lines 5268-5275)

Note the scare-quoted `"syscall" 12Ch, which is out of bounds` — the source is
affirming, from the no-bounds-checking statement above, that a guest can overwrite the
timer-3 interrupt handler *by index alone*.

**Section: `> BIOS EE Patches` → `**Threading** **Patches**` (lines 5281-5284)** — the
result-return path for a replacement handler is shown for the `i`-prefixed
(non-rescheduling) syscall family:

> games resolve
> this by creating a "top thread" whose purpose is to redirect these
> interrupt syscalls to their non-interrupt variants, which forces thread
> reschedules. (lines 5281-5284)

The file does not say how the *return value* of a replacement handler is delivered to
the caller (`v0`? memory?). See `## Not found`.

### 5. `InitMainThread` / `InitHeap`

**Section: `> BIOS EE Syscalls`, entries 3Ch/3Dh/3Eh (lines 5126-5144) — verbatim:**

> **3Ch** **void\*** **InitMainThread/RFU060(uint32** **gp,** **void\***
> **stack,** **int** **stack_size,** **char\*** **args,** **int**
> **root)** Initializes the current thread. Returns the stack pointer of
> the thread.
>
> If stack == -1, the stack pointer equals the end of RDRAM - stack_size.
> Else, it equals stack + stack_size. This function should only be called
> before the program's main function. (lines 5126-5133)

> **3Dh** **void\*** **InitHeap/RFU061(void\*** **heap,** **int**
> **heap_size)**
>
> Initializes the current thread's heap. If heap == -1, the end of the
> heap resides at the thread's stack pointer. Else, the end of the heap is
> heap + heap_size. Returns the end of the thread's heap. (lines 5135-5140)

> **3Eh** **void\*** **EndOfHeap()**
>
> Returns the current thread's heap base. (lines 5142-5144)

Cross-reference — the heap lives on the **TCB**, not in a global, and children inherit
it (`> BIOS EE Threading` → `**Structs**` → `struct TCB`, lines 4790-4791, and syscall 20h
at lines 4966-4974):

> int \*root; //function to return to when exiting thread? void
> \*heap_base;

> t-\>func, t-\>initial_priority, t-\>stack, t-\>stack_size, and
> t-\>gp_reg are used. The new thread re-uses the heap of its parent
> thread. (lines 4971-4973)

**The C runtime: the file says nothing.** Grep for
`at_exit|atexit|constructor|crt|C runtime|global constructor|init_array|__libc|crt0`
returned **zero matches in the entire file**. There is no statement anywhere about
`.init_array` / `.ctors` walking, `atexit` registration, `.fini_array`, or what the EE
C runtime (`crt0.o`) does between `InitMainThread`/`InitHeap` and `main`.

The nearest thing is the pre-`main` syscall patching, which the file places explicitly
**before** the main function:

> The EE kernel is full of bugs, so games have to work around them. Both
> the official SDK and PS2SDK patch the alarm functions and certain
> threading functions before the main function is executed. (lines 5262-5264)

### 6. EE kernel exceptions / break points / `break`

**`> EE COP0 Exception Handling` → `**Exceptions**` (lines 759-815).** Vector table
(lines 768-781):

> Name Normal Bootstrap Level
> ------------------------------------------------| Reset/NMI |
> BFC00000h | BFC00000h | 2 |
> ------------------------------------------------| TLB Refill |
> 80000000h | BFC00200h | 1 |
> ------------------------------------------------| Perf. Counter |
> 80000080h | BFC00280h | 2 |
> ------------------------------------------------| Debug | 80000100h
> | BFC00300h | 2 |
> ------------------------------------------------| All others |
> 80000180h | BFC00380h | 1 |
> ------------------------------------------------| Interrupt |
> 80000200h | BFC00400h | 1 |
> ------------------------------------------------

**Breakpoint cause code** (`**\$13** **-** **COP0.Cause**`, lines 860-872):

> 06h=Bus Error (instruction) 07h=Bus Error (data) 08h=Syscall
>
> 09h=Breakpoint 0Ah=Reserved Instruction 0Bh=Coprocessor Unusable
> 0Ch=Overflow (lines 867-870)

**BD/BD2 delay-slot semantics** (lines 889-892):

> The BD/BD2 bits are important as when they are set, EPC/ErrorEPC is set
> to the address of the branch instruction, not its delay slot. This
> allows the EE to re-execute the branch when it returns from an
> exception.

**EPC return address** (`**\$14/\$30** **-** **COP0.EPC/COP0.ErrorEPC**`, lines 894-900):

> 0-31 Address to return to after an exception
>
> EPC and ErrorEPC are used by level 1 and 2 exceptions respectively. When
> the ERET instruction is executed, it jumps to the address in EPC or
> ErrorEPC, depending on if Status.EXL or Status.ERL is set.

**The kernel's syscall entry is the "All others" vector 80000180h at level 1**, and it
re-arms the handler by rescheduling to EPC (lines 4830, 4868-4870):

> Set current thread entry function to EPC (instruction after exception) (line 4830)

**The user-visible epilogue syscall**, entry 05h (lines 4895-4898):

> **05h** **void** **\_ExceptionEpilogue/RFU005()**
>
> Internal syscall used by kernel exception handlers. Returns to the user
> program. (lines 4895-4898)

**Encoding of `SYSCALL` and `BREAK`** — `> EE Instruction Decoding`, SPECIAL opcode
sub-function `010` (line 391):

> \| JR \| JALR \| MOVZ \| MOVN \|SYSCALL\| BREAK \| --- \| SYNC \| 010 \|

That is the complete inventory: both are `SPECIAL` op 0 with function 010, differing
only in bit 25 (CODE), which the table does not spell out.

**IOP-side exception vectors (different processor, adjacent evidence), EXCEPMAN
(line 5672):**

> EXCEPMAN installs exception vectors at RAM addresses 0x40 and 0x80, but
> they do not do anything useful by themselves. Other modules will use
> EXCEPMAN to install their own handlers. (lines 5672-5674)

---

## Not found

1. **Syscall register preservation/clobber contract.** No preserved-vs-clobbered list,
   no `$v0`-as-return-value rule, no statement about the fate of `$a0`-`$a3` or `$t0`-`$t9`
   across a syscall. The only syscall-ABI sentence in the file is
   *"The kernel syscall handler retrieves the syscall number from the v1 register."*
2. **Everything about `FindAddress` (syscall 83h).** The name appears nowhere; the
   syscall list simply stops at 7Fh.
3. **Physical address inventory of 0x00000000-0x00080000.** No per-page or per-region
   breakdown of the first 512 KB; no syscall-table location; no kernel data-structure
   addresses (`0x100`, `0x180`, thread/TCB arrays, etc.). The file only says
   "first 1 MB reserved for kernel".
4. **Physical 0x400000-0x500000.** No EE RAM contents documented there; all `400000`
   hits are SIF RPC server IDs.
5. **Syscall dispatch mechanism.** No description of how 80000180h indexes into the
   table, how the handler tail-calls the entry, or how a `SetSyscall` replacement's
   return value reaches `$v0`.
6. **C runtime behaviour after `InitMainThread`/`InitHeap`.** Zero mentions of
   constructors, `.init_array`, `.ctors`, `atexit`, `.fini_array`, `crt0`, `__libc`, or
   `main` itself. Also absent: where a default stack/heap is placed when the guest passes
   `stack == -1` / `heap == -1` beyond the single sentence each ("end of RDRAM -
   stack_size", "the thread's stack pointer").
7. **Kernel `break` instruction handling.** The file documents that ExcCode 09h is
   "Breakpoint" and that `BREAK` encodes in the SPECIAL table, but gives **no** kernel
   behaviour for it: no vector mapping for breakpoint (only "All others" 80000180h),
   no breakpoint-register (`COP0.BPC/BDA`, i.e. `$01`/`$02`) treatment, and no statement
   about what the EE kernel's default breakpoint handler does. Note the "Debug"
   exception at 80000100h is COP0 Debug/ExcCode 03h (lines 776, 880) and is a
   *different* thing from the `break` instruction; do not conflate them.
8. **`SetSyscall` bounds** — the file says there is no bounds checking but does not give
   the table's base address or valid index range, only that index 12Ch is "out of bounds".

---

## Contradictions

Against the recorded facts supplied for checking:

| Recorded fact | File says | Verdict |
|---|---|---|
| syscall `0x83` is `FindAddress` | Not mentioned anywhere; syscall list ends at `7Fh` `GetMemorySize` | **No contradiction** (silence — but also **no support**) |
| syscall `0x74` is `SetSyscall` | line 5212: `**74h** **void** **SetSyscall/RFU116(int** **index,** **int** **address)**` | **Confirmed, no contradiction** |
| syscall `0x3C` is `InitMainThread` | line 5126: `**3Ch** **void\*** **InitMainThread/RFU060(uint32** **gp,** **void\*** **stack,** **int** **stack_size,** **char\*** **args,** **int** **root)**` | **Confirmed, no contradiction** |
| syscall `0x3D` is `InitHeap` | line 5135: `**3Dh** **void\*** **InitHeap/RFU061(void\*** **heap,** **int** **heap_size)**` | **Confirmed, no contradiction** |
| syscall `0x40` is `CreateSema` | line 5146: `**40h** **int** **CreateSema(SemaParam** ***s)**` | **Confirmed, no contradiction** |
| KSEG0/KSEG1 translate with `addr & 0x01FFFFFF` over 32 MB RDRAM | line 942-943: `Accessing a privileged region without the necessary privileges raises an Address Error exception. For kseg0 and kseg1, the physical address retrieved is simply (address & 1FFFFFFFh).` — mask identical (0x1FFFFFFF); RDRAM size 32 MB at lines 75 and 4700-4701 | **Confirmed, no contradiction** |

**Nothing in the file contradicts any of the six recorded facts.** All five named
syscall numbers and the KSEG0/KSEG1 mask are stated verbatim and agree exactly.

Two adjacent tensions worth carrying forward (neither contradicts the six facts, but both
bound how far the facts generalise):

- **The `addr & 0x01FFFFFF` mask vs. expandable RAM.** The mask maps a 2 GB segment onto
  32 MB, but the same document says (lines 93-94):
  > EE RAM is reportedly expandable up to 256 MB. However, the maximum seen
  > in practice is 128 MB, for special TOOL consoles.

  A 29-bit physical mask cannot describe a 128 MB console. Either the mask is only valid
  for stock 32 MB units, or expanded-RAM consoles change segment behaviour. The document
  does not reconcile this. Treat the mask as a **32 MB-unit fact**.
- **`-1` sentinels are used as pointers.** `InitMainThread`/`InitHeap` compare `stack`/`heap`
  against `-1` (lines 5131, 5138) rather than `NULL`, and `Exit` takes a `status`
  (line 4890). If the EE ever gains a C runtime, this `-1`-vs-`NULL` distinction is a
  concrete thing a reimplementation must reproduce rather than normalise away.

No other files were edited, and nothing above was inferred into the Answers section.

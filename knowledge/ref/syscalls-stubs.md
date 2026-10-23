# Syscalls / Stubs

Distilled from three corpus files, all read in full:

| Source | Role |
|---|---|
| `resources/04-runtime-syscalls-stubs.md` | How `ps2xRuntime` executes, how syscalls are added, C++ stub craft, game overrides |
| `resources/db-syscalls.md` | EE kernel syscall number → name → params → return → runtime status table (claims ps2tek ground truth, cross-referenced with `ps2_syscalls.cpp`) |
| `resources/db-sdk-functions.md` | SDK library-level stubs (the functions that *call* syscalls), per-library status |

Notation is kept verbatim from the sources: `$a0`–`$a3`, `$v0`, `$v1`, `ctx.gpr[n]`, `impl` / `stub-safe` / `nop` / `log-only`.

Anything the sources do not state is written as **"the sources do not state this"** and the nearest thing they *do* say is quoted. Nothing in this file is inferred from PS2 hardware documentation or from general R5900 knowledge; where this file mentions our own port's code, that is labelled **[port]** and is not attributed to the corpus.

---

## ABI

### The headline: the sources do not state the syscall ABI.

**None of the three sources says which GPRs a `syscall` instruction preserves and which it clobbers on return.** There is no preserved/clobbered table, no statement that `$a0`–`$a3` survive, no statement about `$ra`, `$t0`–`$t9`, `$s0`–`$s8`, `$gp`, `$sp`, `hi`/`lo`, the FPRs, or the vector registers. Do not assume a rule from this corpus.

### What the sources *do* state, exhaustively

1. **The syscall number arrives in `$v1`.** `db-syscalls.md`, "Lookup Protocol" step 1: *"Find the syscall `$v1` number in the table below"*. This is the only place any source assigns a meaning to `$v1` on entry.
2. **Arguments are the o32 argument registers.** `db-syscalls.md`: *"Parameters follow the MIPS o32 calling convention: `$a0`–`$a3` → `ctx->regs[4..7]`"*. `04-runtime-syscalls-stubs.md` §3 repeats it in code form: *"reading arguments from `ctx.gpr[4]` (a0), `ctx.gpr[5]` (a1), etc."* `db-syscalls.md` "Syscall Debugging Workflow" step 5: *"Return value goes in `ctx.gpr[2]` (v0)"*.
3. **The return value goes in `$v0`** (`ctx.gpr[2]` / `ctx->regs[2]`). Every non-`void`, non-`noreturn` row in the syscall table is written as `$v0`=something, and every triage stub writes `ctx.gpr[2].words[0]`.
4. **Negative numbers are a second namespace, not a sign.** `db-syscalls.md`: *"Negative syscall numbers (prefixed `-`) are interrupt-context variants (no thread reschedule)"*. E.g. `0x42 SignalSema` vs `-0x43 iSignalSema`, `0x20 CreateThread` vs no negative, `0x37 SuspendThread` vs `-0x38 iSuspendThread`.
5. **The instruction vector.** `04-runtime-syscalls-stubs.md` §3: *"A `SYSCALL` instruction jumps to the BIOS exception handler."* Nothing about the return path.
6. **Function-call dispatch is a different mechanism.** `04-runtime-syscalls-stubs.md` §1: *"When `jal` instructions are encountered in MIPS, the generated code uses a table lookup to call the corresponding C++ function pointer."* So SDK/libc stubs are reached through `jal` (normal o32 callee-saved rules apply there), while `syscall` goes to the BIOS exception handler (rules unknown). The sources never equate the two.
7. **Stub signature.** `db-sdk-functions.md` Lookup Protocol step 4: *"All stubs use signature: `void funcName(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)`"*, and the default stub body is `setReturnS32(ctx, 0)`. The sources give no separate "callee-saved" list for this path either.

### What is therefore **unknown** from the corpus

- whether `$a0`–`$a3` come back unchanged;
- whether `$t0`–`$t9` and `$a0`–`$a3` are destroyed by the kernel entry (this matters directly: many game stubs pass &reuse argument registers);
- whether `$v1` still holds anything meaningful on return (the only stated role is the *input* number);
- whether `$ra` is rewritten, whether `$sp` is touched, whether `hi`/`lo` or the FPRs are affected;
- whether the exception path contributes any observable register state at all.

### **[port]** Evidence the corpus does not contain

For the open question above, the only evidence available in this repo is our own code, not the sources. Recorded here so the next reader does not have to re-derive it, and clearly separated from the sources above:

- `core/ps2xRuntime/include/ps2_runtime.h:193-220` — GPRs are 64-bit, stored in 128-bit vector slots `ctx->r[n]`; `getRegU32` reads word 0. `setReturnS32` **sign-extends the full 64-bit `$v0`** and overwrites the whole slot; `setReturnU64` puts the low 64 bits in `$v0` **and the high 32 bits in `$v1`**. So in this port `$v1` is doing double duty: syscall number on entry, high word of a 64-bit return on exit. The sources support neither statement.
- `core/ps2xRuntime/src/lib/ps2_runtime.cpp:1494-1496` — the number is `encodedSyscallId != 0 ? encodedSyscallId : getRegU32(ctx, 3)`, i.e. `$v1` is the fallback source of the number.
- Nothing in the port documents a register-preservation contract either. The absence is a real, shared gap — see Contradictions §2.

---

## Boot-critical syscalls

Numbers, names, parameter registers, return values and status are verbatim from `db-syscalls.md`. `impl` = "fully implemented in `ps2_syscalls.cpp`", `stub-safe` = "safe to return 0" (the db's own definitions, Lookup Protocol step 2). That column describes the corpus's `ps2_syscalls.cpp` (upstream PS2Recomp, per the db header); what *our* port actually has a `case` for is `core/ps2xRuntime/src/lib/Kernel/Syscalls/Dispatcher.cpp` — see Contradictions for where the two disagree.

"Boot-critical" here = on the path from reset to a first rendered frame plus the services the main loop cannot run without. The db's full table (semaphores, alarms, every `i` variant, OSD, MCP, etc.) is in `db-syscalls.md` and is not duplicated here.

| # | Name | Params | Return | Status | Note (db) |
|---|---|---|---|---|---|
| 0x01 | ResetEE | `a0`=flags | void | stub-safe | Resets DMAC/VU/VIF/GIF/IPU per flag bits — no-op in recomp |
| 0x02 | SetGsCrt | `a0`=interlace, `a1`=mode, `a2`=field | void | impl | Initializes PCRTC display mode |
| 0x03 | SetGsCrtKn | same as SetGsCrt | void | impl | Korean variant |
| 0x04 | Exit | `a0`=status | noreturn | impl | ps2tek: returns to OSDSYS. Recomp: calls `std::exit(0)` |
| 0x05 | _ExceptionEpilogue | — | void | stub-safe | Internal kernel use — returns to user from exception |
| 0x06 | LoadExecPS2 | `a0`=filename, `a1`=argc, `a2`=argv | noreturn | stub-safe | Loads ELF and executes — not needed in static recomp |
| 0x07 | ExecPS2 | `a0`=entry, `a1`=gp, `a2`=argc, `a3`=argv | noreturn | stub-safe | Clears kernel state, creates main thread at entry |
| 0x0B | AddSbusIntcHandler | `a0`=cause, `a1`=handler | `$v0`=id | stub-safe | IOP SBUS — not needed in recomp |
| 0x0C | RemoveSbusIntcHandler | `a0`=cause | `$v0`=status | stub-safe | |
| 0x10 | AddIntcHandler | `a0`=cause, `a1`=handler, `a2`=next, `a3`=arg | `$v0`=handler_id | impl | Registers INTC interrupt handler |
| 0x11 | RemoveIntcHandler | `a0`=cause, `a1`=handler_id | `$v0`=status | impl | |
| 0x12 | AddDmacHandler | `a0`=channel, `a1`=handler, `a2`=next, `a3`=arg | `$v0`=handler_id | impl | Registers DMAC interrupt handler |
| 0x13 | RemoveDmacHandler | `a0`=channel, `a1`=handler_id | `$v0`=status | impl | |
| 0x14 | _EnableIntc | `a0`=cause_bit | `$v0`=was_enabled | impl | Enables INTC_MASK bit |
| 0x15 | _DisableIntc | `a0`=cause_bit | `$v0`=was_enabled | impl | |
| 0x16 | _EnableDmac | `a0`=cause_bit | `$v0`=was_enabled | impl | Enables D_STAT mask bit |
| 0x17 | _DisableDmac | `a0`=cause_bit | `$v0`=was_enabled | impl | |
| 0x18 | SetAlarm | `a0`=ticks_lo, `a1`=ticks_hi, `a2`=handler, `a3`=common | `$v0`=alarm_id | impl | Timer alarm with chrono callback |
| 0x19 | ReleaseAlarm | `a0`=alarm_id | `$v0`=status | impl | Cancels alarm |
| 0x20 | CreateThread | `a0`=ThreadParam* | `$v0`=thread_id | impl | Allocates thread ID, stores entry/priority/stack |
| 0x21 | DeleteThread | `a0`=thread_id | `$v0`=status | impl | Thread must be DORMANT |
| 0x22 | StartThread | `a0`=thread_id, `a1`=args | `$v0`=status | impl | Sets DORMANT→READY, reschedules |
| 0x23 | ExitThread | — | void | impl | Current thread→DORMANT, reschedules |
| 0x24 | ExitDeleteThread | — | void | impl | Current thread deleted, reschedules |
| 0x25 / -0x26 | iTerminateThread | `a0`=thread_id | `$v0`=status | impl | No reschedule variant |
| 0x2F | GetThreadId | — | `$v0`=tid | impl | Returns current thread ID |
| 0x32 | SleepThread | — | `$v0`=status | impl | Cooperative yield — decrements wakeup_count or goes WAIT |
| 0x33 | WakeupThread | `a0`=tid | `$v0`=status | impl | WAIT→READY, reschedules |
| 0x37 / -0x38 | iSuspendThread | `a0`=tid | `$v0`=status | impl | ⚠️ ps2tek BUG: no reschedule on current thread! |
| 0x3C | InitMainThread | `a0`=gp, `a1`=stack, `a2`=stack_size, `a3`=args | `$v0`=stack_ptr | impl | ps2tek: stack=-1 → end of RDRAM |
| 0x3D | InitHeap | `a0`=heap, `a1`=heap_size | `$v0`=heap_end | impl | heap=-1 → starts at stack pointer |
| 0x3E | EndOfHeap | — | `$v0`=addr | impl | Returns heap base |
| 0x3F | GetHeapEnd | — | `$v0`=addr | impl | Alias for EndOfHeap |
| 0x40 | CreateSema | `a0`=SemaParam* | `$v0`=sema_id | impl | Uses init_count, max_count |
| 0x44 | WaitSema | `a0`=sema_id | `$v0`=status | impl | Blocking: count>0→count--, else WAIT |
| 0x45 | PollSema | `a0`=sema_id | `$v0`=status | impl | Non-blocking: count-- or -1 |
| 0x50 | CreateEventFlag | `a0`=flag_desc_ptr | `$v0`=flag_id | impl | Creates event flag object |
| 0x52 | SetEventFlag | `a0`=flag_id, `a1`=bits | `$v0`=status | impl | Sets bit pattern |
| 0x56 | WaitEventFlag | `a0`=flag_id, `a1`=bits, `a2`=mode, `a3`=result_ptr | `$v0`=status | impl | Blocking wait on bit pattern |
| 0x57 | PollEventFlag | same as WaitEventFlag | `$v0`=status | impl | Non-blocking poll |
| 0x5A | QueryBootMode | `a0`=param | `$v0`=value | impl | Returns boot mode parameter |
| 0x5B | GetThreadTLS | `a0`=tid | `$v0`=tls_ptr | impl | Returns thread-local storage pointer |
| 0x64 | FlushCache | `a0`=mode | void | impl | 0=flush data, 1=invalidate data, 2=invalidate insn. No-op in recomp |
| 0x70 / -0x70 | GsGetIMR | — | `$v0`=imr | impl | Returns GS_IMR |
| 0x71 / -0x71 | GsPutIMR | `a0`=imr_val | void | impl | Sets GS_IMR |
| 0x73 | SetVSyncFlag | `a0`=vsync_ptr, `a1`=csr_ptr | void | impl | Sets kernel vsync pointers — **NOT SetGsVParam** |
| 0x74 | SetSyscall | `a0`=index, `a1`=address | void | impl | ps2tek name. PS2Recomp: RegisterExitHandler. Replaces syscall table entry |
| 0x76 / -0x76 | SifDmaStat | `a0`=dma_id | `$v0`=status | impl | +value=queued, 0=in-progress, -value=complete |
| 0x77 / -0x77 | SifSetDma | `a0`=SifDmaTransfer*, `a1`=len | `$v0`=transfer_id | impl | Low-level SIF1 transfer |
| 0x78 / -0x78 | SifSetDChain | — | void | impl | Initializes SIF0 channel (CHCR=184h) |
| 0x79 | GetOsdConfigParam | `a0`=buf | void | impl | OSD config (language, screen, etc.) |
| 0x83 | FindAddress | `a0`=id | `$v0`=addr | impl | see Contradictions §1 |
| 0x85 | SetMemoryMode | `a0`=mode | `$v0`=prev_mode | impl | |
| 0xFC | _kprintf | `a0`=fmt_ptr | void | impl | Debug print from RDRAM — **conflicts with the db's own alarm row; see Contradictions §4** |

`stub-safe` is not "unimplemented" — it is the db's label for a syscall whose correct behaviour in a static recomp *is* the do-nothing: no hardware to reset (`0x01`), no second ELF to load (`0x06`/`0x07`/`0x7B`), no IOP SBUS (`0x0B`/`0x0C`), no TLB refill (`0x100`). Those are legitimate no-ops, in a different category from a triage stub.

`db-syscalls.md` also gives the "0x73 is NOT SetGsVParam" correction explicitly, i.e. a wrong name in circulation is a known failure mode of this table.

---

## Syscall table overrides

### What the sources say

- **Number/name:** `0x74`, `SetSyscall`. `db-syscalls.md` row: `a0`=index, `a1`=address, return `void`, status `impl`, note *"ps2tek name. PS2Recomp: RegisterExitHandler. Replaces syscall table entry"*.
- **What replacing a table entry means:** *"Replaces syscall table entry"*, i.e. the guest-supplied address takes the place of the kernel's own entry for that number, from then on. That is the whole of the description.
- **The one concrete use recorded anywhere in the corpus** is the alarm patch: the db's row `-0x1E / 0xFC | iSetAlarm | ... | Patched via SetSyscall — ps2tek §EE Patches`. So at least one real-world install is a *kernel-ABI patch* (same signature, different handler), not a new private entry.
- **Return:** `void`. The sources do not say whether `$v0` is left alone on return — consistent with the unresolved ABI question above.

### What the sources do **not** say

- **What the replacement handler is called with.** No source describes the argument registers, whether the syscall number is re-delivered in `$v1`, whether `$a0`–`$a3` are forwarded, or whether the handler runs in the interrupted context, a new one, or on a fresh stack.
- **How the replacement returns** — nothing about `$ra`, `$v0`, or any other register.
- **Whether `a0`=index is signed**, whether negative indices are installable, or what `a1`=address may point at.
- **Whether a table entry can be restored** (e.g. `a1`=0).
- `04-runtime-syscalls-stubs.md` does not mention `SetSyscall` at all; it only covers `bindAddressHandler` / `registerFunction` overrides, which are a *different* mechanism (ELF address → handler, applied at port setup, not at guest runtime).

### **[port]** How our runtime actually does it

Not from the corpus; recorded so the gap is explicit and the behaviour is not re-derived from scratch.

- `SetSyscall` handler (`Kernel/Syscalls/System.cpp:558-565`): reads `a0` as the syscall index and `a1` as the handler, calls `runtime->setEeSyscallOverride(rdram, index, handler)`, then `setReturnS32(ctx, 0)` — so the port does write `$v0`, contradicting the db's `void` cell only in the trivial sense that no caller can observe the difference under the unstated ABI.
- `PS2Runtime::setEeSyscallOverride` (`ps2_runtime.cpp:2340+`): stores `number → handler` in a map, and **also writes the handler word into the guest-visible table mirror** at `0x80011F80 & 0x1FFFFFFF` (= `0x00011F80`) + `syscallNumber * 4`, so guest code that reads the syscall table itself observes the replacement. `handler == 0` erases the entry.
- **Override wins over the kernel case:** `dispatchNumericSyscall` calls `dispatchSyscallOverride` *first* and returns immediately if it claims the call (`Dispatcher.cpp:7-12`). A guest-installed handler for a real kernel number therefore shadows the kernel implementation — this is the mechanism behind the `override=0x2a1c88` observation recorded in `dead_ends.jsonl#0065`.
- **Missing handler is reported, once per (id, handler) pair:** if `runtime->hasFunction(handler)` is false, the port returns `KE_ERROR` (-1, `Helpers/State.h:22`) and logs `[syscall-override:missing-handler]`, on the grounds that a silently-failing probe makes an infinite guest loop look like a legitimate refusal.
- **Invocation shape:** the caller context is copied wholesale, then `pc = handler`, `$sp = scheduler.invocationStackTop()`, `$ra = 0`; the call is asynchronous (`invokeCurrent`). On completion `onComplete` copies **only** `parent.r[2] = completed.r[2]` (see Contradictions §2). Dispatch is re-entrancy-guarded: a second override call for a number already in flight returns false.
- **[port] note:** `$ra = 0` means the guest handler must return by its own `jr $ra` and the scheduler must synthesise the return; combined with `04-runtime-syscalls-stubs.md` §5's warning ("if the backend raw handler doesn't naturally advance `ctx->pc` … it will infinitely loop re-dispatching the exact same PC"), the override path is exactly where a missing PC advance shows up as a hang.

---

## Stub patterns

Catalogue of what the three sources recommend, with the legitimate / bug-hiding split. Status vocabulary is `db-sdk-functions.md`'s: `impl` = real logic, `nop` = safe return-0, `log-only` = prints then returns 0.

| # | Pattern | Source | Legitimate when | Hides a real bug when |
|---|---|---|---|---|
| 1 | **Triage stub** `ret0` / `ret1` / `reta0` — `ctx.gpr[2].words[0] = 0 / 1 / ctx.gpr[4].words[0]` | 04-runtime §4, db-syscalls "Triage Strategy", db-sdk "Generic Stubs" (`ps2_stubs_misc.inl`) | Purely as a *diagnostic*: "Try binding unknown functions to `ret0` or `ret1`. Does the game boot further? If so, you've bypassed a check." | It is left in place. The source is explicit that this is a temporary probe: *"You can figure out what check it was later using Ghidra."* A permanent `ret0` converts a crash into a soft-lock or a wrong-but-plausible state. |
| 2 | **Real native implementation** — read args from `ctx.gpr[4..6]`, do host-side work, return in `ctx.gpr[2]` (the `sceCdRead` example, LBN→host file read) | 04-runtime §4, db-syscalls "Writing Real Implementations" | You know the contract. This is the target state, and the sources use it for the CD/ISO path specifically. | If you keep the *signature* but not the side effects — e.g. writing no bytes to the guest buffer while returning success. |
| 3 | **Loud stub** — unimplemented path prints a warning and fails hard | 04-runtime §3 (*"prints `[Syscall TODO]` and usually crashes"*), db-sdk (log-only) | Always, as a default. It is the only pattern that cannot hide a bug. **[port]** `Unimplemented.cpp` warns with name/PC/RA/`$a0`–`$a3`, then `throw`s; after a per-name cap it returns -1. | Never. If a loud stub starts throwing on a hot path, fix the syscall, don't silence it. |
| 4 | **`nop` = return 0** | db-sdk, hundreds of rows (`sceMc*`, `sceMpeg*`, `sceDma*`, `sceSif*Rpc*`, `sceeFont*`, `sceIpu*`, POSIX `sce*`, `sceVu0*`) | The subsystem genuinely does not exist in a static recomp: memory card, MPEG, RPC/command transport, font, IPU, TTY/DECI2. Returning 0 = "nothing happened", which is the truthful answer. | The value is a pointer, handle, count, or error the game branches on: `sceMcOpen`/`sceMcRead`, `sceSifLoadModuleBuffer`, `sceMpegGetPicture`, `sceMpegDispWidth`, `scePadPortOpen`-style handles. Then 0 is a lie the game will dereference. |
| 5 | **Plausible fixed hardware constant** | db-sdk: `sceCdDiskReady`→2, `sceCdGetDiskType`→0x14, `sceCdStatus`→0x0A, `scePadGetState`→6, `scePadGetPortMax`→2, `sceMpegIsEnd`→1, `sceMpegIsRefBuffEmpty`→1, `sceSifIsAliveIop`→1, `getpid`→1, `sceCdPause/Seek/Standby/Stop`→1 | The game polls a *capability* question ("is a disc in?") and any consistent answer keeps it moving; the value is not dereferenced. | When the game uses the constant to compute sizes/offsets (0x14 as a struct size, 0x0A as a status it switches on) — then the constant is a silent memory-corruption source. |
| 6 | **Fake identity** — `sceSifLoadModule`/`sceSifLoadModuleBuffer` "Returns fake module ID" (≥0) | db-sdk | When the game only compares module IDs for equality against what it just loaded. | When the ID is later used to index or to call back. Also note the sources' own status for these is `nop`, not `impl` — "fake" is not "implemented". |
| 7 | **Alias forwarding** — one handler serving two numbers | db-syscalls: `0x4A` = same handler as `0x7E`, `0x4B` = same as `0x79`; `0xFE` "Alias for ReleaseAlarm", `0x3F` "Alias for EndOfHeap" | The two numbers are genuinely the same kernel entry. | When the alias is asserted from a name in a `case` label rather than from the ABI — see Contradictions §1, which is exactly that failure. |
| 8 | **Argument auto-recovery** | db-sdk `sceCdRead`: "LBN-based sector read with auto-recovery for swapped args" | A real robustness feature for stripped games with surprising calling conventions. | If it makes a *wrong* call look right; it should log which way it swapped. |
| 9 | **Full libc reimplementation** — `malloc/free/calloc/realloc`, `mem*`, `str*`, `printf` family, `fopen..fflush`, `sqrt/sin/cos/atan2/pow/exp/log/log10/ceil/floor/fabs`, `__ieee754_rem_pio2f` | db-sdk, "All are **impl** with real logic, not no-ops" | Always preferable to `nop` for libc: these are the functions the game cannot run without, and they are host-implementable. FPR returns ("Returns via FPR", `atan2(f12, f13)`, `pow(f12, f13)`) note that float stubs use the *FP* ABI, not `$v0`. | Never, if implemented; the danger is the lazy alternative (`malloc` as `ret0` → guest heap pointer 0 → writes to physical 0). |
| 10 | **Vectorised math** | 04-runtime §6: runtime expects SSE/AVX intrinsics; *"Do NOT write naive scalar loops for math-heavy stubs; it will destroy frame rates."* | Always for VU0/MMI math. | n/a — this one is a performance rule, and breaking it presents as a "bug" that isn't a bug. |
| 11 | **Game-scoped override file** — `ps2_stubs_<game>.inl`, registered against ELF metadata (basename, entry, crc32) via `PS2_REGISTER_GAME_OVERRIDE` | 04-runtime §5, db-sdk ("For game-specific stubs, create a new `ps2_stubs_<game>.inl` file") | Always: *"You should keep game-specific hacks out of the core `ps2_syscalls.cpp` or generic SDK headers to avoid breaking other games."* | When the "game-specific" fix is actually a generic ABI fix, in which case it will be re-discovered per game. |

Two cross-cutting warnings the sources attach to the whole catalogue:

- **`bindAddressHandler` may not advance `$pc`.** 04-runtime §5, marked CRITICAL: *"if the backend raw handler doesn't naturally advance `ctx->pc` (like many simple hooks), it will infinitely loop re-dispatching the exact same PC"*. The documented escape is `runtime.registerFunction` plus manual `ctx->pc = getRegU32(ctx, 31)` guarded by an `entryPc` check.
- **Stub what the game cannot observe; implement what it can.** The db's `stub-safe` category exists precisely to separate "correctly a no-op" from "not done yet".

---

## Contradictions

Listed only. No other file was edited.

### 1. Syscall `0x83`: `dead_ends.jsonl#0065` vs `resources/db-syscalls.md`

- **`dead_ends.jsonl#0065` records:** *"`case 0x83: FindAddress` never runs for RE4: the guest installed its own handler for 0x83 via SetSyscall, so dispatchSyscallOverride intercepts first and the trace shows `override=0x2a1c88` on every call. **0x83 is RE4's PRIVATE syscall number, not a kernel one.**"*
- **`db-syscalls.md` records:** `| 0x83 | FindAddress | a0=id | $v0=addr | impl | |`, and lists it twice more as a kernel constant: under "Memory / Cache", `InitMainThread(0x3C) → … → FindAddress(0x83) → SetMemoryMode(0x85)`.
- **The two are not actually exclusive, and #0065's second sentence is the false one.** `Dispatcher.cpp:305-307` has `case 0x83: FindAddress(...)` with a full `FindAddress` implementation in `System.cpp:902`; a kernel `case` cannot exist for a number that is not a kernel number. What #0065 actually measured — the guest's handler intercepting first — is fully explained by `dispatchSyscallOverride` running before the `switch`, and is exactly what a *guest override of a real kernel entry* looks like. **A real kernel syscall number, overridden by the game, is consistent with every observation in #0065; "not a kernel one" is not.**
- **Further disagreement on the same row, unresolved by either record:** the db says `FindAddress` takes `a0`=id (one argument). Our `FindAddress` reads `a0`=start, `a1`=end, `a2`=target and scans for a word match. The static reading of RE4's private `FUN_002A1C88` in the `PATCH 14` comment describes that *same* three-argument signature. So the db's `a0`=id row is inconsistent with the port and with the guest code it describes, while the *number* in that row appears to be right and #0065's "not a kernel one" appears to be wrong.
- **Suggested resolution (not applied here):** #0065's finding should be re-worded to "0x83 is a real kernel syscall (FindAddress) that RE4 overrides with a private handler; the kernel `case` therefore never runs *for RE4*", and the db's `a0`=id params should be corrected against ps2tek/our implementation. This is a `dead_ends.jsonl` edit and is out of scope for this file.

### 2. `dispatchSyscallOverride` copies back only `$v0` — nothing in the corpus supports or forbids it

- **Current behaviour:** `core/ps2xRuntime/src/lib/Kernel/Syscalls/System.cpp:457-518`, `onComplete` ends with a single statement `parent.r[2] = completed.r[2];`. Every other register the guest handler modified — `$a1`–`$a3`, `$v1`, `$t0`–`$t9`, `$s0`–`$s8`, `$fp`, `$ra`, `$sp` — is discarded, even though the *outgoing* call copied the entire context (`invocation.context = *ctx`) and set `pc`, `$sp` and `$ra` on it.
- **What the sources say about it:** essentially nothing, and what they do say cuts both ways.
  - `db-syscalls.md` describes a *kernel* return convention only: args in `$a0`–`$a3`, result in `$v0`. Under that convention a v0-only copy-back is sufficient **for a handler that returns exactly one word in `$v0` and clobbers nothing else the caller still needs** — which is the case the `PATCH 14` static reading of `FUN_002A1C88` describes (a linear search returning the match in `$v0`, or 0).
  - The sources say nothing about guest-to-guest call returns at all: no o32 callee-saved list, no statement that `$s0`–`$s8` survive, no `$ra` rule. So "copy only `$v0`" is an **assumption**, not a documented contract, and it is an assumption about the case where it is least likely to be checked.
- **Why it is a live risk, concretely:**
  - The SDK corpus is full of multi-value returns — the `ret0/ret1/reta0` family exists precisely because a handler's whole job is to shape one return word, but real handlers such as `sceCdGetToc` (fills a guest buffer), `scePadRead` ("Reads pad state → writes to buffer"), `sceGsSetDefDispEnv` (initialises a struct) and the semaphore/event status calls (`a1`=status_buf) communicate through memory, and any handler that returns a *pair* in `$v0`/`$v1` loses `$v1` here. `setReturnU64` in our own `ps2_runtime.h` is precisely a `$v0`/`$v1` pair return.
  - A handler that repurposes a `$t` register as scratch and returns without restoring it will corrupt the caller, silently, only for the numbers the game overrode.
  - `r[]` entries are 128-bit slots and `r[2] = r[2]` copies the whole slot, not just the low word, so whatever is in the upper words of the completed `$v0` slot is written back into the caller's slot. Harmless if those words are always zero, undefined if not.
- **What would settle it** (none of it in the corpus): a per-handler decision — copy back the full context, or copy `$v0` plus an explicitly enumerated set — rather than `$v0` alone as a universal rule. Until then, treat "the handler only returns `$v0`" as an unverified precondition on every `SetSyscall` override, and say so when adding one.

### 3. `04-runtime-syscalls-stubs.md` and `db-syscalls.md` disagree about what syscall `0x02` is

- `04-runtime-syscalls-stubs.md` §3, step 2: *"Search online (ps2dev documentation) or the hardware bible to see what Syscall `0x02` is (`GsPutDrawEnv`)"*.
- `db-syscalls.md` says: `| 0x02 | SetGsCrt | a0=interlace, a1=mode, a2=field | void | impl | Initializes PCRTC display mode |`, and repeats it in the GS Interface summary as `SetGsCrt(0x02)`.
- `db-sdk-functions.md` resolves the other way again: `GsPutDrawEnv` is listed as an **SDK library function** (`impl`, `ps2_stubs_gs.inl`, "Sends draw env to GS"), not a syscall.
- The error is repeated inside `db-syscalls.md` itself, in "Syscall Debugging Workflow" step 2 (*"e.g., `GsPutDrawEnv`"*). Since step 2 is the prescribed lookup procedure, a reader following the corpus as written will misname 0x02 twice.

### 4. `db-syscalls.md` gives `0xFC` two different meanings

- Alarms table: `| -0x1E / 0xFC | iSetAlarm | same as SetAlarm | same | impl | Patched via SetSyscall — ps2tek §EE Patches |`
- Misc/Extended table: `| 0xFC | _kprintf | a0=fmt_ptr | void | impl | Debug print from RDRAM |`
- Both cannot hold. **[port]** `Dispatcher.cpp:61-64` resolves it in favour of the alarm reading: `case 0x18: case 0xFC: SetAlarm(...)`. So `db-syscalls.md`'s `_kprintf` row is wrong for this port — and a debug-print stub that silently became a timer-alarm call would be a very quiet failure.
- Related in the same table: `0x100 SetVTLBRefillHandler` is listed as a "number" alongside 8-bit numbers; the port spells that capability `0x82 InitTLB` (`Dispatcher.cpp:298-300`).

### 5. Alarm negative numbers: corpus vs port

| Number | `db-syscalls.md` | **[port]** `Dispatcher.cpp` |
|---|---|---|
| `0xFD` | `-0x1F / 0xFD` → **iReleaseAlarm** | `case -0xFD` → `iSetAlarm` |
| `0xFF` | `0xFF` → **iCancelAlarm** | `case -0xFF` (= `0xFFFFFF01`) → `iCancelAlarm`; positive `0xFF` has **no case** → `TODO` |

The port treats the alarm patches as *negative* forms only; the db lists two of them as positive. One of the two readings is wrong and the corpus does not say which. Unverified here — recorded, not resolved.

### 6. Other table rows where the corpus and the port disagree

- `0x3F GetHeapEnd` — db lists it (`impl`, alias for `0x3E`); the port has `case 0x3E` only, so a real `0x3F` falls through to `TODO`.
- `0x5A` — db: `QueryBootMode a0=param → $v0=value`. **[port]**: `case 0x5A: Copy(...)` (`Dispatcher.cpp:225-227`).
- `0x5B` — db: `GetThreadTLS a0=tid → $v0=tls_ptr`. **[port]**: `case 0x5B: GetEntryAddress(...)`.
- `0x7F` — db: `SetOsdConfigParam2 a0=config` (note in the same cell: *"ps2tek: MachineType/GetMemorySize nearby"*). **[port]**: `case 0x7F: GetMemorySize(...)`. Here `dead_ends#0065`'s recorded ref already says ps2sdk declares GetMemorySize and "each lands where the runtime expects it" — i.e. our project has already resolved this one in the port's favour, and the db row is the outlier.
- `0x79` / `0x7A` / `0x7E` — db lists all three; the port has `0x4A`/`0x4B` and `0x6E`/`0x6F` instead, with no case for `0x79`, `0x7A` or `0x7E`.
- `0x03 SetGsCrtKn`, `0x05`, `0x06`, `0x07`, `0x0B`, `0x0C` — all `impl`/`stub-safe` in the db, **no case** in the port (they reach `TODO`, which throws).
- `0x37` / `-0x38` — the db flags `-0x38` as *"⚠️ ps2tek BUG: no reschedule on current thread!"*, i.e. it is a distinct entry. **[port]**: both route to the same `SuspendThread`, so the reschedule difference the db warns about cannot be expressed.
- Port-only numbers absent from the db: `0x61`/`0x62` (`EnableCache`/`DisableCache`), `-0x68` (`iFlushCache`), `0x7C` (`Deci2Call`), `0x82` (`InitTLB`).
- `ctx->regs[4..7]` vs `ctx.gpr[4]`: the db's Lookup Protocol names the context array `regs`, while every code example in the db and in `04-runtime-syscalls-stubs.md` uses `gpr`. Grepping the codebase for `ctx->regs` finds nothing.

### 7. The ABI itself is an unrecorded contradiction

The db's Lookup Protocol, the "Syscall Debugging Workflow", and 04-runtime §3/§4 all describe an o32-shaped interface (args `$a0`–`$a3`, result `$v0`, number in `$v1`) but **no source states the register preservation/clobber contract**, and no source covers the guest-to-guest override return at all. Every downstream claim about "returning a value" from a syscall or an override handler therefore rests on an unstated assumption. This is the gap that Contradictions §2 sits on top of, and it is the single most useful thing this corpus is missing.

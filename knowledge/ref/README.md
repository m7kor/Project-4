# The reference corpus, and what it changed

The `resources/` tree (124 files, 54 MB) was present in this repository from
the start and unread for eight working rounds. That fact is worth recording
before anything in it, because it is the same shape as every other failure in
this project: the answer was available and the cost was paid anyway.

## What is in it

| file(s) | subject | size |
|---|---|---|
| `01-ps2-hardware-bible.md`, `db-ps2-architecture.md` | hardware, topology | 49 KB |
| `02-mips-r5900-isa.md`, `db-isa.md`, `db-registers.md` | EE ISA, registers | 71 KB |
| `03-ps2recomp-pipeline.md`, `06-game-porting-playbook.md`, `07-ps2-code-patterns.md`, `db-overlay-patterns.md` | pipeline, porting, overlays | 23 KB |
| `04-runtime-syscalls-stubs.md`, `db-syscalls.md`, `db-sdk-functions.md` | syscall ABI, stub patterns | 58 KB |
| `05-ghidra-ghydramcp-guide.md`, `12-pcsx2-mcp-playbook.md` | MCP tooling | 21 KB |
| `08-infinite-knowledge-base.md`, `10-agent-guardrails.md`, `11-operational-phases.md`, `13-decisional-brain.md` | process and agent rules | 44 KB |
| `09-ps2tek.md` | dense technical reference | 225 KB |
| `db-memory-map.md`, `db-ps2-index.md`, `db-vu-instructions.md`, `padspecs.txt` | memory map, VU, pad | 45 KB |
| `images/` | 100+ scanned figures with two catalogues | 53 MB |

Distilled notes for each cluster live beside this file as
`knowledge/ref/*.md`, one per cluster.

## What it changed immediately

Four recorded facts were wrong or incomplete before it was opened. Three of
them were wrong in the direction that cost real time.

**1. Syscall 0x83 is not a private number.** `db-syscalls.md` lists it as the
real kernel syscall `FindAddress` (`a0`=id, `$v0`=addr); 0x74 is `SetSyscall`,
0x3C `InitMainThread`, 0x3D `InitHeap`, 0x40 `CreateSema`. RE4 overriding it
with `SetSyscall` is legitimate and the override mechanism works; what was
wrong was concluding the number was not a kernel constant at all.
dead_ends#0065 now carries the correction inline.

**2. Branch-likely delay slots: verified, and our compiler was right all along.**
MIPS nullifies the delay slot when the branch is **not taken** — taken executes
it. Three independent sources agree. `ControlFlowEmitter` emits it inside
`if (branch_taken)`, which is correct. Two rounds earlier this nearly became a
reported bug against our own compiler. dead_ends#0078.

**3. The search range cannot contain its target, and that is arithmetic, not
semantics.** RE4's `FUN_002A1CE0` searches the KSEG0 range
`0x80000000..0x80080000`, which resolves to physical `0x0..0x80000` — the first
512 KB. `db-memory-map.md` places `.text` at `0x00100000`, `.data` at
`0x002XXXXX` and heap/stack at `0x00FXXXXX`. **That range contains no part of
the game image whatsoever**, and the keys being searched for live in `.data` at
`0x32ACD4`. Three rounds of host-side profiling could not have produced this
conclusion; one read of the project's own reference map did. dead_ends#0080.

**4. We are at milestone 1 of 5, and the corpus names all five.**
`06-game-porting-playbook.md` gives the order: boot/memory init →
`SifLoadModule` → CDVD reads → GS init → first frame. Our trace shows
`InitMainThread`, `InitHeap(0x4A0A58, 0x100000)`, `CreateSema` x2,
`SetSyscall` x2, and then the stall — with **no file-I/O syscall of any kind**.
The corpus also describes our exact symptom in advance: *"The game freezes.
The log stops printing, but the CPU core goes to 100%."*

It supplies a six-point checklist for "why is it stuck", of which the one that
applies to us is #3 — the first unresolved function addresses must be mapped.
At 95.72% byte coverage, they are not.

## The rule this adds

`dead_ends#0080` is the general form: **before paying for a search, check
whether the repository already contains the answer.** Eight rounds of profiling
answered a question that a file in the working tree answered outright.

The second rule is older and this corpus only confirms it: do not read a
meaning off a label. `#0065` is titled "read a syscall NAME off a `case` label"
and the corpus proves the failure was worse than that — the label was read off
the dispatcher, and the authority was a file nobody had opened.
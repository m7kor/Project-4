# PCSX2 memory-card and save-state study — 2026-10-08

## Nested-transfer observation, 2026-10-08

`PS2X_TRACE_GUEST_WORDS` observes up to sixteen aligned physical RAM words at
guest transfers and nested call exits. It logs changed snapshots, stops after
8192 rows, and never modifies guest memory. PCs identify observation boundaries,
not exact store instructions; same-value writes and changes restored between
observations remain invisible. The option is cleared by the packaged launcher.
`tools/analyze_ee_boundary_trace.py` produces a separate JSON report with a log
hash, selected transitions, malformed-row count and exhaustion status.

Run `20261008T123938Z-1ecf1b6f` lasted 211.687 seconds (configured timeout), with
93 state samples and 92 captured images. It observed 4954 changed snapshots
without exhausting the budget. For callback `0x122EB8`, state 10 advances to 20
after preflight returns to `0x123080`; state 21 calls `0x124758`. The next observed
result 4 follows `0x1247EC -> 0x123818`, then the game sets status `0x48000010`.
Inspection of the original instruction comments shows that `0x1247EC` is the
unformatted-card guard after `0x1247DC -> 0x122578`; the lower file operation has
not begun on that branch. Selected probes saw neither wrapper `0x124C50` nor
native `sceMcFormat` `0x2A97A0`. This identifies the observed failure branch,
not the root cause of bypassing the format path or the complete UI reply API.

The raw card still has 16384 erased pages and SHA-256
`47ebe237a3987f843fc19b0f801ce1edc1690768ef6b18e4b03a12ca6b298358`.
Evidence: `artifacts/research/20261008/pcsx2-memory/nested-menu-observation.json`
and `nested-menu-card.txt`. Build and all five verification checks passed;
packaging verified the original assets and matching executable hashes.
Saving and gameplay remain unverified.

The public PS2SDK reference explains why a repeated GetInfo result 0 alone is
not proof of formatting: `mcman_probePS2Card` accepts a nonzero cached format
value, including a negative unformatted state, while MCSERV reports formatting
separately. This is a reference implementation, not proof of byte-identical
behavior in the game's MCMAN 2.30/MCSERV 2.10 binaries. Sources inspected today:
[MCMAN probe](https://github.com/ps2dev/ps2sdk/blob/master/iop/memorycard/mcman/src/mcsio2.c)
and [MCSERV GetInfo](https://github.com/ps2dev/ps2sdk/blob/master/iop/memorycard/mcserv/src/mcserv.c).
Next: establish the UI reply contract and compare the original state-machine
execution at the 10-to-20 transition, then rerun Format/save/reopen end to end.

Pinned source revision: a9bd239ff971debe318c29e5a6895e6eb7d799e4. Source files and hashes are retained in
`artifacts/research/20261008/pcsx2-memory/manifest.json` (11 files).
External code was read as reference, not executed. PCSX2 source is GPL-3.0+.

## Three distinct mechanisms

1. In-game saves: original MCMAN/MCSERV operate a card filesystem through SIO2.
   A raw PS2 8 MB card has 16,384 pages of 512 data + 16 spare/ECC bytes:
   8,650,752 bytes on disk. Erase restores 16 pages at a time to FF. FileMemoryCard
   programming uses old_byte & incoming_byte; it cannot set cleared bits without erase.
   Newly created cards are blank, not automatically populated with a fabricated filesystem.
2. PCSX2 folder cards: a separate card filesystem implementation reconstructs
   pages, directories, FAT/superblock and metadata, generates ECC on reads and
   flushes cached changes. A folder of arbitrary game files is not equivalent to
   PCSX2 folder-card emulation. Its cache Save copies data, unlike the raw NAND backend.
3. Save states: CPU/IOP/FPU registers, TLB, cycles, RAM and EE/IOP subsystems are
   serialized, including GS/VU/VIF/DMA/SIF/IPU/GIF and SIO state. SIO2 saves card
   checksums and triggers automatic ejection if the current card differs when loading.
   That protects against combining an old machine state with changed persistent storage.
   It does not simply restore an old card image over current progress.

Sources:
- https://github.com/PCSX2/pcsx2/blob/a9bd239ff971debe318c29e5a6895e6eb7d799e4/pcsx2/SIO/Memcard/MemoryCardFile.cpp
- https://github.com/PCSX2/pcsx2/blob/a9bd239ff971debe318c29e5a6895e6eb7d799e4/pcsx2/SIO/Memcard/MemoryCardFolder.cpp
- https://github.com/PCSX2/pcsx2/blob/a9bd239ff971debe318c29e5a6895e6eb7d799e4/pcsx2/SIO/Memcard/MemoryCardProtocol.cpp
- https://github.com/PCSX2/pcsx2/blob/a9bd239ff971debe318c29e5a6895e6eb7d799e4/pcsx2/SIO/Sio2.cpp
- https://github.com/PCSX2/pcsx2/blob/a9bd239ff971debe318c29e5a6895e6eb7d799e4/pcsx2/SaveState.cpp

## Applied local correction

`iop_memory_card.cpp` previously persisted incoming raw bytes directly, allowing
0-to-1 programming without an erase. Writes now combine current and incoming
bytes with AND before persistence; erase still writes FF to the selected aligned
block. The transport checksum continues to cover incoming data as in PCSX2.
No automatic ECC generation is added to the native raw-card protocol: MCMAN
supplies actual data/spare bytes. Converting a data-only external image is a
separate operation and must never silently resize an existing card.

The regression uses its own temporary card, tests writing FF over 55, then AA
over 55, closes/reopens storage, erases a containing block, reprograms it and
checks that the next block survives. Before correction: 485/486 C++ passed and
this regression failed. After correction: 486/486 C++ and 103/103 Python plus
three tooling checks passed in `artifacts/verification/pcsx2-nand-after.json`.
Final verification `artifacts/verification/pcsx2-memory-final.json` also passes
486/486 C++, 105/105 Python and three tooling checks, including two read-only
inspection regressions. Runner build succeeded in 153.8 seconds.
This demonstrates raw NAND correctness, not successful RE4 saving.

## Read-only inspection tool

`python tools/inspect_ps2_card.py "Resident Evil 4/saves/cards/native-card-0.ps2"`
reports size, geometry, hash, FF-page count and presence of the PS2 format
signature. It supports known 8/16/32/64 MB raw or data-only sizes for inspection;
our native card runtime currently accepts only its fixed 8 MB raw size.
ECC and filesystem integrity remain explicitly unchecked. A format signature
alone is not a compatibility certificate. Report output cannot name the input card.

The actual game card is still all FF: 16,384 erased pages, no format signature,
SHA256 `47ebe237a3987f843fc19b0f801ce1edc1690768ef6b18e4b03a12ca6b298358`.
It was read without modification; older card copies remain retained.

## Remaining integration work

Runtime supports both file-backed HLE card operations and original native IOP
modules/raw SIO2. They are distinct storage implementations, not interchangeable
views of one card. A successful HLE GetInfo must not be taken as evidence of a
formatted raw card. Native RPC dispatch is tried before HLE fallback; selected
trace guest_function=0 is not by itself proof that HLE handled a request.

The latest client run used the bundled runner after the GS depth correction:
`20261008T041308Z-bdf951ad`, 151.485 seconds. GetInfo dominated the selected
256-call trace budget. Returns of zero from the EE client indicate successful
asynchronous submission; they do not prove the final card result. The trace
must watch the completion callback and 192-byte end parameter (0x464F00), final
receive result and actual game state before assigning the save failure to Format.
Missing Open/Format after shared budget exhaustion is inconclusive.

Next steps: trace completion and end-parameter payload with independent budgets;
verify native card format/create/save/close/restart/load from inside RE4; only then
verify a copied card with PCSX2/mymc. Save-state implementation needs coordinated
scheduler quiescence, versioned serialization, complete subsystem coverage and
card-change detection before it can be promised. Do not substitute a RAM dump.

## Targeted scheduler observation

`PS2X_TRACE_EE=1` with `PS2X_TRACE_EE_PCS=0x2A9448,0x2A946C`
selects only those scheduler entry/resume PCs for the existing 8192-row budget.
The optional selector accepts at most 16 aligned physical code addresses; an
empty/invalid selection does not turn into unrestricted tracing. Options are
read once on the EE executor. `PS2X_TRACE_WORDS` still selects at most 16 aligned
RAM words, useful for end parameter 0x464F00/04/90, result 0x465FC0 and game
outputs 0x3CF870/74/78. It does not modify guest registers, memory or scheduling.
This catches queued callbacks that are not nested dispatchGuestBranch calls.
Without the new selector, the existing trace behavior is retained.

## Completion payload observed

Run `20261008T042746Z-43da1b58` used the new selected scheduler trace, ran
151.485 seconds and reached EE field 812. It recorded 329 selected rows (328
at GetInfo continuation 0x2A946C and one at 0x2A9448), well below the 8192 limit.
The actual end parameter consistently held type 2, free 0 and format 0. The
final receive result was -2 initially, then 0 for 327 continuation samples.
This verifies that the original callback and guest destination data are reached;
it does not establish a transport failure. The raw image remained all FF.

The last captured menu still asked to create system data with No selected.
Thus the earlier eight-field input sequence is not proven to trigger Format;
absence of a Format call cannot be treated as a diagnosed Format failure.
A separate fixture `artifacts/research/20261008/native-pad-create-system-long.csv`
holds Up/Cross for 32 EE fields at later ticks and leaves longer release gaps.
The integration observation must check actual UI transitions and native
Format/Open RPCs before deciding which storage path to repair.
Evidence: `artifacts/research/20261008/pcsx2-memory/completion-observation.json`.

Later-input run `20261008T043215Z-d8d3017f` completed its configured 210-second
observation (210.093 seconds, EE field 1618, 92 captured frames). All eight
Up/Cross sampler transitions occurred with 32-field holds and 68-field release
gaps. No selected Open/GetDir/Format guest call appeared, while selected card
RPCs remained Init/GetInfo. This call selector excluded repeated GetInfo, so its
256-call budget was not exhausted. Raw card hash remained unchanged. Visual
inspection of diagnostics/frame-11040.png shows the game's "Failed to format"
message; frame-8040.png shows Yes selected. The replay therefore reached the
format-failure UI. No native Format request was observed, so the next target is
the game's format wrapper and its preconditions, rather than assuming an erase
failure or an unconsumed confirmation. Evidence: `long-input-observation.json` beside the pinned
PCSX2 research files. Full in-game save/load remains unverified.

## Menu preflight isolated

Three further 210-second observations completed: `20261008T044214Z-50db0466`,
`20261008T044649Z-237a3417`, and `20261008T045201Z-1f531afa`. The last run
captured the first preflight call at 0x123078, its completion at 0x123EB4 and
return to 0x123080. Final result was 0, type 2, format 0, card flags 1 and
outer state 10; shared word 0x3CF864 remained 0. The later preflight caller
0x1230DC and actual Format wrapper were not observed. Static branch 0x12309C
goes to state 20 when that shared word is zero. Its UI writers and meaning
must be traced before changing the original logic. Format-failure text alone
does not establish a failed native erase or write. The raw card hash remained
unchanged. Evidence: `menu-state-observation.json` in the research directory.

These observations intentionally replace physical pad input with replay.
Normal `Resident Evil 4/Play.cmd` clears `PS2X_NATIVE_PAD_REPLAY` and uses
the physical controller; a replay window cannot verify physical-pad usability.

## Changes between scheduler dispatches

Use `PS2X_TRACE_EE=1`, `PS2X_TRACE_EE_CHANGES=1`, and RAM addresses in
`PS2X_TRACE_WORDS` to emit only boundaries where at least one watched word
changed. Leave `PS2X_TRACE_EE_PCS` unset to observe every boundary. With a PC
selector, only changes detected at those selected boundaries are emitted.
The previous dispatch PC/thread is context, not the address of an exact store:
nested calls and events can execute between samples. The 8192-row budget now
emits an explicit exhaustion notice. Empty watches produce no change rows.

Run `20261008T073822Z-ce2fcbed` completed its observation after 211.515 seconds,
with 92 frame files and 19 change rows, without exhausting the trace. It saw
state 10 become 20 following continuation 0x123080, then error 0x48000010 and
state 100. Word 0x3CF864 stayed zero until error handling set -1. Neither the
Format wrapper nor native Format call was observed. The card hash is unchanged.
Next: trace the UI response interface and the shared word's writers; this
evidence does not justify modifying the original menu branch or card contents.
Evidence: `menu-boundary-observation.json` in the research directory.

The rebuilt runtime marks replay windows `INPUT REPLAY - physical controller
disabled`. Normal Play.cmd clears replay. Build completed in 197.8 seconds;
`menu-boundary-trace.json` passes all five checks, and the packaged runner
matches the build. These diagnostic/UI changes do not fix in-game saving.

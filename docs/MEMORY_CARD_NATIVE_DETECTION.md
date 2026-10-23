# Memory-card service and native RE4 detection

Latest update: [SIO2_NATIVE_CARD.md](SIO2_NATIVE_CARD.md). The native reset
now succeeds with real SIO2 packets, DMA output and connected status.
GetInfo still fails; newly reached SECRMAN ordinal six is missing. The
following sections preserve earlier investigations and evidence.

The HLE directory RPC previously returned zero entries unconditionally.
A regression creates a persisted ten-byte save and queries its exact name
through an XMCSERV packet. Before the fix, three assertions failed; after
routing GetDir to the filesystem backend, the name, length, and one-entry
write limit pass. MemoryCardRequest now carries six EE n32 arguments,
including the directory table in $t1. The destination range is checked
including normalized-address continuity, so crossing the end of RAM is
rejected even when individual addresses alias into valid RAM.

Evidence: `artifacts/verification/mc-directory-before.json` (470/471 C++),
`artifacts/verification/mc-directory-final.json` (471/471 C++, 101/101 Python
and three tool self-checks). This verifies one persisted-file directory
query and bounds; directory pagination, full metadata updates, card capacity,
and game save/load remain unverified.

## Original IOP path is authoritative for RE4

Source `IopSubsystem::handleRpc` gives original registered IOP RPC servers
priority over HLE. The game loads an original memory-card server. Its
sampled init reply contains result zero, MCSERV 0x210 and MCMAN 0x230,
meeting the game's checks at 0x2A8F50 (0x20A) and 0x2A8FA0 (0x20E).
The HLE constants 0x205/0x206 are not evidence of a version failure in
this native run, and were not changed to force acceptance.
Evidence: `artifacts/research/20261007/mc-init-version-evidence.json`.

Run `20261007T181658Z-d47a3d87` lasted 181.593 seconds and ended at the
configured timeout. Four original GetInfo calls completed and returned -11
for port zero, slot zero, requesting type, free clusters, and format. All
four snapshots have a zero word at the native transfer-state address
0x648C0. The error is named sceMcResFailResetAuth by PS2SDK, but the
error name alone does not establish the exact executed branch: the
native GetInfo wrapper can also map a failed free-cluster query to -11.

Static snapshot disassembly narrows the reset path: MCMAN 0x548CC calls
SIO2MAN ordinal 25 via 0x64308 and tests the transfer-state word's upper
nibble against 0x1000. Failure returns -1 to its caller; the PS2 probe
at 0x54B10 maps failure to -11. A selected PC sample at 0x54954 can
measure that return, without bypassing detection. The emulator currently
has generic backing storage for SIO2 registers and no FIFO/device/DMA11/12
protocol engine; this is a concrete implementation gap, not yet proof of
which transfer failed.

Evidence: `artifacts/research/20261007/mc-native-getinfo-evidence.json`,
`mcserv-native-getinfo.json`, `mcman-native-reset-auth.json`,
`mcman-native-ps2-probe.json`, and `mcman-native-sio2-import.json`.

## Primary references and next validation

PS2SDK's common memory-card definitions and native RPC implementation:
- https://github.com/ps2dev/ps2sdk/blob/master/common/include/libmc-common.h
- https://ps2dev.github.io/ps2sdk/mcserv_8c_source.html

Eight unmodified PCSX2 SIO2, memory-card protocol, storage, and filesystem
references were extracted from the already pinned, hash-verified archive.
Their paths and hashes are in
`artifacts/research/20261007/sio2-reference/manifest.json`. These are
research references, not newly linked code. The protocol code is GPL-3.0+.

`PS2X_TRACE_IOP_SIO2` enables at most 128 aligned backing-word observations
per IOP memory reset, for SIO2 0x1F808200..0x1F808280 and DMA11/12
0x1F801540..0x1F801558. The trace includes read/modify/write backing reads;
it is not an instruction-width trace and does not alter device behavior.
The next runtime capture should pair it with
`PS2X_TRACE_IOP_PC=0x54954` and `PS2X_IOP_RPC_CAPTURE=0x80000400:0x1`.
No original game asset was edited or deleted.


## Executed reset-auth path and dropped DMA setup

Run `20261007T211854Z-87f3a902` completed its configured 181.5-second
capture. All 64 selected samples at native PC 0x54954 have v0=0xFFFFFFFF:
the reset-auth function actually returns -1, rather than merely resembling
a failing branch in static disassembly. Its captured outgoing packet begins
`81 f3 00 00`. The first 128 SIO2 word observations show command setup and
START control, with command status 0x1F80826C remaining zero. The trace is
capped, so absence after the cap is not evidence of no later activity.

Native SIO2MAN 0x1CAC4 uses DMACMAN ordinal 28 for slice setup and ordinal
32 for start on channels 11/12. Those imports were silently ignored by the
emulator's generic DMACMAN fallback. An executable IRX regression calls
both imports with the fifth argument on the o32 stack; it fails before the
fix (no acceptance, address, block count, or start control). That direct
baseline invocation also has an unrelated working-directory test failure;
see `artifacts/verification/dmac-slice-before.log`, not an all-suite clean
baseline claim.

The source now prepares MADR, BCR, slice-direction control and the start
bit through the existing MMIO/device path. This does not fabricate DMA
completion or implement the missing SIO2 device protocol. Channels 0..12
are covered by the existing register mapping; FDMA 13/14 remain unsupported.
PS2SDK source specifies the 24-bit address, packed block count, direction
and receive control bit, and OTC rejection:
https://github.com/ps2dev/ps2sdk/blob/master/iop/system/dmacman/src/dmacman.c

Evidence: `artifacts/research/20261007/mc-sio2-runtime-proof.json`,
`sio2-native-send.json`, and `sio2-native-dmacman-import.json`.
The pre-DMAC-fix build and tooling verification passed:
`artifacts/verification/build-mc-sio2-trace.log` (144.3 seconds),
`artifacts/verification/mc-sio2-final.json`. The DMAC fix passes all 472 C++ tests, 101 Python tests and three tool
self-checks: `artifacts/verification/dmac-slice-final.json`. The runner
built in 141.1 seconds: `artifacts/verification/build-dmac-slice-fix.log`.
Run `20261007T212802Z-11c32ad3` ended at its configured timeout after
181.468 seconds, with 83 decoded frames (36 nonblack). The trace now shows
DMA11 MADR=0x64958, BCR=0x10040, CHCR=0x1000201, and DMA12 MADR=0x66158,
BCR=0x10040, CHCR=0x41000200. Four original GetInfo calls still return -11,
and all 64 reset-auth return samples remain -1. Visually inspected frame
8400 retains the readable warning. This proves the import repair inside
the game, and confirms that it does not complete card detection. Evidence:
`artifacts/research/20261007/dmac-slice-native-proof.json`.


## Required next device implementation

Keep the original MCMAN/MCSERV execution path. The SIO2 backend must own
the sixteen command descriptors, port control, input/output FIFOs, connection
status, interrupt status/acknowledgement, and DMA11/12 RAM movement.
Processing must respect command lengths and DMA block padding: the observed
reset-auth command is four bytes within a 64-word DMA block. Emit SIO2 IRQ17
and DMA completion only when the corresponding work actually completes.

The card device must implement probe, F3/F7/XOR authentication exchanges,
specifications, terminator, sector addressing, page reads/writes and block
erases using persistent storage with correct geometry and spare/ECC bytes.
A blank card is unformatted; do not report a formatted card without valid
filesystem data. Validate formatting through original MCMAN, persist a save,
restart, and compare the loaded contents. Preserve existing save data.

The same bus also serves the controller. Full original pad negotiation and
host button input are needed to advance through prompts and verify gameplay.
Passing card detection or displaying a warning is not the completion gate.

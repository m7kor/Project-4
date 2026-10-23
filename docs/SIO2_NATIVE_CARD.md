# Native SIO2 and raw memory-card backend — 2026-10-08

Latest update: [SECRMAN_AUTHENTICATION.md](SECRMAN_AUTHENTICATION.md).
The authentication orchestrator is implemented and RE4 now detects the
card and offers to create system data. The evidence below is the earlier
transport-only run; game save/load remains unverified.

The native IOP now has an opt-in SIO2 register/FIFO implementation and a
raw PS2 memory-card protocol backend. DMA11 consumes input blocks, DMA12
copies available replies to checked IOP RAM ranges, and completed transfers
advance MADR and clear CHCR's start bit. An output DMA started before input
remains pending. Completion events use a queue so both DMA channels and the
SIO2 interrupt are retained. The emulator drains this queue through its
existing interrupt-handler scheduling path. SIO2 ISTAT uses write-one-to-clear.

The raw card has 16,384 sectors of 512 data bytes plus 16 spare/ECC bytes.
Its 8,650,752-byte image is stored at the host memory-card root as
`native-card-0.ps2`; a new image is all FF and is **unformatted**. Original
MCMAN owns formatting, directory layout and ECC generation. Existing images
must have the correct size and are loaded without truncation. Writes and
16-sector erase operations update persistent storage. This is not a claim
that a game save or a formatted filesystem has been verified.

Implemented PS2 commands include probe, sector selection, geometry,
terminator negotiation, read/write/end, erase, boot acknowledgement,
F3/F7 and F0 authentication packet responses. Missing port-two cards and
native pads return device absence. PS1 cards, multitaps, controller input,
encrypted-file operations and full authentication orchestration remain work.
Unsupported or truncated card packets are not acknowledged; bad sector
checksums and out-of-capacity sectors prevent storage writes.

## Validation

Build: `artifacts/verification/build-sio2-native.log`, exit zero, 173.9 seconds.
Verification: `artifacts/verification/sio2-native-final.json`, 474/474 C++,
101/101 Python and three tool checks. New regressions exercise F3's five-byte
reply, geometry/XOR, blank unformatted data, persistent save bytes across
reopen, bad/truncated/out-of-range requests, erase alignment and neighboring
block preservation, terminator positions and F0 XOR. An MMIO/DMA regression
uses RE4's descriptor 0x140572 with a 256-byte padded input, receives the
exact five-byte response plus zero padding, verifies guard bytes and both
completions, and exercises interrupt acknowledgement, PIO and missing-card
responses. This coverage does not certify every command or transfer mode.

Native run `20261007T214759Z-687f01a3` was launched with:

```powershell
$env:PS2X_IOP_SPU2_NATIVE='1'
$env:PS2X_IOP_SIO2_NATIVE='1'
$env:PS2X_TRACE_IOP_SIO2='1'
$env:PS2X_TRACE_IOP_PC='0x54954'
$env:PS2X_IOP_RPC_CAPTURE='0x80000400:0x1'
python -m ps2l run 'game/Resident Evil 4 (USA)/SLUS_211.34' --timeout 180 --diagnostics --out artifacts/runs
```

It ended at the configured timeout after 181.516 seconds, with 83 decoded
frames and 34 nonblack frames. All 64 selected native reset-auth epilogue
samples now have v0=0, versus FFFFFFFF in the previous run. Four completed
native GetInfo snapshots show status 0x1100 and actual DMA output
`00 00 00 2b 55`. **All four GetInfo replies still return -11**.
The screenshot `frame-8400.png` was visually inspected: the readable
no-card warning remains. This is a proven reset/transport improvement,
not successful card detection or game save/load.

The newly reached code invokes missing `secrman:6` version 0x103 at
0x64538; the log contains 226 such occurrences. MCMAN's authentication
wrapper at 0x5487C calls that import and checks its result. PS2SDK names
ordinal six `SecrAuthCard`; it orchestrates card packets and MechaCon
operations through registered callbacks. The next step is implementing or
integrating that real orchestration, including failure propagation and
MechaCon behavior, then measuring the original PS2 probe return and GetInfo.
Do not replace it with an unconditional success or skip the game warning.

Evidence: `artifacts/research/20261007/sio2-native-proof.json`,
`mcman-native-auth-start.json`, `mcman-native-secrman-import.json`.
`game-file-preservation-sio2.json` rehashes all eight original extracted
files: every size and SHA-256 matches the earlier local audit. The raw
card is additional state; no original game file was edited or deleted.

## Primary references

The pinned PCSX2 archive and nine unmodified reference files are recorded
in `artifacts/research/20261007/sio2-reference/manifest.json` (GPL-3.0+).
The new protocol implementation is GPL-3.0-or-later with source attribution.
The additional IopHwWrite reference establishes SIO2 ISTAT's acknowledgement
semantics. These reference files are not linked into the runner.

- [PS2SDK SECRMAN exports](https://github.com/ps2dev/ps2sdk/blob/master/iop/security/secrman/src/exports.tab)
- [PS2SDK authentication orchestration](https://github.com/ps2dev/ps2sdk/blob/master/iop/security/secrman/src/secrman.c)
- [PS2SDK card packet helpers](https://github.com/ps2dev/ps2sdk/blob/master/iop/security/secrman/src/CardAuth.c)
- [PS2SDK MechaCon operations](https://github.com/ps2dev/ps2sdk/blob/master/iop/security/secrman/src/MechaAuth.c)

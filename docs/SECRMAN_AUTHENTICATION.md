# Native card authentication and RE4 detection — 2026-10-08

SECRMAN ordinal 6 now executes the complete card authentication exchange
instead of falling through to an unhandled import. Ordinal 7 resets the
card and device session. The implementation follows PS2SDK's SecrAuthCard
ordering and checks transfer completion, SIO2 status, acknowledgement,
terminator and read checksums. Any rejected exchange fails authentication
and resets both endpoints. It does not return success just because the
ordinal was called.

The serial endpoint invokes the command callback registered by original
MCMAN, preserving its registered GP. In RE4 this is 0x54F7C. Packets and
buffers reside in checked IOP allocations and are released after each
synchronous call. The 148-byte SIO2 structure layout is established by
disassembly of this game's original SIO2MAN send/receive routines:
ctrl1/ctrl2 at 4/20, descriptors at 40, PIO lengths at 108/112 and pointers
at 116/120. This layout has not been certified for other SIO2MAN versions.

The virtual MechaCon endpoint uses the pinned PCSX2 challenge bytes for
commands 0x84/0x85, checks command length and session ordering, and carries
the complete 0x80..0x88/0x8F authentication sequence. It is a virtual-device
model, not physical MagicGate cryptography or encrypted KELF support. It
does not implement unrelated CDVD security commands. Card formatting and
filesystem contents are still owned by original MCMAN.

## Tests and actual game evidence

Build `artifacts/verification/build-secrman-auth.log`: exit zero, 171.2 seconds.
Verification `artifacts/verification/secrman-auth-final.json`: 475/475 C++,
101/101 Python and three tool self-checks. The new test authenticates against
the raw-card protocol, checks the full independent 34-exchange transcript,
injects failure at each exchange and verifies rejection/reset, and rejects
a corrupted read checksum, missing transport and invalid device command
order/length. This does not prove all SECRMAN functionality.

Native run `20261007T220323Z-0d6f907f` used:

```powershell
$env:PS2X_IOP_SPU2_NATIVE='1'
$env:PS2X_IOP_SIO2_NATIVE='1'
$env:PS2X_TRACE_IOP_SECRMAN='1'
$env:PS2X_TRACE_IOP_PC='0x51ab0'
$env:PS2X_IOP_RPC_CAPTURE='0x80000400:0x1'
python -m ps2l run 'game/Resident Evil 4 (USA)/SLUS_211.34' --timeout 180 --diagnostics --out artifacts/runs
```

It ended at the configured timeout after 181.515 seconds. The report's
fault detector has no matched faults; this is not proof of absence of all
errors. There are 82 decoded frames, 33 nonblack. The 23 serial authentication
packets all execute the original 0x54F7C handler with completion=1,
result=1 and SIO2 status 0x1100. The native PS2 probe return sampled at
0x51AB0 is FFFFFFFE (-2), versus earlier reset/transport failure. Four
completed original GetInfo snapshots return **-2, 0, 0, 0**; all contain
card type 2 and format state -2. The raw image remains entirely FF at
8,650,752 bytes: no formatting or system-data write has been invented.

`frame-8400.png` was visually inspected: the game now says no system data
is present on the memory card and asks **Create system data file now?**
with Yes/No choices. The previous no-card warning is gone in this run.
Intermediate black frames are not by themselves evidence of a rendering
regression; the final captured prompt is readable.

Evidence: `artifacts/research/20261007/secrman-auth-native-proof.json` and
the run's original logs, snapshots and image. All eight original extracted
game files are rehashed against the prior local audit in
`game-file-preservation-secrman.json`; no original file was edited/deleted.

## Remaining work

System-data creation, formatting, game save/load after restart and full
gameplay are **not verified**. Native pad attachment/input is still absent
in IopSio2. Next, implement and test native pad negotiation and host input,
then exercise the game's Yes choice and capture original format/write RPCs,
persistent storage changes and readback after restarting. Keep the existing
card image intact. SIO2 remains opt-in until broader runtime validation.

## Primary references

- [PS2SDK authentication sequence](https://github.com/ps2dev/ps2sdk/blob/master/iop/security/secrman/src/secrman.c)
- [PS2SDK packet construction and validation](https://github.com/ps2dev/ps2sdk/blob/master/iop/security/secrman/src/CardAuth.c)
- [PS2SDK export ordinals](https://github.com/ps2dev/ps2sdk/blob/master/iop/security/secrman/src/exports.tab)
- PCSX2 commit `646df006a4688063e56c0826e7ea4b8bb0c112c4`,
  `pcsx2/CDVD/CDVD.cpp`, extracted unmodified from the hash-verified archive.
  Its provenance/hash is recorded in `sio2-reference/manifest.json`.

The implementation has GPL-3.0-or-later source attribution.

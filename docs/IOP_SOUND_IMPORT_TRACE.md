# Original sound transfer and handler registrations

`PS2X_TRACE_IOP_SOUND=1` captures resolved guest `libsd` imports before
execution. It records ordinal, IOP cycles, import PC, return address, resolved
guest target, GP, four register arguments, the fifth o32 argument at SP+16,
and CPU interrupt control. The fifth argument is read only from valid IOP
RAM, with widened address arithmetic and an explicit validity flag.

The [PS2SDK import table](https://github.com/ps2dev/ps2sdk/blob/master/iop/sound/libsd/include/libsd.h)
identifies voice/block transfer ordinals 17/18 and transfer/SPU interrupt
handler registration ordinals 26/27. Init/quit ordinals 4/2 are also traced.
These are separate APIs: registration
27 must not be treated as replacement of a core's DMA transfer handler.
The logger observes the original guest exports and does not replace them.

There are separate per-instance limits: 64 init/quit/handler entries and 128
transfers per IOP reset. Status polling is excluded so it cannot consume
the registration budget. Direct calls to export addresses do not pass
through this import trace. A captured entry does not prove that the
function returned or completed a transfer.

```powershell
$env:PS2X_TRACE_IOP_SOUND='1'
$env:PS2X_TRACE_IOP_IRQ='1'
$env:PS2X_IOP_RPC_CAPTURE='0x53544154:2'
python -m ps2l run 'game/Resident Evil 4 (USA)/SLUS_211.34' --timeout 180 --diagnostics --trace-disc
python tools/diagnostics/iop_sound_audit.py artifacts/runs/<capture>/stderr.txt --out artifacts/research/20261007/sound-import-audit.json
```

`iop_sound_audit.py` retains event order, records per-core handler replacement
and associates transfers with the last observed registration candidate.
A decreasing cycle counter starts a new segment without inheriting handler
state. Init and quit entries invalidate both previous handler candidates,
without claiming that the calls returned or that the live slots are zero.
It rejects malformed records, invalid handler cores and voice
transfers whose size was not captured. Empty input is not usable evidence;
reaching a known trace bound is explicitly marked. These observations need
cross-checking against RAM snapshots and actual completion callbacks.

Four regressions cover cross-core replacement, cycle reset isolation,
missing/invalid evidence, cap reporting and the distinction between SPU IRQ
and transfer handler registration. They do not certify game audio.

`PS2X_TRACE_IOP_PC` optionally selects one aligned uint32 guest PC (decimal
or hexadecimal). At most 64 pre-instruction samples per reset record cycle,
PC, RA, GP, SP, v0 and interrupt control. The selector is read at reset;
invalid or absent values disable it. It does not modify registers, memory,
or guest dispatch. A PC match is not automatically a function return:
establish that point from the original code and correlate the caller.
For the CSE transfer consumer, original JAL at 0x33D80 calls the LIBSD
import and continues at 0x33D88, whose next instruction does not produce v0.
`PS2X_TRACE_IOP_PC='0x33d88'` therefore observes its returned value when
the captured RA also matches that continuation.

## Observed RE4 sequence

Build succeeded in 160.0 seconds (92,746,240 bytes). Runner SHA-256:
`1ad97494273750a0a294892d83e8ba43288c9a6de6e9e1367e1e13cd704ca9e3`.
`artifacts/verification/iop-sound-import-trace.json` records 464/464 native
and 89/89 Python tests passing, plus the tooling self-checks.

Run `20261007T115707Z-eb1ddf25` lasted 180.203 seconds: 84 decoded frames,
all black, no faults matched by the detector. Original ELF hash is unchanged.
The audit captured three registrations and seven transfers without reaching
either trace limit:

| IOP cycle | Original observed entry |
|---|---|
| 1,487,901 | CSE voice transfer, core 0, mode 8, 16 bytes |
| 1,517,657 | CSE registers 0x2DFD4 / argument 0x36D48 for core 0 |
| 1,518,011 | CSE registers 0x2DFD4 / argument 0x36D58 for core 1 |
| 7,724,665 | Stream code registers 0x40830 / argument 0x48254 for core 0 |
| 7,724,692 | Stream block transfer, core 0, mode 0x10, size argument 0x1000 |
| 37,236,402..37,588,701 | Five CSE voice-transfer entries, core 0, mode 0, source 0x3A238, SPU destination 0x5020, size 1024 |

The fourth early RAM snapshot confirms core-zero callback 0x40830 and an
occupied transfer slot for sender 23, with reply bytes 8..11=01/01/00/10.
Core-one callback is zero, despite its earlier registration. Thus a last
observed registration is not sufficient to certify live handler state.

Original stream code at 0x40938..0x40980 saves the old callback argument at
0x48620 and old function at 0x48618. Both are zero in the fourth snapshot.
Static original LIBSD initialization at 0x2BB44 explicitly clears both
callback slots at 0x2BBE0/0x2BBE4; original `sceSdInit` at 0x2BDE4 calls
this initializer. This identifies a concrete reset path to trace, but does
not yet prove when it executed between the observed registrations, or why
the original guest reaches that ordering. Init, quit, and direct export
calls are outside the current selected import trace.

Next evidence: record initialization/quit alongside registration and transfer
returns, then establish callback save/restore ordering and actual DMA
delivery. Do not replace the active callback or wake the worker artificially.
Snapshots remain bounded early observations rather than final IOP state.

Evidence: `artifacts/research/20261007/sound-import-audit.json`,
`sound-import-summary.json`, `stream-saved-transfer-handlers.json`,
`stream-init-transfers.json`, `libsd-init-mode.json` and
`libsd-init-implementation.json`. Static disassembly is not execution proof.

## Follow-up: initialization ordering and actual transfer returns

The extended logger adds init/quit and an optional selected-PC sample.
Build succeeded in 152.6 seconds (92,747,776 bytes), SHA-256
`3768766b7fc53beb8d52b9918f7134143f3572e5e49f16b5ae91acbbb799dc1c`.
Validation: 464/464 native and 90/90 Python tests, including conservative
candidate invalidation on init/quit. Run `20261007T120935Z-9ea4e57c` lasted
180.203 seconds; 84 decoded frames were all black. No faults matched the
detector, and the original ELF hash is unchanged.

Two original `sceSdInit(0)` entries are now observed: CSE at cycle 1,466,464
(continuation 0x2F048), then the other module at cycle 1,518,518
(continuation 0x3AE2C), immediately after CSE's core registrations at
1,517,657 and 1,518,011. This is a real observed initialization between CSE
registration and later stream setup. The original initialization's clearing
code, zero saved stream callback and zero live core-one callback corroborate
loss of the CSE registrations. Why the guest reaches this ordering still
requires establishing module/startup ownership; do not disable init globally.

At established continuation PC/RA 0x33D88, five return samples show four
values 0xFFFFFF2E (-210), then 0x400 (1024). Original VoiceTrans's branch at
0x28DE8 produces -210 when its transfer-state check is nonzero; the final
accepted size therefore disproves permanent rejection of this request.
All five points are inside the caller's critical section (control=0), so
these samples alone do not establish whether its later resume succeeds.

The accepted transfer scheduled IRQ 0x24 at cycle 37,589,009, due at
37,589,521. All five recorded IRQ returns occur earlier in the log; no
post-acceptance dispatch was recorded. The trace did not reach its cap, but
this is still bounded process evidence, not a complete hardware trace.
The next probe must inspect interrupt restoration after 0x33D8C's resume
call, pending delivery, and callback restoration. Wrong callback ownership
alone is not yet sufficient to explain absence of interrupt delivery.

Evidence: `artifacts/research/20261007/sound-init-audit.json` and
`sound-init-summary.json`. Four early RPC pairs again show an occupied slot
for sender 23 and stream callback 0x40830; they do not establish final IOP
state. The PCSX2 reference connector described in
`resources/12-pcsx2-mcp-playbook.md` has no callable tools in this session,
so no matching reference timeline is claimed.

## Follow-up: control after resume

Run `20261007T121735Z-1598d202` uses the same runner but samples
PC/RA 0x33D94, after the original caller's CpuResumeIntr import.
It lasted 180.109 seconds and produced 85 black frames. All five
samples still have control=0, including the accepted transfer's
continuation. The disabled state therefore persists beyond this call;
its earlier owner remains unidentified. Full selected fields are in
`artifacts/research/20261007/sound-post-resume-summary.json`.

Independent PS2SDK comparison also exposed incorrect success returns
for repeated CPU interrupt suspension/disable. These are now corrected
with a failing-before executable IRX test; see
[IOP_CPU_INTERRUPT_ERRORS.md](IOP_CPU_INTERRUPT_ERRORS.md).

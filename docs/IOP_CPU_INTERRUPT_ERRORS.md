# IOP CPU interrupt return values — 2026-10-07

The native HLE returned success from both `CpuSuspendIntr` (ordinal 17)
and `CpuDisableIntr` (ordinal 8) even when interrupts were already disabled.
PS2SDK's non-INTRMANP implementation returns `KE_CPUDI` (-102) in that
situation. Suspend still writes the previous state when a state pointer is
provided; a null pointer does not change the return-value contract.

Primary references:

- [PS2SDK intrman implementation](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/intrman/src/intrman.c)
- [PS2SDK kernel error constants](https://github.com/ps2dev/ps2sdk/blob/master/iop/kernel/include/kerr.h)

The local implementation now saves the previous control state before
disabling interrupts and returns the appropriate value. It does not force
interrupts on when the guest resumes a saved disabled state.

An executable synthetic IRX exercises the actual emulator import resolver:
enable, outer suspend, nested suspend, inner resume, outer resume, repeated
disable, and suspend with a null pointer in both control states. The guest
records return values, saved states and observed hardware control in RAM.
Before the fix, 464/465 native tests passed; the new case failed exactly
its nested-suspend, repeated-disable and null-pointer-disabled assertions.
After the fix, verification passed all 465 native and 90 Python tests,
along with three tooling self-checks.

Evidence: `artifacts/verification/intrman-disabled-before.log`,
`intrman-disabled-after.json`, `build-intrman-disabled-after.log`.

## RE4 evidence preceding this fix

Run `20261007T121735Z-1598d202` lasted 180.109 seconds and produced
85 decoded frames, all black. At the original continuation PC/RA
0x33D94, immediately after the call to `CpuResumeIntr` at 0x33D8C,
all five samples show control=0 and return value=0. This includes the
continuation after the accepted 1024-byte voice transfer. Thus disabled
control persists past the consumer's resume; the previous observation was
not merely taken inside its critical section.

This does not identify which earlier caller owns the disabled state or
prove that the return-value defect caused the black screen. The stream's
original nesting wrapper at 0x3DC78 saves Suspend's return status at
0x48224 and uses it when deciding whether to resume in 0x3DCC4, so accurate
error values matter to actual guest control flow. Further evidence must
establish the original disable/resume sequence and scheduling boundaries.
Do not force an enable, skip sound initialization or wake a worker manually.

Evidence: `artifacts/research/20261007/sound-post-resume-summary.json`.

## RE4 result with the correction

Runner build passed in 154.3 seconds, 92,747,776 bytes, SHA-256
`bd81cb2991976772e323198fcb53c1b97cf378729593746bd5da3866ab592676`.
Run `20261007T122633Z-47851dd1` lasted 180.203 seconds. Its 84 decoded
frames were all black, with no image decode errors or detector-matched
faults. Original ELF SHA-256 remains
`465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad`.

All four early post-STAT snapshots now record 0xFFFFFF9A (-102) at
0x48224, with nesting depth zero at 0x48220 and saved control zero at
0x48614. This confirms that the corrected return value reaches the
original stream wrapper. All five post-resume samples still show
control=0. Seven LIBSD transfer entries and three registrations were
observed without reaching the trace cap; the five captured IRQ returns
still precede the later accepted transfer. The correction does not resolve
the persisted disable or establish full audio compatibility.

Next: capture the earlier disable/resume ownership and inspect thread
scheduling boundaries. The scheduler uses fixed instruction slices, but
whether such a boundary is responsible here has not been established.

Evidence: `artifacts/research/20261007/sound-disabled-error-summary.json`,
`sound-disabled-error-audit.json` and `sound-critical-state-after.json`.

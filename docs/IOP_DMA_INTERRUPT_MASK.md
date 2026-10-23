# IOP DMA interrupts must respect CPU masking

## Observed defect

Run `20261007T111505Z-34b45563` recorded the first 128 SPU DMA interrupt dispatches. **126 executed while IOP interrupt control was zero**; all 128 reported completion. Handler 0x29EEC was registered and enabled for IRQ 0x24, with argument 0x2CB58. This shows real original LIBSD code executing inside interrupt-disabled regions. It does not prove this is the only cause of the black screen.

The local emulator's `servicePendingDmaInterrupts` removed due completions and called intrman without checking CPU interrupt control. `dispatchInterrupt` checked the per-line enable and handler, but also omitted the global check. CpuDisableIntr/CpuSuspendIntr already set that control to zero; delivery ignored it.

The [PS2SDK intrman contract](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/intrman/include/intrman.h) explicitly separates global CPU masking from per-cause masks. It also identifies SPU DMA lines 0x24 and 0x28. No PS2SDK implementation code was copied into this repair.

## Repair and meaningful regression

DMA completions now stay in the pending queue while the global CPU interrupt control is zero. Intrman also rejects direct dispatch while globally masked. Existing handler selection and timing remain otherwise unchanged.

The regression executes a synthetic native IOP IRX, not a mirrored helper test. It registers/enables the SPU0 DMA interrupt, disables CPU interrupts, starts a DMA and runs thousands of guest instructions. Guest code records the handler count before re-enabling, then records it again after re-enabling.

* Before repair: the test fails because the handler already ran inside the disabled section.
* After repair: the masked count is zero, the unmasked count is one, and the completion is not lost or duplicated.

Files: `artifacts/verification/iop-irq-mask-before.log`, `artifacts/verification/iop-irq-mask-after.json`. Validation after repair: **462/462 native tests and 86/86 Python tests pass**. Original game files were not edited or bypassed.

## Bounded diagnostic controls

`PS2X_TRACE_IOP_IRQ=1` logs at most 128 interrupt registration/enable imports, 128 dispatch attempts and 128 scheduled SPU DMA completions per process. Successful dispatch logs include actual handler completion status. Counters are separate but shared across runtime instances in the process; do not infer global absence from the capped output.

```powershell
$env:PS2X_TRACE_IOP_IRQ = '1'
$env:PS2X_IOP_RPC_CAPTURE = '0x53544154:2'
python -m ps2l run 'game/Resident Evil 4 (USA)/SLUS_211.34' --timeout 180 --diagnostics --trace-disc
```

Reference observations: `artifacts/research/20261007/iop-irq-before-summary.json`. Before/after IOP memory capture is described in [IOP_RPC_SNAPSHOTS.md](IOP_RPC_SNAPSHOTS.md).

## Actual game verification after repair

Capture `20261007T112124Z-8964d07a` ended at 180.203 s with 85 black frames and no faults matched by the current detector. Runner SHA-256 is `92527a20e9be772348f3da87b2ac0e2cf29d1518f2294864e4646f5a3669283b`. The five captured DMA interrupt dispatches all show control=1 and completed handlers; none show delivery with control=0. This is a narrower sample than the 128-event baseline, because execution changed. Do not equate the counts with equal workloads or claim speed improvement.

No selected STAT function-2 snapshot was produced in this run; it did not reproduce the earlier sampled status-loop stage within the observation window. Early capped IOP thread logs show thread 23 waiting on its mailbox, not its later transfer sleep. These logs cap at 64 samples, so they do **not** establish its final state. Use the last EE state and an uncapped or selectively delayed IOP capture to locate the present wait before assuming the old worker still owns it.

Evidence: `artifacts/research/20261007/iop-irq-after-summary.json`. This fixes an independently proven interrupt defect but does not solve or certify game output. Next audit includes interrupt context reporting (QueryIntrContext currently returns zero) and critical-section ownership across guest scheduling; do not re-enable incorrect masked dispatch merely to restore the previous boot stage.

## Remaining fidelity work

### Follow-up: per-line masked completions

The global-control repair did not retain completions when only the selected
IRQ was disabled. The pending queue removed due events before intrman could
reject delivery, permanently losing the event. A second actual IRX fixture
keeps CPU interrupts enabled, masks SPU0's individual line, starts DMA, then
unmasks that line. Before this repair it failed because the handler never
ran after re-enable: 462/463 tests passed in
`artifacts/verification/iop-line-mask-before.log`.

Queue delivery now checks registration and enable state and retains events
until dispatch accepts them. A handler can change masks, so eligibility is
checked again at dispatch. Retirement checks the captured due cycle to avoid
erasing a new transfer scheduled by the handler on the same line. Mature
masked events do not force idle execution into one-cycle spins. This remains
the existing coalesced per-line event model, not a full DICR implementation.

The local DMA scheduling path currently produces these events for SPU0/SPU1;
CDVD raw transfers use a separate completion path. This defect alone is not
evidence that a particular RE4 disc request lost its interrupt.

After repair, `artifacts/verification/iop-line-rearm.json` records **464/464
native tests and 86/86 Python tests passing**. A third real IRX case starts a
second DMA inside the first handler; both transfers deliver exactly one
interrupt, with no delivery while the line is masked. The original global
mask and context checks continue to pass. Build evidence is in
`build-iop-line-mask-after.log` and `build-iop-line-rearm.log`.

### Runtime capture after per-line retention

Runner build completed in 155.1 seconds (92,745,216 bytes), SHA-256
`e55fd33ca80f699111c4c98b37200e1c2f9b3a8e16cecf0d2e121bd010777d9b`.
Run `20261007T114449Z-77fdd56b` lasted 300.203 seconds: 141 decoded frames,
all black, with no faults matched by the detector. It reached the five
resource-completion entries at 0x1B36F0 and produced all four selected STAT
snapshot pairs. Those entries are not full-payload verification or proof of
complete function returns. Final EE counters were DMA=17,682, GIF=1,770 and
GS privileged writes=26,837; these counters do not prove visible rendering.

Five captured SPU interrupt handlers completed with control=1. In the four
early STAT after-snapshots, core-zero callback remained 0x40830 with argument
0x48254; core-one callback was zero. First queue state was zero, followed by
three occupied states with sender 23. Reply bytes 8..11 were 00/00/00/10
once, then 01/01/00/10. Original CSE completion callback is 0x2DFD4, but
forcing it would bypass the unresolved callback ownership/restore protocol.
Next evidence needed is the actual registration and transfer call sequence.

Evidence: `artifacts/research/20261007/iop-line-mask-summary.json` and
`line-mask-callback-state.json`. These are the first four snapshots, not the
final IOP state. This capture has a longer window and different selected EE
trace targets than the prior 180-second run; it is not a formal performance
comparison. Original ELF SHA-256 is unchanged.

These repairs address global and per-line masking retention. They do not certify complete IOP interrupt behavior: DICR acknowledgment, CP0 exception entry/return, accurate SPU2 transfer latency and actual PCM rendering still require their own tests and implementation. The existing SPU2 memory path remains a compatibility model; DMA completion alone cannot prove sound correctness.

The observed bank-transfer worker also needs the intended completion callback. A prior snapshot had core-zero LIBSD transfer handler pointer 0x40830 (another original module), whereas CSE has its own handler at 0x2DFD4. Their ownership/restore timing is a lead, not proof that the original game's callback is wrong. Do not force a game-specific callback or wake thread 23 artificially.

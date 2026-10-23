# IOP interrupt context — 2026-10-07

`intrman` ordinal 23 (`QueryIntrContext`) previously always returned zero,
including calls made by a guest DMA interrupt handler. The
[PS2SDK contract](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/intrman/include/intrman.h)
requires one in interrupt context and zero outside it. Original sound
libraries can use this distinction when selecting thread or interrupt APIs.

The interrupt dispatcher now maintains a scoped depth while it executes an
enabled guest handler. Nested guest calls share that context; normal return
and exception unwinding restore the previous depth. Reset clears it. Rejected
dispatches do not enter interrupt context. This does not manufacture a sound
completion or wake any game thread.

The existing synthetic IRX regression exercises the real SPU DMA registers,
handler registration, masked pending delivery and imported query function.
Its guest handler records the query result in IOP RAM; module code queries
again after delivery. Expected observations are one inside and zero outside,
with exactly one interrupt after re-enabling. Before the fix the handler
observation failed: 461/462 native tests passed in
`artifacts/verification/iop-context-before.log`.

After correction, `artifacts/verification/iop-context-after.json` records
462/462 native tests and 86/86 Python tests passing, plus the three tooling
self-checks. The interrupt fixture observes one inside the handler, zero
after return, and retains the masked-delivery guarantees.

Runner build succeeded in 155.3 seconds, SHA-256
`b7a1d578dcd3ccf3a6ce434c9034f9d30de01b5eac1b36911a27dc603cab5778`.
Capture `20261007T113401Z-582da3c5` lasted 180.203 seconds and decoded 85
frames, all black; no faults matched the detector. Five captured DMA
handlers completed with interrupts enabled. The selected resource-status
call at 0x16BB78 returned to 0x16BB80 with value 2 in 256 bounded samples.
No selected STAT snapshots were produced during this capture. Final sampled
EE PC was 0x16BB78. This is evidence of the resource-loading stage, not
proof of an infinite wait or that the service cannot be reached later.
`artifacts/research/20261007/iop-context-summary.json` retains the evidence.
The original ELF hash is unchanged.

This fix covers handlers dispatched through `IopIntrman::dispatchInterrupt`.
Timer callbacks invoked directly by `IopTimrman` are not covered. It does not
establish a hardware interrupt stack, full CP0 exception semantics, accurate
interrupt timing, or a complete SPU2 implementation. Gameplay and the black
screen require separate runtime evidence.

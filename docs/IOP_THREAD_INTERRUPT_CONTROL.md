# IOP thread interrupt context — 2026-10-07

## Defect and correction

The local scheduler stored CPU registers per thread but left interrupt
control in one shared hardware field across host execution slices. A
thread blocking with interrupts disabled therefore passed that disabled
state to another ready thread. Conversely, another thread enabling
interrupts destroyed the blocked thread's disabled state when it resumed.

PS2SDK preserves `I_CTRL` in each saved register context. Its thread
initialization and idle context both start with `I_CTRL=1`; its switch
callback returns the selected thread's saved context. See the primary
[thread context implementation](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/threadman/src/thcommon.c)
and [thread operations](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/threadman/src/thbase.c).

`IopThread` now owns a saved control value. Starting a thread initializes
it to enabled. `endTimeslice` saves the outgoing hardware value;
`beginNextReady` restores the selected thread's value. If no user thread
is ready, the implicit idle context enables interrupts so completions can
wake sleeping threads. Resuming a blocked disabled thread restores zero;
there is no unconditional enable of an active guest critical section.

This fixes saved-state isolation. It does not establish that every current
host-slice preemption, timer callback or synthetic guest call follows
hardware interrupt scheduling rules. Those remain separate fidelity gates.

## Verification

A native test uses real kernel thread imports and scheduler operations:
start two differently prioritized threads, disable in the first, put it
to sleep, run the second, wake the first, and switch back. Before the fix,
465/466 tests passed: the new test failed both the second thread's enabled
state and the resumed first thread's disabled state. After correction,
466/466 native and 90/90 Python tests passed, plus three tooling checks.
The case also exercises disabled sleep into idle, interrupt-enabled idle,
and restoration of the disabled state after wakeup.

Evidence: `artifacts/verification/thread-control-before.log`,
`thread-control-after.json`, `build-thread-control-after.log`.

## Optional diagnostics

Set `PS2X_TRACE_IOP_INTERRUPT_OWNER=1` before starting the runner. The
setting is read at emulator reset. Output is bounded independently:

- `[IOP interrupt control]`: first 256 guest instruction boundaries
  changing control, including imports and MMIO writes, with PC, RA,
  cycle, before and after values.
- `[IOP masked slice]`: first 64 thread slice endings with disabled
  control; records thread, state, yield/stop flags, entry/end PCs and
  the last observed guest control-changing boundary.
- `[IOP context control]`: first 64 scheduler restorations changing
  control, including thread zero for idle.

The last-change fields named `owner_*` are diagnostic breadcrumbs, not
proof of a causal owner. Nested calls or a context switch can make the
boundary belong to another thread. Later changes remain tracked for these
fields after the first trace cap, but capped logs cannot certify absence
of later changes. These observations do not modify guest memory or control.

The pre-fix diagnostic runner built in 153.5 seconds. Run
`20261007T123526Z-2cfed24f` lasted 180.219 seconds with 84 decoded black
frames and no detector-matched faults. It reached both the 256-change and
64-slice caps during startup; it therefore does not identify the later
disable owner. Five post-resume samples still have control=0. Independent
scheduler testing and the primary context contract establish the defect;
the capped game trace alone does not.

Evidence: `artifacts/research/20261007/interrupt-owner-baseline.json`.

## Actual game result after correction

The corrected runner built in 152.1 seconds, 92,751,360 bytes, SHA-256
`2a84e549ca0ac4d809d27158a1448973b320b53b17b53e6ae9fffec068dd8d0b`.
Final verification is `artifacts/verification/thread-control-final.json`:
466/466 native and 90/90 Python tests, plus three tooling checks.

Run `20261007T124159Z-53d36430` lasted 180.203 seconds with 78 decoded
frames, all black, no image errors and no detector-matched faults. Original
ELF hash remains unchanged. The five established continuation samples at
PC/RA 0x33D94 now all show control=1, where both preceding runs showed
control=0. Their CpuResumeIntr return values are zero. This is direct guest
evidence that the previously observed persistent disable has been removed.

All four early post-STAT snapshots now show the stream's saved control=1
and status=0. However, three still contain occupied queue state 2, sender
23 and reply bytes 8..11=01/01/00/10; the active core-zero callback remains
0x40830. The sound audit again records two initializations, three
registrations and seven transfer entries without reaching its cap. The
IRQ return trace reaches 128, so it cannot prove delivery of the specific
later accepted voice transfer or absence of subsequent IRQs. Context
restoration reaches its independent 64-log cap as well.

Do not interpret the frame count as a performance benchmark: tracing and
changed guest interrupt activity affect execution. Next establish the
specific accepted transfer's delivery/callback path, and replace the
placeholder SPU2 transfer model with independently validated hardware
behavior. See [SPU2_BACKEND_REVIEW.md](SPU2_BACKEND_REVIEW.md).

Evidence: `artifacts/research/20261007/thread-control-run-summary.json`,
`thread-control-sound-final.json`, `thread-control-snapshot-state.json`.

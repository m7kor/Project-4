# Selected guest calls

## Integer decoder input snapshot

`PS2X_CAPTURE_CALL_TARGET=0x19b1f8`, `PS2X_CAPTURE_CALL_FROM=3200`, and
`PS2X_CAPTURE_CALL_PREFIX=<new absolute path prefix>` capture the first selected
call at or after that EE vsync. The parent directory must exist. Existing
`.json` or `.ram.bin` files are refused. The snapshot contains 32 MiB EE RAM,
all 128-bit GPRs, both scalar HI/LO pairs, PC and SA. It does not contain FPU,
VU, kernel or device state and is not a full save state. With the variables
unset, no snapshot is written.

`python tools/audio/replay_ee_adx.py PREFIX --out NEW_PREFIX` independently
executes the original integer instructions in that RAM snapshot for RE4's
`0x19b1f8` ADX wrapper. It rejects unsupported instructions and memory accesses,
and has an instruction cap. Output WAVs are separate pre-IOP channels at an
assumed 48000 Hz; they do not represent speaker output. Comparison against
the generated function and real captured PCM is still required before
assigning a decoder fault. Focused instruction tests cover delay slots, likely
branches, signed loads/division, R5900 multiply destinations and unaligned
doubleword/quadword copies.

`tools/audio/build_compiled_adx_harness.py` builds an isolated comparison harness
from current generated functions without editing them. It records source hashes
and replaces checkpoints with controlled probes at loops **and call boundaries**.
`tools/audio/compare_ee_adx.py PREFIX --harness EXE --out NEW_REPORT` compares
complete RAM, all GPR halves and HI/LO at periods 0/1/8. Supported entries include
the ADX wrapper/executor, PCM wrap/post-decode, SJ helpers and PCM commit routine.
Synthetic callbacks/fixtures must be identified explicitly; these comparisons
do not validate production scheduling, devices or competing threads.

`tools/diagnostics/ee_file_poll_trace.py LOG --out REPORT.json` preserves
selected call phases, register values and the observed RE4 file headers at
0x1B4618/0x1B3770/0x1B3BE0/0x1B4558. These raw state fields do not certify
read success. A yielded call can resume without another matching leave line.
The shared limit counts entries across **all** selected targets, including
semaphore and background calls. `ee_job_trace.py` now uses that total to
report exhaustion even when fewer than 256 job notifications were observed.

`PS2X_TRACE_CALLS` is a comma-separated list of at most sixteen aligned
32-bit guest addresses. `PS2X_TRACE_CALL_SOURCES` optionally narrows those
targets to at most sixteen caller instruction addresses. An absent or empty
source list preserves the previous target-only behavior. Address parsing
accepts decimal or `0x` hexadecimal values, stopping at the first invalid
token. These are diagnostics only; they do not change guest dispatch.

`PS2X_TRACE_CALL_ARM` optionally lists up to sixteen target addresses using
the same parser. With a nonempty list, selected calls are ignored until a
transfer first reaches one of these targets. That transfer emits a single
`[EE trace:armed]` marker and can itself be captured if selected. Earlier
calls do not consume the 256-call budget. This makes a bounded trace useful
for a late event without guessing its wall-clock or guest-field timing.
An absent/empty list preserves immediate tracing. An invalid first token
parses as an empty list, consistently with the existing address options.

The runtime records enter/leave, source and target PCs, v0 and the original
a0..a3 arguments, plus up to 64 bytes at each valid physical RAM argument.
The global limit remains 256 selected dispatches. A call that yields to the
scheduler can have an enter without a leave in this bounded trace; that is
not proof it hangs. The byte dumps do not normalize virtual aliases or read
MMIO. Values on an enter are not return values.

`PS2X_TRACE_CALL_MEMORY` optionally selects up to sixteen aligned physical
RAM addresses. Each emitted call line adds 64 bytes from each valid address
as `mem_<hex-address>=<hex-bytes>`. Windows outside 0x1000..RAM_SIZE-64
are ignored. These reads happen on the EE thread at the call boundary,
allowing destination bytes to be inspected when a completion callback is
entered, even if that destination is not one of the callback arguments.
With the existing 512-line bound, added memory hex is at most 1 MiB.
This is prefix evidence only, not proof of the rest of an asset.

A memory selector can also be `base:offset`, for example
`0x325308:0x7f40`. This reads a 32-bit pointer at `base`, adds `offset`
with a widened sum, and captures 64 bytes at the resolved physical address.
The pointer location must be aligned and within 0x1000..RAM_SIZE-4;
the final window must be within 0x1000..RAM_SIZE-64. Invalid windows are
ignored; virtual aliases and MMIO are not resolved. The emitted key is
`mem_<base>_at_<offset>_resolved_<address>`. The sixteen-window and
512-line limits are unchanged.

Capture `20261007T052710Z-c9da1df9` verified this against RE4: the pointer
at 0x325308 resolved to 0x425BA0, with the requested windows appearing in
512 selected call lines. Of 256 calls to 0x16F570, 238 leave records reached
the caller continuation 0x227D7C; the other 18 reached continuation PCs
inside the call chain. Do not count every leave record as a completed call.
The root+0x7F50 values were 0 and 0x01000000, neither setting the early-return
mask 0x10000000. Root+0x1C4 was zero. These observations exclude those
particular entry gates in this sample, not other causes of the black screen.
Evidence: `artifacts/tool-audit/20261006/render-state-summary.json`.

Example for the resource-status call observed in RE4:

```powershell
$env:PS2X_TRACE_CALLS='0x17bb40'
$env:PS2X_TRACE_CALL_SOURCES='0x16bb78'
python -m ps2l run 'game/Resident Evil 4 (USA)/SLUS_211.34' --timeout 180 --diagnostics --trace-disc
Remove-Item Env:PS2X_TRACE_CALLS, Env:PS2X_TRACE_CALL_SOURCES
```

The source filter was added after capture `20261006T153046Z-855eede1`
spent its target-only trace budget polling the earlier catalogue request
from 0x16C0F8. Repeating that identical capture cannot identify the later
resource request from 0x16BB78; the source filter addresses this concrete
diagnostic blind spot.

Scheduler entry is not a dispatchGuestBranch call. To observe a thread
entry or resume, select it with PS2X_TRACE_EE_PCS; arm the call trace on
an actual observed branch transfer instead. A branch-only arm at a worker
entry can leave the trace unarmed despite that worker running.

PS2X_TRACE_EE also enables auxiliary ReferThreadStatus output. This output
is now capped at 512 status lines plus a cap notice per process; the status
service continues writing the complete ABI and returning normally. The
525-test run with tracing enabled includes 600 repeated status requests
and verified exactly 512 status records plus the notice. This prevents
unbounded auxiliary output from dominating a late-PC diagnostic capture.

The filtered native capture `20261006T153646Z-a2c52f1e` ran for 180.219
seconds and produced 512 enter/leave lines, all from source 0x16BB78.
The first 256 status calls returned 2 for relative LSN 169232, six sectors.
Adding the archive base 25 maps this to BIO4DAT entry 363. The trace cap
still prevents a conclusion that this request remains pending forever;
creation and completion calls need their own capture. Evidence is in
`artifacts/tool-audit/20261006/resource-source-filter-summary.json`.

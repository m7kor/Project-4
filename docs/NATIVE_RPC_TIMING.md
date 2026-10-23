# Native RPC timing and receive-buffer progress

## Scope

The original IOP service currently executes synchronously inside a native SIF call. `PS2X_SIF_RPC_TIMING=1` is an optional experiment that measures IOP cycles spent handling that call and schedules its response in EE virtual time using the existing 8:1 clock ratio. A SID value, such as `PS2X_SIF_RPC_TIMING=0x80000400`, now isolates that service while other services retain their existing timing. Empty or malformed selections do not enable timing. It is disabled by default. This is not yet a complete asynchronous IOP implementation: accounting for IOP work already executed ahead of EE remains to be validated.

## Two observed failures

1. Run `artifacts/runs/20261008T130030Z-457d3693` produced no captured frames within 211.578 seconds. A delayed response encountered an occupied receive buffer and was lost. The explicit delivery failure is now recognized by the run-report fault detector. Preserved reclassification: `artifacts/research/20261008/pcsx2-memory/rpc-timing-prequeue-review.json`.
2. A FIFO was added to retain responses until the guest consumes the existing packet. Run `artifacts/runs/20261008T131405Z-0c50a9dd` still produced no captured frames within 211.453 seconds. Retrying every 8 virtual cycles coincided with the scheduler's 8-cycle charge before guest dispatch: each attempt became due before the consumer could execute. The final observation reached EE vsync 57 with no GS writes.

## Progress correction

Both initial and subsequent FIFO retries now use the existing 32-cycle generated checkpoint interval. This leaves runnable guest code time to consume its buffer. Packet data is copied, FIFO ordering is retained, invalid receive buffers are rejected before enqueue, and reset invalidates pending work. The retry interval does not change the measured native service completion deadline.

The regression `a busy SIF receive buffer must not starve its runnable guest consumer` leaves an old packet in the buffer, queues a response, and runs a real guest consumer under a bounded virtual-time deadline. Before the correction it failed: the guest never ran and never received the response. After the correction it passes. Verification reports:

- Before: `artifacts/verification/sif-queue-starvation-before.json`, 488/489 C++ tests passed.
- After: `artifacts/verification/sif-queue-starvation-after.json`, 489/489 C++ and 106/106 Python tests passed, plus the three tool checks.

These tests establish scheduler and transport progress, not successful RE4 boot or memory-card formatting. Actual game observations are recorded separately in `CURRENT.md`. Normal `Play.cmd` clears the experimental timing option when packaged.

## Game experiment after the correction

Run `artifacts/runs/20261008T132630Z-291f86fb` ended at the 211.468-second timeout. It produced 38 state samples and 37 captured frames, but every captured frame was black. The final published state was host tick 4440, EE vsync 142, PC `0x187978`, cycle 697972481, and one GS write. It therefore progressed beyond the previous scheduler starvation but did not establish a successful boot. The measured-response timing experiment remains disabled in normal play; no memory-card formatting was proven.

The first attempted normal control (`20261008T133023Z-32fe8c6a`) failed immediately because setting a PowerShell environment value to an empty string left the input-replay option present. This was a test-launch configuration error, not a game boot result. The subsequent control removes the environment entries before launching. The batch launcher uses `set "NAME="`, which removes that entry.

## Normal control with timing disabled

Run `artifacts/runs/20261008T133059Z-4e018f9b` used native SIO2/SPU2 without replay or the experimental timing flag. It reached the system-data creation question with 68 state samples, 67 frames, and EE vsync 948 at the 150.094-second observation deadline. No recognized fault was recorded. The first sampled nonblack image, `frame-4200.png`, was saved approximately 76.549 seconds after the recorded run start; this is a sampled wall-clock estimate, not an exact first-pixel timestamp. The earlier traced baseline had its first sampled nonblack image at approximately 84.253 seconds; different diagnostic settings prevent treating that difference as a controlled speedup. The physical controller was detected as `XInput Gamepad (GLFW)` on PS2 port 0.

The build cache still had `PS2X_GUEST_PC_PROFILE=ON`. The profiling code calls timers and records PC samples inside guest dispatch; its presence is confirmed, but its effect on this boot must be measured rather than assumed.

Run `artifacts/runs/20261008T133908Z-d18c70d0` used a rebuilt runner with profiling compiled out. It produced 67 state samples and 66 frames, reached EE vsync 1056, and ended at the 151.484-second observation deadline without a recognized runtime fault. Its first sampled nonblack image was saved at approximately 79.438 seconds. The final inspected image, `frame-7920.png`, shows the existing memory-card formatting failure; formatting/save completion is still unproven. The raw card remains unchanged at SHA-256 `47ebe237a3987f843fc19b0f801ce1edc1690768ef6b18e4b03a12ca6b298358`.

Both normal runs booted past black output, but removing profiling did not demonstrate a material startup speedup. Test building and verification overlapped the early part of the profile-off observation, so these runs are observations rather than a controlled performance benchmark. All five verification groups passed for the profile-off build (489 C++ and 106 Python tests). The startup comparison and report hashes are preserved in `artifacts/research/20261008/boot-timing-comparison.json`.

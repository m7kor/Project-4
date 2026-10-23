# Native RPC on the original IOP service thread

## Implemented path

`PS2X_SIF_RPC_ASYNC=0x80000400` selects the original card service for experimental queued execution. `1` selects all services; the default remains off. This is separate from the earlier measured-reply timing experiment and does not need `PS2X_SIF_RPC_TIMING`.

SetRpcQueue now records its thread binding and initializes the queue structure. RpcLoop marks that actual thread as waiting for requests. Accepted native requests retain their own payload and RPC_END identity. Only the FIFO head of each queue can start, so later requests cannot overwrite a running handler's server buffer. The callback executes on the registered thread through the existing priority scheduler and EE/IOP 8:1 accounting. There is no synthetic two-million-instruction completion or extra measured-response delay.

The original RpcLoop CPU context and interrupt state are saved while the service function runs below its suspended frame on the same owned thread stack. CPU budget slices retain the live callback context. WaitSema, event, delay, and mailbox imports therefore act on a real current thread; scheduling resumes it only when its actual wait is satisfied. Upon return, its RpcLoop context is restored and output is copied directly to the original EE receive address. The owned END packet is delivered through the existing SIF transport, which retains responses when the EE receive buffer is occupied.

Reset clears queued work. Deleting the service thread produces an explicit incomplete-call fault without publishing output. Module unload cancels its jobs and cannot resurrect dead threads. Callback faults, invalid result ranges, and failed completion delivery are reported rather than fabricated as successful replies. The general runtime still defaults to synchronous RPC unless selected. After the successful original system-data creation/restart/readback observations, the RE4 package now selects queued execution only for card SID `0x80000400`; see [SIO2_ASYMMETRIC_CARD.md](SIO2_ASYMMETRIC_CARD.md).

## Verification

`artifacts/verification/iop-rpc-thread-lifetime-final.json` passes all groups: **492 C++ tests and 106 Python tests**, plus the three tool checks.

The new fixture loads an actual MIPS IRX-style service. It creates a priority-24 thread, binds its queue, registers its callback, and enters RpcLoop. The first request executes 600,000 loop iterations, exceeding two million instructions without early output or completion. A second request, accepted while the first is running, preserves its separate payload and END identity and blocks in WaitSema. A real guest SignalSema wakes the original thread. Both callbacks report the same original thread ID. Additional checks cancel a waiting request on reset, delete its thread, and unload the module without stale result writes or resurrected threads.

This verifies the typed request path, scheduler ownership, waits, FIFO data ownership, and lifecycle behavior in the fixture. Actual RE4 Format/create/save/restart/load remains required. The native runner build completed successfully in 503.5 seconds. The RE4 observation uses separate copied game assets and isolated save storage under `artifacts/research/20261008/native-async-game`. The last normal-play package has not been replaced by this experimental path.

## First actual RE4 observation

Capture `20261008T150716Z-354d0f29` lasted 401.656 seconds, using only the card async option and an isolated blank card. The first nonblack sampled image was `frame-4320.png`, approximately 79.618 seconds after capture-folder creation. This is still a slow boot, without a demonstrated startup improvement.

The original Format handler completed with result zero. The isolated 8,650,752-byte card changed from all-erased to a PS2 format signature, 112 non-erased pages, SHA-256 `08a88b11925a8d51d81314acb0659b595304fd41f90f49bbe641f35d5fde3200`. The geometry/signature inspection does not certify filesystem or ECC integrity. The native game then reported a missing indirect target: its original RPC_END callback at `0x2A9020`, called from `0x29EFCC`. Consequently the UI stayed on formatting, and create/save/restart/load is not verified. A secondary unhandled import is cdvdman:24 (`sceCdReadClock`, per the PS2SDK cdvdman import table).

The traced callback has been added to `recomp/config_re4.toml` as `re4_card_rpc_end@0x2A9020`. Regeneration used the recompiler, copied only its three changed generated files, and entrycheck confirms the actual target is registered. The updated native build succeeded in 166.0 seconds; its observation is described below. The normal package remains unchanged. Evidence: `artifacts/research/20261008/native-rpc-thread-queue-observation.json`, `native-async-card-final.json`, and `native-async-callback-entrycheck.json`.

Reference for the import identity: https://github.com/ps2dev/ps2sdk/blob/master/iop/cdvd/cdvdman/include/cdvdman.h (observed 2026-10-08; architectural reference, not byte-identical to the retail module).

## Callback repair observation

The updated build (86,673,920 bytes) was run as `20261008T151923Z-68b48937` for 300.234 seconds. The isolated first-format card was backed up before resetting only that known test fixture to erased bytes. Original package save storage was not changed.

Format again returned zero. The original EE completion callback now ran without the previous missing-target fault, and the card menu advanced through states 12 -> 20 -> 21 -> 22 -> 23. A captured frame showed “Now Saving system data”. Two native Open calls (function 2) completed with result zero. The following original request, function `0x1B`, remained pending through the bounded observation; its completion was not observed. The last captured frame is RGB-pixel-identical to `frame-10320.png`, the observed system-data saving screen; no subsequent UI progression is established. Four unhandled cdvdman:24 imports remain explicit faults. The isolated card SHA-256 is `39c2acf9b7e2ab06284d0f39f02272d8f6a9b9ca72be9cb0349766dbd0dfc119`, with format signature and 112 non-erased pages. Save/load is not certified. The normal package still has not been promoted.

Next investigation: provide a verified IOP sceCdReadClock implementation; inspect the live original service function `0x1B` and its wait/CPU state; verify final system-file creation and restart/readback before enabling queued card execution in Play.cmd. Startup needs native host-time profiling separate from those card-correctness checks. The first observation had 154 guest VSync ticks (about 2.57 guest seconds at 60 Hz) when its first nonblack sample appeared after about 79.62 host seconds; this demonstrates slow guest boot progression without identifying the dominant host-time subsystem.

Evidence: `artifacts/research/20261008/native-async-callback-observation.json`, `native-async-callback-state-final.json`, `native-async-callback-card-final.json`, and `artifacts/verification/native-async-callback-runner-build.log`.

## Later verified package state

The SIO2 response-length correction subsequently completed original system-data creation and a neutral-input restart reading all 60 bytes, with the card unchanged. The tested executable is now packaged and Play.cmd selects only the card service. Full gameplay progress save/load, rendering beyond the card stage, performance and PS2 intro remain incomplete. Current evidence and limits are in [SIO2_ASYMMETRIC_CARD.md](SIO2_ASYMMETRIC_CARD.md). Earlier observations above describe the package state at those earlier captures.

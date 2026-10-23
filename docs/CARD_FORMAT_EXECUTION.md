# RE4 original card-format execution

## Observed change

The earlier synchronous native-RPC path completed GetInfo inside the first preflight call. The original RE4 menu changed state 10 directly to 20, then failed the formatted-card guard in state 21 without sending Format.

With `PS2X_SIF_RPC_TIMING=0x80000400`, only the card service receives measured virtual-time completion; other services keep their existing timing. Run `artifacts/runs/20261008T135103Z-8f4c01f3` booted and followed the original states 10 → 11 → 12. The trace records `0x123174 → 0x124C50` and `0x124D28 → 0x2A97A0`, then a native RPC request to SID `0x80000400`, function **0x10 (decimal 16)**. This is stronger evidence for the early-completion problem than the earlier all-service experiment, which failed before the card menu.

The operation did not complete: native RPC entry `0x7C224` exhausted the 2,000,000-instruction call budget at PC `0x514C0` with `yielded=0`. The run report correctly contains both `[IOP call incomplete]` and `[SIF RPC unsupported]`; the latter reflects rejected completion, not proof that the original RPC function is absent. The run lasted 211.531 seconds and reached EE vsync 1488. Card bytes did not change. The selected EE changes are preserved in `artifacts/research/20261008/card-only-timing-observation.json`.

## Repeated original-IOP observation

Run `artifacts/runs/20261008T135633Z-711e31d5` captured IOP RAM immediately before and after the actual Format request using `PS2X_IOP_RPC_CAPTURE=0x80000400:0x10`. It repeated the incomplete call at `0x514C0`; the report ended after 210.125 seconds at EE vsync 1517 with the same two fault types. The snapshots each contain 2 MiB, and only 287 bytes differ. The request buffer at `0x7F290` retained its contents. The raw card remains entirely erased at SHA-256 `47ebe237a3987f843fc19b0f801ce1edc1690768ef6b18e4b03a12ca6b298358`.

The first experiment accidentally selected decimal 10 for the snapshot option, while the observed RPC function is hexadecimal 0x10. No snapshot from that first selection establishes anything about Format. The repeated experiment corrected the selector and captured both phases.

Static disassembly from the current after-snapshot shows `0x514A4..0x514CC` XORing a byte range in a count-controlled loop. PC `0x514C0` is the loop branch. This is not a semaphore wait. It does not establish whether the total format work legitimately exceeds the call budget, or whether a range/count is invalid. Disassembly: `artifacts/research/20261008/format-budget-stop-current.json`.

## Next diagnostic and remaining implementation

Incomplete-call diagnostics now include RA, SP, A0, A1, V1, executed instruction count, and configured budget. The source change passed all five verification groups in `artifacts/verification/iop-call-context.json` (489 C++ and 106 Python tests).

Run `artifacts/runs/20261008T140755Z-05e6e1b6` then captured RA `0x54394`, SP `0x1FFDB0`, A0 `0x665B1`, V1 `0x2A`, and exactly 2,000,000 executed instructions. Static disassembly identifies the caller at `0x5438C`, whose delay slot sets the checksum length to 128 bytes. V1 is still 42 in that bounded range; A1 has deliberately been set to -1 by the checksum function as its loop sentinel. It is not evidence of a negative input length. The four observed receive-data chunks at `0x6625C`, `0x6635C`, `0x6645C`, and `0x6655C` each contain 128 bytes and have an XOR matching their stored checksum (zero). This rules out an oversized checksum argument at this observation, but does not prove how many outer iterations are required or whether another retry condition is wrong. Evidence: `artifacts/research/20261008/format-call-context-observation.json` and `format-checksum-caller.json`.

No instruction budget was increased and no successful result was fabricated. The original RPC must return, its completion must reach the original EE client, and actual card format/create/save/restart/load must all be verified before this experiment is promoted. Time spent executing IOP ahead of EE still needs correct accounting; measured reply deferral alone is not a complete asynchronous service implementation. Normal packaged play continues to clear the timing experiment.

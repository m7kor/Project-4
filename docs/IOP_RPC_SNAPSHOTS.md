# Original IOP RPC state capture

The RE4 worker's busy response requires inspecting the original service's code and data. EE traces alone cannot show which IOP callback or state produces those bytes.

`PS2X_IOP_RPC_CAPTURE` selects exactly one SID and RPC function, using `SID:function` with integer syntax. `PS2X_CAPTURE_DIR` must name an existing output directory; `ps2l run --diagnostics` sets it automatically. For the current STAT investigation:

```powershell
$env:PS2X_IOP_RPC_CAPTURE = '0x53544154:2'
python -m ps2l run 'game/Resident Evil 4 (USA)/SLUS_211.34' --timeout 180 --diagnostics --trace-disc
```

The original emulated RPC bridge writes **at most four before/after pairs per IOP reset**, each exactly 2 MiB. Before snapshots occur after request data is copied to the server's buffer. After snapshots occur after guest execution, including incomplete executions. Logs provide SID, RPC number, entry, GP, input buffer, original server descriptor, returned pointer and actual completion flag. They do not fabricate completion or change guest RAM. Filesystem errors produce warnings, not guest failures. Capturing adds host I/O overhead; do not use these runs to measure performance.

File names use `iop-rpc-<sid>-<function>-<index>-before.bin` and `-after.bin`. Counter reset can overwrite previous files if the same capture directory is reused across IOP resets; each `ps2l run` uses a fresh directory. No snapshot means no matching original server invocation was captured, or a logged write failure; it is not proof that no RPC exists elsewhere in the transport.

Inspect the entry from the matching log, not a guessed module address:

```powershell
python tools/diagnostics/iop_snapshot_inspect.py PATH_TO_SNAPSHOT --start ENTRY_FROM_LOG --words 64 --out artifacts/research/stat-entry.json
```

The inspection tool accepts exactly 2 MiB, validates aligned physical/aliased windows and limits output to 512 words. It reuses the locally tested scalar MIPS decoder, records source SHA-256 and retains raw words. Static decoding does not prove executable ownership, function boundaries or correctness for unsupported instructions.

## RE4 static evidence

The ELF at byte offset **0x13D54** in `modules.dat` extends to the next ELF at 0x1F09C. Its IOP module metadata names it **Capcom Sound Engine**; strings identify `SifRpcCommThread`, `SifRpcStatThread`, `SndDrvThread` and separate COMM/STAT errors. A derived copy is `artifacts/research/20261007/thmsgbx.irx`; original game files are unchanged.

In that original ELF, relative code address 0x618C registers the STAT handler at **0x629C**, with buffer at relative **0xD4D0**. Handler 0x629C accepts function 2, calls through the pointer at relative **0xD44C** when present, supplies output address **0xD4F0**, and returns that output buffer. The callback pointer and relocated load base must be obtained from live IOP RAM before interpreting its busy state. EE bind address 0x159A00 is a transport allocation, not sufficient evidence of the original module base.

The initial 90-second run `20261007T105955Z-e7f57780` reached the STAT bind but captured no matching invocation. The process ended at its explicit timeout; a separate 180-second experiment was then started to match the prior runs' observation window. Do not mistake the shorter run's missing snapshots for a broken capture hook.

## Captured original handler and busy-bit provenance

Run `20261007T110310Z-29fc0074` completed at 180.093 s with 85 black frames and no detector-matched faults. Four complete snapshot pairs were written, each file exactly 2 MiB. All four original handler calls completed. Original module load base is **0x2D200**, handler **0x3349C**, callback pointer at **0x3A64C** contains **0x2FB78**, and returned reply buffer is **0x3A6F0**. These are observed addresses for this run, not portable game configuration.

The original callback's command 0x20000000 path calls **0x2DB84** twice. It extracts bit 5 into reply byte 8, and bit 4 into reply byte 9. That getter invokes `ReferEventFlagStatus`/`iReferEventFlagStatus` on **event ID 5**, read from 0x36D44, and returns the `currBits` field at status offset 12. PS2SDK's [event status layout](https://ps2dev.github.io/ps2sdk/thevent_8h.html) confirms the field and import ordinals. Reply bytes are 00/00/00 once and 01/01/00 afterward in the captured pairs.

The original transfer worker, entry **0x32DDC**, sets bits 0x20 and 0x10 at 0x32E1C/0x32E24. It pulls up to 1024 bytes from EE using `sceSifGetOtherData` at 0x32F0C, then queues a transfer through **0x33E74** and sleeps at 0x32F5C. Successful continuation clears bit 0x10 after the final chunk and bit 0x20 after finishing the request.

The observed worker is **IOP thread 23**. In the diagnostic thread samples it initially waits on mailbox 4 at PC 0x32FA8, then remains asleep at **PC 0x32F64** in 58 samples. Its transfer slot at 0x3AD40 is occupied (state 2), sender thread ID 23, source 0x3A238, destination 0x5020, size 1024. Destination transfer mailbox ID is 3. Consumer thread 22 waits on mailbox 3 at PC 0x33E3C. Waiting there can mean it already consumed the message; these samples alone do not prove mailbox delivery failed.

This narrows the next investigation to the queued transfer's actual completion and wakeup of thread 23. Do not clear event bits manually, wake the thread artificially or declare audio DMA correct from the consumer's wait alone. Inspect the original consumer's libsd transfer and completion interrupt/callback route.

Evidence: `artifacts/research/20261007/stat-original-service-report.json`, `stat-callback.json`, `stat-busy-getter.json`, `stat-busy-worker.json`, `stat-dma-enqueue.json`, `stat-dma-consumer.json`. Native/Python validation: `artifacts/verification/iop-rpc-snapshot-final.json` (461 C++ and 86 Python tests passed).

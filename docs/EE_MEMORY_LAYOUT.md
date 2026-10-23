# EE memory layout in the current HLE runtime

The runtime reserves physical EE RAM `0x00080000–0x00100000` for callback stacks, copied SIF command payloads and the native RPC workspace (32 KiB). These are runtime implementation allocations, not game allocations.

`SetupThread(stack = -1, size)` returns the top of RAM, `0x02000000`, aligned to 16 bytes. Thread metadata records the stack base as `0x02000000 - size`; a downward-growing stack begins at its top. Explicit stack addresses still return `stack + size`.

RE4 clears its native heap from `0x00F98800` through `0x01FB0000` (exclusive). Returning the automatic stack base as SP previously placed saved return addresses inside that range. The corrected SP keeps the game's live frames above it.

Host-managed guest heap blocks skip the reserved runtime window. Callback stacks and RPC storage share the reserved arena allocator, so neither consumes the game's heap. ELF load segments overlapping that window are rejected before the segment is copied. A game using that physical range needs a different memory arrangement; this reservation is a current HLE limitation, not a universal PS2 memory map.

## Evidence

- Native regression: automatic stack survives the RE4-sized heap clear; callback and RPC addresses stay in the arena; guest heap allocation skips it.
- RE4 run `20261006T043604Z-9479444f`: main EE thread remains active and reaches CDVD layer search, whereas the earlier run ended with both threads dormant.
- Synthetic ELF collision run `artifacts/arena-validation/20261006T043651Z-31133c8b`: load fails explicitly with `ELF segment overlaps the HLE-private runtime arena.`

Set `PS2X_TRACE_EE=1` to record the first 8192 scheduler dispatches with PC, RA, SP and selected registers. This optional trace records scheduler resumes, not every nested translated call.

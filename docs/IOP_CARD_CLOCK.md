# IOP card clock and extended service-thread observation

## Implemented

The retail MCMAN path previously called unhandled `cdvdman:24` during card operations. `IopCdvd::dispatchImport` now implements `sceCdReadClock` (24) and `sceCdRC` (51). It validates the complete eight-byte IOP RAM destination before any write, rejects null/hardware/out-of-range pointers, reads the host clock, fills status/reserved bytes, writes BCD seconds/minutes/hours/day/month/two-digit year, and returns one only after a successful write. Host time conversion failure returns zero without partial output. The current time policy is host-local, matching the existing EE native clock implementation; it is not a certification of physical PS2 RTC/Japan-time and OSD timezone behavior.

`PS2X_TRACE_IOP_THREADS=1` extends capture-only thread snapshots to 512 observations at one IOP-clock-second intervals. The default capture retains its original 64 observations at one-fifth-second intervals. The flag is cached on IOP reset, so it adds no repeated environment lookup to the normal scheduler. Reset also resets the observation counter and next sampling cycle. Thread descriptions now include RA/SP/A0/A1/V0/V1 alongside PC/state/priority/wait. `tools/diagnostics/iop_thread_trace.py` produces a read-only timeline of observed changes for one thread. It explicitly does not treat repeated sampled PCs as proof of a loop or deadlock.

## Verification

`artifacts/verification/iop-card-clock-final.json` passed all groups: **493 C++ and 106 Python tests**, plus the three tool checks. The added clock fixture checks BCD field ranges, initialized status/reserved bytes, unaligned KSEG RAM addressing, adjacent guards, invalid-range failure without partial writes, the raw clock alias, and no EE-memory writes. The native runner build succeeded in **169.4 seconds** (86,674,432 bytes). `git -C core diff --check` passed for the touched C++ sources.

Restart observation `20261008T153600Z-a5a03815` ran 400.219 seconds on the retained partial test card. Original GetInfo reported formatted=1 and free clusters `0x1F3C`; the UI reported “Failed to load system data”, consistent with incomplete prior creation. No runtime fault pattern was reported, but this observation did not request function `0x1B` or exercise the new clock import, and it is not a save/load pass. The test card remained SHA-256 `39c2acf9b7e2ab06284d0f39f02272d8f6a9b9ca72be9cb0349766dbd0dfc119`. It was copied to `artifacts/research/20261008/native-async-clock-restart-card.ps2` before resetting only the isolated fixture to erased bytes for a fresh creation observation.

Fresh-card capture `20261008T154319Z-a0cf82b9` ran 400.11 seconds without a recorded runtime fault pattern, again completed Format and two Open calls, then waited in request `0x1B`. Extended observations show original thread 15 delaying at PC/RA `0x56B80` with argument 500. Static retail disassembly reveals a back-branch waiting for the write-finish marker `0x55`. The asymmetric SIO2 input/reply defect is described in [SIO2_ASYMMETRIC_CARD.md](SIO2_ASYMMETRIC_CARD.md); clock correction alone did not complete saving. The normal package and original user save storage have not been promoted or overwritten. System-file creation/restart/readback, full gameplay, performance, and PS2 intro remain incomplete.

## Primary references

- PS2SDK clock layout/BCD and success contract: https://github.com/ps2dev/ps2sdk/blob/master/common/include/libcdvd-common.h
- Import ordinals: https://github.com/ps2dev/ps2sdk/blob/master/iop/cdvd/cdvdman/include/cdvdman.h

Observed 2026-10-08. These are architectural interfaces; the retail MCMAN extra import 68 used by RPC function `0x1B` is not named by the current public mcman header. Static disassembly of the actual captured retail code links `0x7C554` -> `0x7CF28` -> `0x7D20C` (import 68). A name or completion behavior must not be inferred solely from the modern SDK.

## Later verified state

The subsequent SIO2 fix completed original system-data creation and restart/readback of all 60 bytes. The combined tested runner has been packaged with queued card execution selected in Play.cmd. See [SIO2_ASYMMETRIC_CARD.md](SIO2_ASYMMETRIC_CARD.md) for current evidence. The earlier failed/partial observations above do not describe the final package state. Gameplay progress save/load and the remaining whole-game requirements are still incomplete.

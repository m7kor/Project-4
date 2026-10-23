# Native SPU2 integration — 2026-10-07

The runtime now has an optional real SPU2 backend, adapted from KillzoneRecomp's
standalone PCSX2 sound library. It builds with clang-cl and passes standalone
audio tests and actual IOP memory/guest-interrupt tests. RE4 still produces
black frames. This is verified sound infrastructure, not proof of playable
RE4, complete sound output, or compatibility with every PS2 game.

## Sources and reproducibility

The adapter is preserved unchanged under `integrations/kzspu2`, from
[KillzoneRecomp commit 5f0700079f9ac4e14799d66d01747dbcdcec55f6](https://github.com/drakolordx7/KillzoneRecomp/tree/5f0700079f9ac4e14799d66d01747dbcdcec55f6/ext/kzspu2).
Its unmodified sound dependency is pinned to
[PCSX2 commit 646df006a4688063e56c0826e7ea4b8bb0c112c4](https://github.com/PCSX2/pcsx2/tree/646df006a4688063e56c0826e7ea4b8bb0c112c4/pcsx2/SPU2),
under `dependencies/pcsx2-spu2/646df006a4688063e56c0826e7ea4b8bb0c112c4`.

`tools/research/prepare_spu2_sources.py` prepares the required source closure,
rejects unsafe archive paths, caps sizes, verifies pinned identities, and
refuses to overwrite locally modified source. The source manifest records
230 dependency files and 17 adapter files, each with its SHA-256. The archive
SHA-256 is `9cafebd6e706d53402cd5405300f93dfc42f9d00921ca7cc89f3e3113276f366`.
The independent audit is
`artifacts/research/20261007/spu2-prepared-source-audit.json`.

The preserved adapter and sound engine are GPL-3.0-or-later. Their notices,
dependency licenses, and `integrations/kzspu2/COPYING.GPLv3` are included.
Distributing a runner linked to this backend requires complying with that
license, including corresponding-source obligations.

Build and activation from the repository root:

```powershell
python tools/research/prepare_spu2_sources.py
python -m ps2l build --configure-flag PS2X_NATIVE_SPU2=ON --target ps2x_tests --target ps2EntryRunner
python -m ps2l build --target ps2_iop_spu2_bridge_tests
$env:PS2X_IOP_SPU2_NATIVE='1'
```

The CMake option defaults to OFF. A build with it ON still uses the existing
fallback unless the runtime environment variable is present. Requesting the
backend in a build without it reports an explicit initialization failure.
The current local build cache has the option ON.

## Implemented behavior

`core/ps2xIOP/src/emulator/core/iop_spu2.cpp` owns the adapter and queues its
callbacks. Guest handlers are dispatched through the existing interrupt
controller, rather than being called directly from sound engine callbacks.

IOP memory routes physical SPU2 register accesses and their masked aliases,
including byte lanes and split 32-bit accesses. Both cores support DMA in
both directions with bounds checks and stable IOP RAM storage. CHCR remains
busy until the backend completes the transfer; MADR reflects progress. The
native path bypasses the old placeholder completion schedule. Read transfers
mark the destination range as owned after completion.

The backend advances on the IOP cycle clock during guest execution and idle
periods. Events feed the existing SPU and DMA interrupt paths, respecting
global and per-line masks. Reset clears sound state, queued events, and PCM.
The subsystem exposes a drain API for 48 kHz stereo PCM. Host speaker output
is not wired to that API yet.

Previously swallowed IOP scheduler exceptions now emit
`[IOP runtime exception]`, stop further IOP execution, and are classified as
faults by the run wrapper even if the process exits successfully.

## Verification and limits

The final broad verification passed **466/466 C++ tests, 93/93 Python tests,
and three tooling self-checks**. Evidence:
`artifacts/verification/native-spu2-final.json`.

The adapter's independent fixture passed with zero failures. It verified
non-silent ADPCM tones on both cores, DMA payload round-trips, IRQ address
behavior, key-off, and auto-DMA PCM consumption. Its measured auto-DMA
completion was 161.7 ms for 170.7 ms of fixture PCM. Evidence:
`artifacts/verification/spu2-standalone-test.log`. These are synthetic sound
tests, not evidence of RE4 audio.

Our bridge fixture also passed with zero failures. It checks register byte
lanes, both DMA directions on both cores, exact payloads and guards,
CHCR/MADR transitions, destination ownership, PCM draining, reset, and
out-of-RAM rejection. A synthetic IRX executes real IOP instructions and
shows zero handler calls while globally masked and exactly one after
reenabling interrupts. Evidence:
`artifacts/verification/spu2-bridge-test.log`.

DMA cancellation/CHCR abort, duplicate active starts, zero-BCR encoding,
complete bus timing, and comprehensive interrupt fidelity remain open.
The adapter has process-global sound state, so the wrapper permits one
native instance at a time. The PCM API has one consumer and no current
host-device integration. Movies, banks, effects, sustained gameplay, and
hardware-reference comparisons still need validation.

## Actual RE4 result and next investigation

Run `20261007T154827Z-765774f5` used the native backend for 181.609 seconds
and ended at the configured timeout. All 84 decoded frames were black;
there were no image decoding errors or faults matched by the detector.
The runner SHA-256 was
`f91a4987ec13400c96ef1faffbcd9a83381d6dbd48d87ccdf4a7c56c8d139519`.
The original ELF retained SHA-256
`465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad`.

There were 79 recorded IRQ returns, without reaching the trace cap, and
zero placeholder DMA completion schedules. A DMA IRQ return appears after
the last selected worker sample. All five samples at `0x33D94` show I_CTRL
enabled. This establishes later delivery; it does not pair the exact
accepted VoiceTrans request with its intended completion handler. V0 at
that sample is CpuResumeIntr's return, not VoiceTrans's return.

Four early RPC snapshots still show the later busy state and the stream
handler `0x40830`. The stream's saved prior handler at `0x48618` is zero.
Trace records show CSE registering its callbacks, then a second SdInit,
then stream registration. The original initialization routine clears the
callback slots. The next task is to determine why that reinitialization
occurs and whether module entry arguments, startup ordering, or ownership
are wrong. It is not justified to force a callback or manually wake the
worker.

Evidence and parsed line references are in
`artifacts/research/20261007/native-spu2-run-summary.json` and
`artifacts/research/20261007/native-spu2-sound-audit.json`.

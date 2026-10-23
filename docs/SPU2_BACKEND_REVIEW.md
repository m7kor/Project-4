# SPU2 backend follow-up — 2026-10-07

**Later verified implementation:** the candidate below has now been pinned,
built, and integrated behind optional native-SPU2 activation. Both standalone
audio and IOP bridge/IRX tests pass. RE4 still renders black frames. See
[NATIVE_SPU2_INTEGRATION.md](NATIVE_SPU2_INTEGRATION.md) for current evidence,
source provenance, activation instructions, and remaining limitations.
The remainder of this document records the earlier review before integration.

After restoring I_CTRL per IOP thread, DMA IRQ returns reach the diagnostic
cap of 128 instead of stopping at five. That establishes increased observed
delivery, not a measured interrupt rate or complete sound playback.

The current `IopMemory::maybeCompleteDma` is a placeholder: it clears CHCR
start immediately, sets a completion status bit, and schedules a callback
after `max(BCR words * 2, 64)` cycles. This path does not transfer the sound
payload into a modeled SPU2 RAM or implement auto-DMA consumption. Merely
slowing the callback or forcing the CSE handler would not implement the
requested full game with accurate audio.

The primary [PCSX2 SPU2 DMA implementation](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/SPU2/Dma.cpp)
distinguishes plain transfer progress from auto-DMA input consumption.
Its DMA code uses 24 cycles per halfword; auto-DMA retains input and refills
internal buffers over audio progression. This is a concrete hardware-model
gap to address, not a license to replace our delay with one scalar constant.

## Reviewed adapter candidate

The earlier nine-project survey excluded dependency subtrees. A targeted
follow-up has now captured all 17 text files in Killzone's `ext/kzspu2`
at pinned commit `5f0700079f9ac4e14799d66d01747dbcdcec55f6`.
Every file matches both its recorded SHA-256 and the Git blob identity in
the previously saved immutable tree. Nothing downloaded was built or run.

Sources: `research/spu2-review/20261007/killzone/sources/ext/kzspu2`;
manifest alongside it; identity audit
`artifacts/research/20261007/spu2-adapter-source-audit.json`.

Reviewed API/build documentation describes an isolated PCSX2 SPU2 static
library with register access, both DMA directions, progress/MADR, event
deadlines, reset, queued interrupt callbacks and a 48 kHz stereo ring.
The CMake target uses unmodified PCSX2 sources and symbol-renaming shims.
The README points to PCSX2 revision `646df006a4` through its parent
project; a full immutable dependency pin must be resolved before a build.
The adapter declares GPL-3.0+ and must retain its source/license notices
when integrated. Its tested toolchain is MSVC x64; our clang-cl build
compatibility is unverified. No backend is installed in our runtime yet.

## Required integration and evidence

1. Pin the complete compatible PCSX2 dependency and preserve provenance;
   build the adapter's existing register/DMA/audio tests without game code.
2. Route IOP SPU2 reads/writes with correct byte lanes and physical aliases,
   both DMA directions, bounds and RAM lifetime. CHCR/MADR must reflect
   progress until genuine completion; no duplicate placeholder completion.
3. Advance the backend on one monotonic IOP clock, including idle deadlines.
   Queue callbacks before guest dispatch, honor masks, and reset pending
   events and audio state together with the IOP.
4. Verify plain DMA payloads and guards, auto-DMA timing, IRQ address
   behavior, both cores and reset using independent fixtures. Drain actual
   stereo PCM through the existing host output with bounded latency.
5. Replay RE4's real sound transfers and specific completion callback;
   verify movies, banks, effects and sustained sound alongside gameplay.

These are implementation gates still open. The saved-context correction
is proven independently and in the game; a full SPU2 implementation and
the black-screen resolution are not proven by it.

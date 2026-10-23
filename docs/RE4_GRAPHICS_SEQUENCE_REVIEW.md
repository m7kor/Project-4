# RE4 graphics sequence review — 2026-10-10

The user reports vertical text/image shake and intermittent black output.
Reviewing only every 120th host presentation cannot exclude either symptom.

## Existing evidence

All 135 saved PNGs in `20261009T215615Z-6e2ca421` were decoded and inspected
in numerical order. There are 67 distinct images. Nine are entirely black:
120, 6240, 8880, 9000, 9120, 9240, 9360, 9480 and 9600. Several are during
scene transitions; black pixels alone do not identify a rendering defect.
Sofdec-logo samples 2160/2280/2400 change mean RGB intensity from
224.324/112.126/224.324, despite zero estimated vertical alignment offset.
This is an observed brightness change, not proof of its cause.

The latest numerical image is 16200, not 9960. Capture sorting was fixed in
both frame audit and run summary; 146 Python tests passed including this
decimal-boundary regression. The game is still at Loading. Its event reader
entered `event/evd/r120s99.evd` and yielded; completion is unverified.

## Dense capture

`PS2X_CAPTURE_EVERY` chooses a positive host-presentation interval (default
120). `PS2X_CAPTURE_FIRST` and `PS2X_CAPTURE_LAST` bound the captured ticks.
The default remains first tick plus multiples of 120. These settings only
apply when capture is enabled. PNG export adds overhead; host tick counts
must not be reported as game FPS.

Each state record now includes the presentation request that produced the
latched image: GS field tick, PMODE, SMODE2, both DISPFB/DISPLAY pairs, actual
display/source framebuffer and preferred-source flag. These values are
retained under the image's presentation mutex. They are not freshly read
from the live guest at export time. EE state remains a published scheduler
snapshot and can legitimately be newer than the captured image.

`artifacts/research/20261009/review-frame-sequence.py` decodes every saved
image, measures intensity/change/vertical alignment, joins presentation
metadata and writes contact sheets in bounded 80-image pages.

## Suspected synchronization defect

`UploadFrame` currently latches from the host presentation thread whenever
the published EE field changes. `PS2Memory` writes privileged display
registers directly on the guest thread, without the frontend state mutex.
Thus host-side latching can read settings during buffer switching and can
copy VRAM during a sequence of draw calls. Backend locking prevents corrupt
memory access inside a primitive, but does not define a completed guest
frame. Dense before/after evidence is required before attributing the
observed brightness changes to this timing.

## Applied field-boundary fix and measured result

Presentation now runs on the EE executor at each VBlank before guest waiters
resume or the buffer-switch callback is queued. The host only uploads the
published image. This processes consecutive fields even when host drawing
or PNG export skips guest fields and avoids sampling privileged registers
while the guest writes them. Reset clears presentation metadata as well.

The same 90-second dense-capture setup was run before and after. The static
memory prompt selection yielded 30 before samples with bottom rows 291/293
and two distinct RGB hashes. Afterward 46 samples spanning both field
parities have bottom row 293 and exactly one RGB hash. This directly
verifies stability for that prompt. The startup logos now remain visible
between fades in the after contact sheets.

Before: 510 images, 445 black. After: 715 images, 74 black, confined to two
startup ranges (120–178 and 252–266). These raw counts are not a compatibility
percentage: PNG overhead changes host cadence and guest progress. Both
observations ended at their timeouts, without gameplay certification.

524 C++ tests pass from the required `core` working directory; 146 Python
tests pass. A new regression verifies that presentation diagnostics retain
the latched image's registers after live registers change. The scheduler
regression checks that VBlank publishes an image before the guest waiter
resumes. Full evidence is `re4-field-boundary-observation.json`.

## Exact-input conversion cache and final packaged build

The CPU backend reuses raw per-parity conversion results only when all VRAM
bytes and all presentation inputs match. It continues temporal blending
each field and never caches that blended result. Direct mapped writes and
true black frames invalidate old output in the regression test. All 525 C++
and 146 Python tests pass. A 200-operation microbenchmark measures 226.386ms
for repeated static input and 594.064ms for changing input; this does not
measure game FPS or compare two identical gameplay scenes.

Final run `20261009T223657Z-f0cf5995` ended at its 361.516-second timeout with
no fault markers, field 8077, and 1866 captured PNGs sampled every four host
presentations. All saved PNGs were decoded and measured. There are 830
distinct images and 83 black images. The 25 selected memory-prompt samples
have one RGB hash and bottom row 293; this sampling catches only odd fields,
so the earlier dense capture remains the direct proof across both parities.

Stage entry remains incomplete: threads 23/31/32 wait on semaphores
153/172/156. The last image (7472) is gray. This is not a gameplay success or
proof that every later scene is free of graphics defects. The next loading
diagnostic must follow the original read request and its completion, rather
than forcing semaphore signals or skipping events.

The local `Resident Evil 4` executable was updated after these checks.
The packaging tool verified all eight original game files and retained
existing destination saves. Executable/manifest/runner hashes match; the
user card retains hash `8207bfeaff91e21998e71df1d3d86375f458e3d04a4669612f2bf89ccaabc448`.
The previous executable, manifest, launcher and README are backed up in
`artifacts/research/20261009/before-graphics-package`. No process remains live.

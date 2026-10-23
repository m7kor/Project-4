# IOP module arguments and numeric option parsing — 2026-10-07

Two runtime defects were found while investigating RE4's duplicate sound
initialization. Neither fix changes the original game files or skips content.

## Direct module entry ABI

Direct file/buffer loading called an IRX entry with packed byte length in a0
and the raw string bytes in a1. Module entry expects argc and an argv pointer
array. StartModule already prepared that array correctly. Both paths now
share the same bounded preparation, include the loader name as argv[0],
terminate the pointer array, and keep storage alive until entry returns.
Missing data with nonzero length and packed arguments over 64 KiB are rejected.

Reference: PS2SDK's
[module start implementation](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/modload/src/modload.c)
and [loadfile argument contract](https://github.com/ps2dev/ps2sdk/blob/master/ee/kernel/include/loadfile.h).
The synthetic IRX test copies entry arguments during execution, through both
host-file and EE-buffer loading, with and without multiple packed strings.
It failed before the correction (466/467 tests passed), and passed afterward
(467/467). Existing StartModule tests still pass.

Run `20261007T160709Z-6cb1fdb9` with this correction alone produced 84 black
frames over 181.593 seconds. Its sound trace still has two initializations,
three registrations and seven transfers. Thus the direct-load correction did
not itself resolve the observed sound ownership problem.

## Original option parsing was rejecting digits

The new diagnostic records the packed argument bytes and argc. The game
passes CRI `thpri=39`, `spucore=1`, and `sdinit=0` through StartModule. These
arguments reached its prepared argv array; that path was already using the
correct entry ABI. The original module sets its sound-init flag to one by
default, then tests the first digit's sysclib ordinal-8 mask for bit 0x04
before calling ordinal 36 (strtol) and updating the flag.

Our ordinal 8 returned zero for every character. It therefore rejected
the digit '0', leaving the default initialization enabled. The same defect
affects numeric thread-priority and sound-core options. Captured memory at
0x485D8 contains one; code at 0x3AE00 checks that flag before SdInit. The
parser's original update lies at 0x3B124. These static windows and the actual
argument trace establish a concrete defect; runtime consequences are checked
separately below.

Ordinal 8 now produces the exact PS2SDK ASCII masks, without using host
locale classifications. Source:
[PS2SDK ctype implementation](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/sysclib/src/nonstd/ctype.c).
Extended bytes are outside the reference's 128-entry table and are not a
verified character-set feature. Ordinal 9's direct table-pointer API remains
unimplemented; this change does not claim complete sysclib compatibility.

An executable IRX tests the digit-mask gate and strtol path for numeric zero;
separate assertions cover representative ASCII mask classes and boundaries.
The prior mask implementation failed those assertions. Final verification
passes **468/468 C++ tests, 93/93 Python tests, and three tooling self-checks**.
The numeric fixture preserves the default one when the digit gate fails,
and writes zero only through the accepted parse path.

Evidence:

- `artifacts/verification/module-argv-before.log`
- `artifacts/verification/module-argv-final.json`
- `artifacts/verification/ctype-before.log`
- `artifacts/verification/ctype-final.json`
- `artifacts/research/20261007/module-argv-sound-audit.json`
- `artifacts/research/20261007/cri-sound-init-disassembly.json`
- `artifacts/research/20261007/cri-entry-argument-disassembly.json`
- `artifacts/research/20261007/cri-parser-imports.json`
- `artifacts/research/20261007/cri-init-flag-store-candidates.json`

The store-candidate report is a bounded static search; it does not prove
every candidate executes or provide complete executable ownership.

## Actual game verification after both corrections

Run `20261007T161552Z-f393668f` lasted 181.594 seconds and ended at timeout.
The original ELF hash is unchanged. Runner SHA-256:
`dba144aab3e6bf643ceb57d18231a5fdce39b03580c58c1686e36099bf5a5fba`.
Three decoded frames are black, with no image errors or detector-matched
faults. This run has fewer sampled frames than the previous run and does
not prove successful rendering or improved overall execution speed.

The game now performs one SdInit rather than two. CRI registers its stream
handler and starts block transfer on core 1, matching `spucore=1`. Thread
priorities 30 and 39 match the supplied options. Four snapshots all show
CRI's initialization flag zero; core-zero handler is CSE's 0x2DFD4 and
core-one handler is streaming's 0x40830. The stream's saved core-one
handler/argument are 0x2DFD4/0x36D58. The indexed storage is established by
original instructions at 0x40950..0x40980; the old core-zero saved slot
is no longer the correct field to inspect for this transfer.

RPC reply bytes 8..11 are 00000010, then 01010010, then 00000010 in each
of the final two snapshots. Queue count is 0, 2, 0, 0 respectively. This
proves the previous busy state clears in the captured observations; it
does not certify every bank, final runtime state, or complete audio.
The sound-transfer trace reaches its 128-entry cap, so no claim of a
complete transfer history is justified.

The final sampled EE PC is 0x2AF590 with RA 0x2AA0EC. Current generated
source identifies that instruction as SQ in a memory-fill loop called
from 0x2AA0E4. It is not an RPC wait instruction. The next
investigation is to capture the caller's destination and byte count,
prove their source and bounds, and determine why execution spends time
in that path. Do not skip the fill or force an artificial image.

Parsed evidence: `artifacts/research/20261007/ctype-run-summary.json`,
`ctype-sound-audit.json`, and `cri-core1-handler-disassembly.json`.

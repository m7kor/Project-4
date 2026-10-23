# Bounded texture and CLUT capture — 2026-10-07

The fragmented RE4 output now has a concrete texture diagnostic. A selected
textured draw can preserve its local memory, loaded palette, decoded atlas,
indices, and draw metadata at the producer's pre-draw boundary. It does not
change game content, replace colors, or certify a correct reference frame.

## Capture and inspection

```powershell
$env:PS2X_IOP_SPU2_NATIVE='1'
$env:PS2X_CAPTURE_TEXTURE_TBP='13472'
python -m ps2l run 'game/Resident Evil 4 (USA)/SLUS_211.34' --timeout 180 --diagnostics --trace-disc
python tools/diagnostics/gs_texture_inspect.py artifacts/runs/<run>/diagnostics/gs-texture-13472 --out artifacts/texture-report.json --preview artifacts/texture-preview
```

The selector is a single block address in 0..16383. The first matching
textured draw captures once per backend reset; an existing capture directory
is preserved and reported as an error. No capture occurs without both the
selector and the run capture directory. Submit holds the backend producer
lock throughout the capture, avoiding live-state reads from the UI thread.

Files:

- `vram.bin`: exactly 4 MiB of pre-draw GS local memory.
- `clut-u16le.bin`: all 512 loaded palette halfwords in explicit little endian.
- `texture-rgba.bin`: point-decoded full atlas, preserving stored PS2 alpha.
- `texture-indices.bin`: original cached indices for indexed formats.
- `draw.json`: dimensions, TEX0 fields, frame, offset, scissor, test, blend,
  clamp, filter, and selected primitive/vertex data. This is a texture
  diagnostic, not a complete draw replay format.

The diagnostic atlas disables draw-specific coordinate wrapping and linear
filtering on a copy of the draw state. The actual draw keeps its original
state. Dimensions are capped at 1024×1024. Binary output is below 9.1 MiB
per capture, plus bounded metadata. Diagnostic failures are explicit and
do not substitute successful game rendering.

The inspector checks exact file lengths, dimensions, four-bit index bounds,
hashes, palette values, and color counts. Optional PNG previews are derived
from the captured bytes. The indices preview maps 0..15 to gray levels
0..255; it is not an original color image. Neither preview is an independent
renderer oracle.

## Verification

**469/469 C++ tests, 96/96 Python tests, and three tool self-checks pass**
in `artifacts/verification/texture-capture-final.json`. The native capture
fixture checks selector behavior, complete local memory, exact atlas size,
stored RGBA/alpha preservation, and first-capture retention. Python checks
reject truncated files, invalid indices, and oversized dimensions.

The PSMT4/PSMT8 block and column tables match all entries of pinned PCSX2
`646df006a4688063e56c0826e7ea4b8bb0c112c4` GSTables.cpp. The reference came
from the previously verified source archive. Evidence:
`artifacts/research/20261007/texture-swizzle-table-audit.json`. This checks
table equality, not every address calculation or hardware behavior.

## Actual RE4 evidence

Run `20261007T163830Z-dbaab711` lasted 181.594 seconds, ending at timeout.
It decoded 81 frames, 33 nonblack, with no decoding errors or faults matched
by the detector. The fragmented image persists. Runner SHA-256:
`b79b182bf3e34511b8d5137caee72ac13f3e87e23842d92a19d02327e8d523ff`.
Original ELF SHA-256 remains
`465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad`.

Capture selected TEX0 TBP 13472, PSMT4, TBW 16, 1024×256, with CLUT CBP
13440, CPSM32, CSM1, CSA zero, CLD 2. The index preview has recognizable,
complete glyph shapes, numbers, accents, and controller symbols. The
palette-decoded preview already exhibits faint colored outlines resembling
the game window. This narrows the problem to palette/data interpretation
before framebuffer presentation, rather than proving an absent font atlas.

Loaded palette values include black with nonzero alpha and colored entries.
Raw local-memory words at CBP include 0x50000040 among them. Matching
subsequences in the original BIO4DAT.AFS identify entry 366 (offset
346685440, size 131808) as a source candidate. The exact file layout,
upload payload, and point where values may differ remain unproven; do not
replace the palette with white or invent a desired image.

The next investigation is to capture the palette transfer's source bytes
and GS destination, compare them with the original asset, and verify CLUT
loading against the hardware layout. It must distinguish upstream data
corruption, transfer decoding, and CLUT address interpretation.

Evidence:

- `artifacts/research/20261007/font-texture-inspection.json`
- `artifacts/research/20261007/font-texture-preview/atlas-indices.png`
- `artifacts/research/20261007/font-texture-preview/atlas-rgba.png`
- `artifacts/research/20261007/palette-source-pattern-search.json`
- `artifacts/research/20261007/font-source-entry366.json`
- Original capture under the run's `diagnostics/gs-texture-13472` directory.

## Palette input trace (2026-10-07)

`PS2X_TRACE_TRANSFER_DBP=13440` selects the destination base pointer.
The CPU backend records at most 32 begin/input events per reset, including
transfer registers, copied pixels, input byte count, and up to 512 input
bytes. `tools/diagnostics/gs_transfer_audit.py` validates the records and
distinguishes a complete captured input from a bounded prefix. Neither
kind proves transfer completion or the source guest address.

Run `20261007T165411Z-4320d01e` supplied a 1024-byte PSMCT32 input to DBP
13440, DBW 1, at (0,0), with dimensions 16 by 16. Its prefix already
contains `0x50000040`; this value is present before local-memory writes
and CLUT lookup. Its first 512 bytes match 510 bytes of BIO4DAT.AFS at
offset 346816600, eight bytes before the candidate palette at 346816608.
Only byte offsets 4 and 7 differ (one four-byte word). This is evidence
for investigating source positioning/packet construction, not proof that
skipping eight bytes is a correct fix. Do not modify original assets or
compensate by injecting a replacement palette.

That run exposed a diagnostic defect: DBW was streamed as an unsigned
character. The raw log is retained, and the parser correctly rejects it;
the comparison is explicitly labeled as a raw-prefix observation. The
trace now casts DBW to an integer. A regression rejects character fields,
invalid register ranges, and negative state. Evidence:
`artifacts/research/20261007/palette-transfer-prefix-comparison.json`.
Next: validate the corrected trace and identify the source guest address
and DMA/GIF packet boundary responsible for the extra eight-byte prefix.

Corrected run `20261007T170158Z-413eb27d` validates 32 records, at the trace
limit. All 16 captured input prefixes have the same differences at offsets
4 and 7 against the candidate source window. Evidence is in
`palette-transfer-numeric-audit.json` and
`palette-transfer-validated-comparison.json` under the research directory.
The independent bounded GIF decode identifies setup packet 124 (96 bytes,
including an IMAGE tag with 64 qwords but no image payload) followed by
packet 125 (1040 bytes, IMAGE tag plus 1024 bytes). The bounded decoder's
short-packet classification does not prove corruption of a hardware stream
across calls. Investigate stream boundaries and source construction before
changing parsing or compensating for the prefix. Full packet metadata:
`artifacts/research/20261007/palette-gif-packets.json`.


## Resolution of the observed palette corruption

Run `20261007T174920Z-68fd2cbe`, after the VIF DIRECT continuation fix,
provides a 512-byte input prefix identical to original BIO4DAT.AFS at
346816608. The loaded font palette now includes white, and visual inspection
of `frame-8400.png` shows readable memory-card warning text matching the
user screenshot. This resolves the specific observed corruption; all
transfers and full gameplay remain unverified. See
[VIF_DIRECT_CONTINUATION_FIX.md](VIF_DIRECT_CONTINUATION_FIX.md) and
`artifacts/research/20261007/vif-direct-game-proof.json`.

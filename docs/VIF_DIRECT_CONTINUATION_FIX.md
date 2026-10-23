# VIF DIRECT payloads and GS IMAGE continuation

The observed RE4 palette prefix contains `0x50000040`, a VIF DIRECT command
with immediate 64. The previous interpreter checked pending GS IMAGE qwords
before decoding any further VIF commands. It therefore treated intervening
NOP/DIRECT words as pixel data, shifting the palette input by eight bytes.
This is distinct from the independently corrected LQ/SQ address alignment.

Two executable runtime regressions fail on the previous implementation:

- A DIRECT payload split after its GIF tag and then delivered one byte at
  a time loses its image data.
- A pending GIF IMAGE continued through a second DIRECT command includes
  intervening NOP/DIRECT words in the uploaded pixels.

Evidence: `artifacts/verification/vif-direct-before.json`, 468 of 470 C++
tests pass; these two fail. The earlier fixtures incorrectly placed raw
image bytes outside their declared DIRECT payload; the fixtures now express
valid VIF framing rather than preserving the incorrect shortcut.

The source fix tracks the declared DIRECT byte count separately from pending
GS IMAGE qwords. It decodes VIF commands between DIRECT payloads, and only
uses bytes enclosed by DIRECT to continue the image. A genuine DIRECT
payload may span calls, including sub-quadword fragments. Each complete
DIRECT payload is buffered, with the protocol maximum of 1 MiB (immediate
zero means 65536 qwords). Reset clears both states and buffered bytes.
This buffering does not establish cycle-accurate delivery or general GIF
stream parsing; the existing IMAGE continuation adapter remains in use.

Primary reference: pinned PCSX2
`646df006a4688063e56c0826e7ea4b8bb0c112c4`, `pcsx2/Vif_Codes.cpp`,
`_vifCode_Direct`, where the VIF immediate defines the command's own payload
length independently of GIF parsing. The local verified archive supplied
the reference; the web fetch was unavailable. Extracted reference SHA256:
`659e95720d49b7f047f499fa31770e522dccb610c2d595647231e1f28748396c`.

The corrected runner and tests built successfully in 586.7 seconds:
`artifacts/verification/build-vif-direct-fix.log`. Both formerly failing
regressions now pass, together with all 470 C++ tests and 101 Python tests,
plus three tool self-checks. Evidence:
`artifacts/verification/vif-direct-final.json`.

Actual RE4 run `20261007T174920Z-68fd2cbe` lasted 181.515 seconds
and ended at the configured timeout (exit 124). It produced 80 decoded
frames with five distinct pixel hashes. Frame `frame-8400.png` was visually
inspected: the memory-card warning is readable, matching the user screenshot.
The first 512 captured palette-input bytes now match the original
BIO4DAT.AFS exactly at offset 346816608. This proves the bounded prefix and
repairs the observed font corruption; it does not establish all transfers,
full game rendering, input, or saving. The game reports no memory card in
slot 1; that next issue needs separate investigation. Evidence:
`artifacts/research/20261007/vif-direct-game-proof.json`,
`palette-transfer-after-vif.json`, and `font-after-vif.json`.
The RPC trace is limited to 128 records, so absence of a later GetInfo
record is not proof that the game never requested it.

The preceding diagnostic run `20261007T172740Z-e79ba78a` generated 278 valid,
uncapped generic GIF DMA source records. Palette packets 124/125 have no
corresponding generic PATH3 source record, narrowing investigation to the
VIF PATH2 forwarding code where the continuation defect is present.
Evidence: `artifacts/research/20261007/gif-dma-source-audit.json`.
Original game files were not changed.

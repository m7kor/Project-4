# Bounded GIF DMA source evidence

`--trace-gif` / `PS2X_TRACE_GIF` now additionally records up to 1024 source
spans before copying data into generic GIF DMA chains or submitting generic
linear GIF DMA transfers. Each record includes source physical address,
RAM/scratchpad selection, span byte count, chain tag address and ID where
available, byte offset within the assembled chain, and up to 64 source bytes.

This complements the existing flattened GIF packet trace. It does not
change addresses or guest bytes. Native fast paths bypass these generic
hooks, so it is not complete coverage of every GIF transfer. The index limit
is per process, with an explicit capped marker. Wrapped source spans are
recorded individually at their actual resolved physical positions.

`python tools/diagnostics/gif_dma_source_audit.py <stderr.txt> --out <report.json>`
validates physical bounds, tag fields, capture lengths, memory selection,
and duplicate record indices. A complete captured source span is different
from a prefix of a larger span. Neither proves DMA completion or that guest
memory remains unchanged after the capture.

The motivating RE4 evidence is the palette input containing an extra
eight-byte prefix and `0x50000040`, unchanged after the independently verified
LQ/SQ alignment fix. The next runtime trace must identify which guest source
span contributes those bytes, then inspect its producer. Original assets
and runtime data must not be patched with an invented palette.

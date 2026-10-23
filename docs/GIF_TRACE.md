# Raw GIF evidence

`python -m ps2l run <ELF> --timeout 120 --diagnostics --trace-gif` records
the first 512 callbacks delivered to the GS frontend. Each callback records
its declared byte size, at most 4,096 bytes as hex, and a sampled EE PC.
That PC is not necessarily the instruction which issued DMA. The cap is
explicit; the trace cannot prove the absence of later texture uploads.
The hex payload budget is 4 MiB, excluding small line metadata.

Decode a completed capture with:

```
python tools/bios_mine/gif_trace.py artifacts/runs/<capture>/stderr.txt --out artifacts/gif-decoded.json
```

The decoder preserves raw values and separates `prefix-truncated` from
`short-packet`. PACKED slots have 16 bytes; REGLIST slots have eight bytes
with padding to a quadword. NREG zero means sixteen for register formats;
IMAGE and IMAGE2 lengths depend only on NLOOP. Multiple tags in one callback
are decoded. Packed RGBA and A+D have distinct layouts. Five tests cover
these boundaries, including the next tag following odd REGLIST padding.
The length rules were checked against the primary implementation in
[PCSX2 Gif_Tag](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/Gif_Unit.h).
This tool does not emulate the GS or certify game compatibility.

The original 128-byte capture `20261006T151301Z-39b392e8` reached its
512-callback cap: 383 complete packets and 129 truncated prefixes. It ran
120.219 seconds without faults matched by the detector. Its prefixes cannot
settle what colors and vertices occur later in the large command packets.

The 4,096-byte build completed in 164.9 seconds. The first subsequent
90.218-second capture `20261006T152139Z-fa1e3444` only reached two setup
packets and timed out, without matched faults. This variation means neither
a wall-time timeout nor the count of startup packets proves rendering
failure at a particular game stage. The longer repeated capture with disc
tracing must be inspected separately.

That repeated capture `20261006T152329Z-52d1daaa` completed after 120.110
seconds: all 512 recorded packets are complete PACKED tags, and all 56
captured frames are black. Its first large packet clears FBP 0 and copies
from TEX0 TBP 3584 (the base of FBP 112). Repeated packets clear FBP 112 in
black with zero XYOFFSET during the clear, restoring the normal offset
afterward. No IMAGE tags or transfer-register writes occur in these first
512 callbacks; the cap prevents any global absence claim. The source trace
digest and raw values are preserved in `gif-expanded-disc-decoded.json`,
with a compact summary in `gif-expanded-summary.json` under the dated
tool-audit directory.

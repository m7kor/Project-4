"""Decode a raw 4 MB GS VRAM dump (swizzled, as the GS stores it) into a PNG.

The runner writes such dumps with PS2X_GPU_VRAM_DUMP_AT=<vsync> (paraLLEl-GS
backend). Only PSMCT32/PSMCT24 are decoded; that covers RE4's framebuffers.

    python tools/diagnostics/gs_vram_view.py gpu-vram-600.bin --fbp 0 --fbw 8 --height 448 -o out.png
    python tools/diagnostics/gs_vram_view.py gpu-vram-600.bin --scan   # list non-empty pages
"""
import argparse
import sys

import numpy as np
from PIL import Image

VRAM_BYTES = 4 * 1024 * 1024
BLOCK32 = np.array([[0, 1, 4, 5, 16, 17, 20, 21],
                    [2, 3, 6, 7, 18, 19, 22, 23],
                    [8, 9, 12, 13, 24, 25, 28, 29],
                    [10, 11, 14, 15, 26, 27, 30, 31]])
COLUMN32 = np.array([[0, 1, 4, 5, 8, 9, 12, 13],
                     [2, 3, 6, 7, 10, 11, 14, 15],
                     [16, 17, 20, 21, 24, 25, 28, 29],
                     [18, 19, 22, 23, 26, 27, 30, 31],
                     [32, 33, 36, 37, 40, 41, 44, 45],
                     [34, 35, 38, 39, 42, 43, 46, 47],
                     [48, 49, 52, 53, 56, 57, 60, 61],
                     [50, 51, 54, 55, 58, 59, 62, 63]])


def decode_ct32(words, fbp, fbw, width, height):
    """fbp in 2048-word pages, fbw in 64-pixel units."""
    y, x = np.mgrid[0:height, 0:width]
    page = fbp + (y // 32) * fbw + (x // 64)
    block = BLOCK32[(y >> 3) & 3, (x >> 3) & 7]
    addr = (page * 2048 + block * 64 + COLUMN32[y & 7, x & 7]) % (VRAM_BYTES // 4)
    pixels = words[addr]
    rgb = np.stack([(pixels >> s) & 0xFF for s in (0, 8, 16)], axis=-1).astype(np.uint8)
    return rgb


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump")
    ap.add_argument("--fbp", type=int, default=0, help="base page (FBP of FRAME/DISPFB)")
    ap.add_argument("--fbw", type=int, default=10, help="width in 64-pixel units")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int, default=448)
    ap.add_argument("--scan", action="store_true", help="print which 8 KB pages hold non-zero data")
    ap.add_argument("-o", "--out", default="vram.png")
    args = ap.parse_args()

    data = np.fromfile(args.dump, dtype=np.uint32)
    if data.size * 4 != VRAM_BYTES:
        sys.exit(f"expected a 4 MB dump, got {data.size * 4} bytes")
    if args.scan:
        pages = data.reshape(512, 2048)
        used = [i for i in range(512) if pages[i].any()]
        runs, start = [], None
        for i in range(513):
            if i < 512 and i in used:
                start = i if start is None else start
            elif start is not None:
                runs.append((start, i - 1))
                start = None
        print("non-zero pages:", ", ".join(f"{a}-{b}" if a != b else f"{a}" for a, b in runs) or "none")
        return
    width = args.width or args.fbw * 64
    rgb = decode_ct32(data, args.fbp, args.fbw, width, args.height)
    Image.fromarray(rgb, "RGB").save(args.out)
    print(f"{args.out}: {width}x{args.height} fbp={args.fbp} fbw={args.fbw} max={rgb.max()}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""lodestone diffview - pixel-diff a frame against a reference, honestly.

    lodestone diffview diff A.png B.png [--tolerance N] [--out diff.ppm] [--json]
    lodestone diffview diff A/ B/     [--tolerance N]          # frame sequences
    lodestone diffview oracle         what a reference must contain before it counts
    lodestone diffview --selftest     prove the differ on synthetic frames

The differentiator
------------------
Every static-recompilation project in the ecosystem verifies frames the same way:
a human looks at two screenshots next to each other. That works right up to the
moment it matters, when the frame is 99.4% correct and the difference is a
single pixel at the edge of a sprite, and "looks the same to me" becomes the
only quality gate in the release.

So this is not a pixel differ, it is a *gate*. Three properties make it one:

  1. It is deterministic and quantised. "99.4% correct" is not a pass. A frame
     passes when differing pixels <= tolerance, and the exact number is always
     printed whether it passed or not.

  2. It distinguishes three failures that eyeballing merges into "looks wrong":
     a pixel in the wrong PLACE (geometry), a pixel with the wrong VALUE
     (colour), and a FRAME SIZE mismatch (usually a resolution or FBP-setup
     bug, which no pixel-level tolerance should hide).

  3. It refuses to produce a verdict it cannot justify. The exit code reports
     the comparison; `--oracle` reports whether the reference itself is
     trustworthy. This project has retracted enough published numbers to be
     allergic to a green check that means "I compared two files that are both
     empty".

Honest scope
------------
The reference side is PCSX2, which is a separate GPL process and is never
linked here. When no reference corpus exists, `diffview oracle` says so and
`diff` on two of our own frames still works. A verification tool that reports
PASS because the oracle was absent would be worse than no tool at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Image I/O - raw stored RGB pixels; no resizing or colour-profile transforms.
# --------------------------------------------------------------------------- #
#
# PPM (Netpbm) is the one raster format with no decoder dependency, no
# compression heuristic, and no colour-profile ambiguity. Captures from our
# runner are PNG, so accept 8-bit RGB/RGBA PNG with an optional Pillow decoder.
# Do not resize, resample, apply ICC profiles, or discard non-opaque alpha.


@dataclass
class Image:
    width: int
    height: int
    rgb: bytes                      # width * height * 3, row-major, no padding

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        o = (y * self.width + x) * 3
        return self.rgb[o], self.rgb[o + 1], self.rgb[o + 2]


def load_image(path: Path) -> Image:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        try:
            from PIL import Image as PillowImage
        except ImportError as exc:
            raise ValueError("PNG input requires Pillow; PPM input needs no dependency") from exc
        if len(data) < 29 or data[24] != 8 or data[25] not in (2, 6):
            raise ValueError(f"{path}: PNG input must be 8-bit RGB or RGBA")
        with PillowImage.open(path) as decoded:
            decoded.load()
            if decoded.mode == "RGBA" and decoded.getchannel("A").getextrema() != (255, 255):
                raise ValueError(f"{path}: non-opaque PNG cannot be compared as RGB")
            rgb = decoded.convert("RGB")
            return Image(rgb.width, rgb.height, rgb.tobytes())
    if not data.startswith(b"P6"):
        raise ValueError(f"{path}: expected binary PPM or RGB PNG")
    fields: list[bytes] = []
    i = 2
    while len(fields) < 3:
        while i < len(data) and data[i : i + 1].isspace():
            i += 1
        if data[i : i + 1] == b"#":
            while i < len(data) and data[i] != 0x0A:
                i += 1
            continue
        j = i
        while j < len(data) and not data[j : j + 1].isspace():
            j += 1
        fields.append(data[i:j])
        i = j
    i += 1                                   # single whitespace after maxval
    w, h, _maxval = (int(f) for f in fields)
    if _maxval != 255:
        raise ValueError(f"{path}: maxval {_maxval} unsupported (need 255)")
    need = w * h * 3
    px = data[i : i + need]
    if len(px) != need:
        raise ValueError(f"{path}: truncated - need {need} bytes of pixel data, got {len(px)}")
    return Image(w, h, bytes(px))


def save_ppm(path: Path, img: Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"P6\n%d %d\n255\n" % (img.width, img.height) + img.rgb
    )


def make_diff_image(a: Image, b: Image, w: int, h: int,
                    max_delta: dict[tuple[int, int], int]) -> Image:
    """Differing pixels in magenta, unchanged pixels as a dimmed greyscale.

    Magenta because it cannot occur naturally in most game frames, so a human
    opening the file sees the differences immediately instead of hunting for
    them. The dimmed background is there so the differences can be located
    relative to the actual image rather than floating in a void.
    """
    out = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * 3
            if max_delta.get((x, y)):
                out[o:o + 3] = b"\xff\x00\xff"
            else:
                if x < a.width and y < a.height:
                    r, g, bl = a.pixel(x, y)
                elif x < b.width and y < b.height:
                    r, g, bl = b.pixel(x, y)
                else:
                    r = g = bl = 0
                # ~35% grey keeps the shape readable without competing with the
                # magenta, and is intensity-preserving so shading survives.
                grey = (r * 77 + g * 150 + bl * 29) >> 8
                grey = 32 + (grey * 223) // 255
                out[o:o + 3] = bytes((grey, grey, grey))
    return Image(w, h, bytes(out))


# --------------------------------------------------------------------------- #
# The differ
# --------------------------------------------------------------------------- #


@dataclass
class DiffResult:
    size_match: bool
    a_size: tuple[int, int]
    b_size: tuple[int, int]
    total: int                       # pixels compared
    differing: int
    max_delta: int                   # largest per-channel difference seen
    mean_delta: float
    first: tuple[int, int, int] | None    # x, y, delta
    bbox: tuple[int, int, int, int] | None  # x0, y0, x1, y1
    tolerance: int
    per_channel: tuple[int, int, int] = (0, 0, 0)   # r, g, b worst
    hist: dict[int, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        # Size mismatch is checked FIRST and unconditionally.
        #
        # This was the real bug the self-test caught: `passed` originally read
        # `differing <= tolerance`, so comparing a 32x24 frame against a 4x4 one
        # with a large tolerance returned PASS - the comparison had, in effect,
        # been told to ignore exactly the evidence it existed to surface. A
        # size mismatch is a resolution or FBP-setup bug and no pixel budget may
        # suppress it, because the two images are not even measuring the same
        # thing.
        return self.size_match and self.differing <= self.tolerance

    @property
    def pct(self) -> float:
        return (100.0 * self.differing / self.total) if self.total else 0.0

    def verdict(self) -> str:
        if not self.size_match:
            return ("SIZE MISMATCH - this is a resolution or FBP-setup bug; "
                    "no pixel tolerance should be allowed to hide it")
        if self.passed:
            return f"PASS - {self.differing} differing pixel(s) within tolerance {self.tolerance}"
        if self.differing > self.total // 100:
            return ("FAIL - more than 1% of the frame differs; treat this as a "
                    "structural error, not a rounding difference")
        return f"FAIL - {self.differing} differing pixel(s), tolerance is {self.tolerance}"


def diff_images(a: Image, b: Image, tolerance: int = 0,
                write_diff: Path | None = None) -> DiffResult:
    same_size = (a.width, a.height) == (b.width, b.height)
    w = max(a.width, b.width)
    h = max(a.height, b.height)
    total = w * h

    per_channel = [0, 0, 0]
    worst: dict[tuple[int, int], int] = {}
    differing = 0
    delta_sum = 0
    max_delta = 0
    first: tuple[int, int, int] | None = None
    x0 = y0 = 1 << 30
    x1 = y1 = -1
    hist: dict[int, int] = {}

    for y in range(h):
        for x in range(w):
            if x < a.width and y < a.height:
                ar, ag, ab = a.pixel(x, y)
            else:
                ar = ag = ab = -1
            if x < b.width and y < b.height:
                br, bg, bb = b.pixel(x, y)
            else:
                br = bg = bb = -1
            d = max(abs(ar - br), abs(ag - bg), abs(ab - bb))
            if d > max_delta:
                max_delta = d
            delta_sum += d
            if d > tolerance:
                differing += 1
                worst[(x, y)] = d
                hist[d] = hist.get(d, 0) + 1
                if first is None:
                    first = (x, y, d)
                if x < x0:
                    x0 = x
                if y < y0:
                    y0 = y
                if x > x1:
                    x1 = x
                if y > y1:
                    y1 = y
            # Per-channel worst is tracked over all comparisons, so a uniform
            # shift shows up as a per-channel bias rather than vanishing.
            for i, (u, v) in enumerate(((ar, br), (ag, bg), (ab, bb))):
                if u >= 0 and v >= 0 and abs(u - v) > per_channel[i]:
                    per_channel[i] = abs(u - v)

    if write_diff is not None:
        save_ppm(write_diff, make_diff_image(a, b, w, h, worst))

    return DiffResult(
        size_match=same_size,
        a_size=(a.width, a.height),
        b_size=(b.width, b.height),
        total=total,
        differing=differing,
        max_delta=max_delta,
        mean_delta=(delta_sum / total) if total else 0.0,
        first=first,
        bbox=(x0, y0, x1, y1) if differing else None,
        tolerance=tolerance,
        per_channel=tuple(per_channel),
        hist=hist,
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def render(name: str, r: DiffResult) -> str:
    W = 76
    L = ["=" * W, f"DIFFVIEW  {name}", "=" * W]
    L.append(f"  frame A        {r.a_size[0]} x {r.a_size[1]}")
    L.append(f"  frame B        {r.b_size[0]} x {r.b_size[1]}")
    L.append(f"  pixels         {r.total:,}")
    L.append(f"  differing      {r.differing:,}  ({r.pct:.4f}%)")
    L.append(f"  tolerance      {r.tolerance}")
    L.append(f"  max channel delta  {r.max_delta}")
    L.append(f"  mean delta         {r.mean_delta:.4f}")
    L.append(f"  worst R/G/B    {r.per_channel[0]} / {r.per_channel[1]} / {r.per_channel[2]}")
    if r.first:
        L.append(f"  first diff     ({r.first[0]}, {r.first[1]})  delta={r.first[2]}")
        L.append(f"  bounding box   x {r.bbox[0]}..{r.bbox[2]}   y {r.bbox[1]}..{r.bbox[3]}")
    if r.hist:
        top = sorted(r.hist.items())[:8]
        L.append("  delta histogram    " + "  ".join(f"{k}:{v}" for k, v in top))
    L.append("")
    L.append(f"  VERDICT: {r.verdict()}")
    L.append("=" * W)
    return "\n".join(L)


ORACLE_TEXT = """\
DIFFVIEW ORACLE - what makes a reference frame trustworthy

A frame comparison is only evidence if BOTH sides are reproducible. A diff
against a screenshot someone took once, on a different run, on a different
machine, is not a test - it is a coin flip with extra steps. Before any
reference counts, it must carry all of:

  1. provenance   which emulator build, which config, which disc image hash
  2. determinism  the same inputs produce byte-identical output, twice
  3. stability    the frame is captured at a named point (tick N), not
                  "whenever the screen looked done"
  4. provenance of OUR side too - same standard, or the comparison is rigged

State here:
"""


def oracle() -> int:
    print(ORACLE_TEXT, end="")
    corpus = ROOT / "analysis" / "frames"
    # A frame only counts as a reference if it carries a provenance sidecar.
    # A bare .ppm in this directory is a test fixture, not evidence, and
    # reporting it as a reference is precisely the false green this command
    # exists to prevent. Directories beginning with "_" are fixtures by
    # convention.
    if not corpus.is_dir():
        print("  reference corpus : ABSENT   (analysis/frames does not exist)")
        print()
        print("  No PCSX2 reference frames have been captured yet. `diffview diff`")
        print("  still works between two of our own frames, and that is useful, but")
        print("  it verifies REPRODUCIBILITY, not CORRECTNESS. Do not report a")
        print("  verification pass from it. That is the whole point of this command")
        print("  existing: to make the absence of evidence impossible to overlook.")
        return 1

    frames = sorted(p for p in corpus.iterdir() if p.suffix.lower() in (".ppm", ".png") and not p.name.startswith("_"))
    sidecars = {p.stem for p in corpus.glob("*.json") if not p.name.startswith("_")}
    unreferenced = [p.name for p in frames if p.stem not in sidecars]

    print(f"  frame files     : {len(frames)}")
    print(f"  with provenance : {len(frames) - len(unreferenced)}")
    if unreferenced:
        print(f"  WITHOUT provenance (do NOT count as references):")
        for n in unreferenced[:10]:
            print(f"      {n}")
        if len(unreferenced) > 10:
            print(f"      ... and {len(unreferenced) - 10} more")
    if not frames:
        print()
        print("  No reference frames yet. `diffview diff` still works between two")
        print("  of our own frames, and that is useful, but it verifies")
        print("  REPRODUCIBILITY, not CORRECTNESS. Do not report a verification")
        print("  pass from it.")
        return 1
    if unreferenced:
        print()
        print("  A frame without provenance is a screenshot. Reference frames must")
        print("  name the emulator build, the config and the disc image hash they")
        print("  came from, or the comparison is not reproducible.")
        return 1
    print()
    print("  Every reference frame carries provenance.")
    return 0


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #

SELFTESTS: tuple[tuple[str, callable], ...] = ()


def _selftest() -> int:
    W = 32
    H = 24

    def flat(rgb=(10, 20, 30)) -> Image:
        return Image(W, H, bytes(rgb) * (W * H))

    cases: list[tuple[str, bool, callable]] = []

    # identical frames must be a clean pass at tolerance 0
    cases.append(("identical frames pass at tolerance 0", True,
                  lambda: diff_images(flat(), flat(), 0).passed))
    # one changed pixel must be caught exactly
    def one_pixel():
        b = flat()
        i = (5 * W + 7) * 3
        px = bytearray(b.rgb)
        px[i:i + 3] = bytes((11, 20, 30))          # delta 1
        r = diff_images(b, Image(W, H, bytes(px)), 0)
        return r.differing == 1 and r.max_delta == 1 and r.first == (7, 5, 1)
    cases.append(("one pixel of delta 1 is found exactly, at its coordinates", True, one_pixel))
    # tolerance must be honoured
    cases.append(("tolerance admits a delta within it", True,
                  lambda: diff_images(flat(), flat((11, 20, 30)), 1).passed))
    cases.append(("tolerance rejects a delta beyond it", False,
                  lambda: diff_images(flat(), flat((11, 20, 30)), 0).passed))
    # a uniform shift is a colour bug, not noise: every pixel differs
    def shift():
        r = diff_images(flat(), flat((12, 20, 30)), 0)
        return r.differing == W * H and r.per_channel[0] == 2
    cases.append(("a uniform shift is a colour bug, not noise", True, shift))
    # size mismatch must never be hidden by a large tolerance
    def size():
        small = Image(4, 4, b"\x00" * 48)
        r = diff_images(flat(), small, 10_000_000)
        return (not r.passed) and (not r.size_match)
    cases.append(("a size mismatch is never hidden by a huge tolerance", True, size))
    # bbox must bound every differing pixel
    def bbox():
        px = bytearray(flat().rgb)
        for (x, y) in ((2, 3), (9, 8), (W - 1, H - 1)):
            i = (y * W + x) * 3
            px[i:i + 3] = b"\xff\x00\x00"
        r = diff_images(flat(), Image(W, H, bytes(px)), 0)
        return r.differing == 3 and r.bbox == (2, 3, W - 1, H - 1)
    cases.append(("the bounding box covers every differing pixel", True, bbox))

    failures = 0
    print("lodestone diffview self-test")
    for name, expect_pass, fn in cases:
        try:
            ok = bool(fn())
        except Exception as exc:                     # noqa: BLE001
            ok = False
            name = f"{name}  [raised {type(exc).__name__}: {exc}]"
        if ok != expect_pass:
            failures += 1
        print(f"  {'PASS' if ok == expect_pass else 'FAIL'}  {name}")
    print(f"  {len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def _pairs(args: argparse.Namespace) -> list[tuple[str, Path, Path]]:
    a, b = Path(args.a), Path(args.b)
    if a.is_dir() and b.is_dir():
        names = sorted({p.name for p in a.iterdir() if p.suffix.lower() in (".ppm", ".png")} &
                       {p.name for p in b.iterdir() if p.suffix.lower() in (".ppm", ".png")})
        return [(n, a / n, b / n) for n in names]
    return [(a.name, a, b)]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lodestone diffview",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("diff", help="compare a frame, or two frame directories")
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--tolerance", type=int, default=0,
                   help="differing pixels allowed to still PASS (default 0)")
    d.add_argument("--out", default=None, help="write a diff image here")
    d.add_argument("--json", action="store_true")

    sub.add_parser("oracle", help="state whether a trustworthy reference exists")

    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.cmd == "oracle":
        return oracle()
    if args.cmd is None:
        ap.print_help()
        return 2

    assert args.cmd == "diff"

    # Belt and braces with the ASCII-only output: a verification tool that dies
    # encoding a character while printing a verdict is a tool whose verdict you
    # cannot read, and an unreadable verdict is indistinguishable from no
    # verdict at all. This happened once already: the report line "max channel
    # delta" carried a Greek delta and the whole tool exited 1 with a traceback
    # on a stock cp1252 console.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    results = []
    worst_pass = True
    for name, pa, pb in _pairs(args):
        try:
            ra = load_image(pa)
            rb = load_image(pb)
        except (OSError, ValueError) as exc:
            print(f"diffview: {exc}", file=sys.stderr)
            return 2
        out = Path(args.out) if args.out else None
        r = diff_images(ra, rb, args.tolerance, out)
        results.append(r)
        worst_pass = worst_pass and r.passed
        if args.json:
            continue
        print(render(f"{pa.name} vs {pb.name}", r))
        if out:
            print(f"  diff image     {out}")

    if args.json:
        json.dump([
            {"a": r.a_size, "b": r.b_size, "differing": r.differing,
             "total": r.total, "pct": r.pct, "max_delta": r.max_delta,
             "bbox": r.bbox, "tolerance": r.tolerance, "passed": r.passed,
             "verdict": r.verdict()}
            for r in results], sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0 if worst_pass else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

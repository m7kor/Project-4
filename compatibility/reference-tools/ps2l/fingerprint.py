#!/usr/bin/env python3
"""lodestone fingerprint <ELF|ISO>  — one command that opens everything.

Prints: identity, ELF layout, code-size estimate, SCE syscall census,
string fingerprints, and AFS/archive detection for the parent disc.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
import sys
from pathlib import Path

MIPS_SYSCALL = 0x0C
PS2_SDK_PREFIXES = (
    "sceCd", "sceCdRead", "sceSif", "sceGs", "sceGif", "sceDma", "sceIpu",
    "sceMpeg", "sceSpu", "scePad", "sceMc", "sceDeci2", "sceNet", "sceVu0",
    "sceFs", "sceFile", "sceAio", "sceScatter", "sceKernel", "sceTty",
)
INTERESTING_STRINGS = (
    b"sceKernel", b"sceCd", b"sceGs", b"sceGif", b"sceSif", b"sceMpeg",
    b"sceIpu", b"sceSpu", b"sceVu0", b"scePad", b"sceMc", b"ioprp",
    b"IOPRP", b"DRIVERS", b"MODULES", b"AUDIOD", b".IRX", b".irx",
    b".afs", b".AFS", b".DAT", b".dat", b"0flist", b"0FLIST",
    b"VAG", b"ADPCM", b"ADX", b"TIM2", b"OGG", b"ogg", b"ATR", b"str",
    b"rpc", b"SIO2", b"sio2", b"PADMAN", b"MCMAN", b"MCSERV",
)


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_boot_elf(target: Path) -> Path:
    """If given an ISO dir or a SYSTEM.CNF-bearing dir, resolve BOOT2."""
    cnf = target / "SYSTEM.CNF"
    if not cnf.is_file():
        return target
    text = cnf.read_text(errors="replace")
    m = re.search(r"BOOT2\s*=\s*.*?\\([^\s;]+)", text)
    if not m:
        return target
    cand = target / m.group(1)
    return cand if cand.is_file() else target


def parse_elf(data: bytes, path: Path) -> dict:
    if data[:4] != b"\x7fELF":
        die(f"{path} is not an ELF")
    e_type, e_machine, _ver, e_entry, e_phoff, e_shoff, _flags = struct.unpack_from(
        "<HHIIIII", data, 16
    )
    _ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
        "<HHHHHH", data, 40
    )

    loads = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if off + 32 > len(data):
            break
        p_type, p_off, p_vaddr, _paddr, p_filesz, p_memsz, p_flags, _al = struct.unpack_from(
            "<IIIIIIII", data, off
        )
        if p_type == 1:
            loads.append((p_off, p_vaddr, p_filesz, p_memsz, p_flags))

    # Function estimate from call/branch density + average PS2 function size.
    # Locate the real code sections. PT_LOAD filesz includes .data/.sndata/
    # .rodata, and scanning those as instructions inflates every count below —
    # The former census also mistook ANDI for SYSCALL. Decode SPECIAL's
    # function field below, not primary opcode 0x0C.
    text_secs, load_secs, overlays = parse_sections(data)
    code_bytes = sum(s[1] for s in text_secs)

    body_off, body_sz = 0, 0
    if text_secs:
        body_off, body_sz = text_secs[0][0], code_bytes
    body = b"".join(data[offset:offset + size] for offset, size, _ in text_secs)

    calls = 0
    syscalls = 0
    syscall_imms: dict[int, int] = {}
    words = len(body) >> 2
    for i in range(0, len(body) - 3, 4):
        w = struct.unpack_from("<I", body, i)[0]
        op = w >> 26
        if op == 0 and (w & 0x3F) == MIPS_SYSCALL:
            syscalls += 1
            imm = (w >> 6) & 0xFFFFF
            syscall_imms[imm] = syscall_imms.get(imm, 0) + 1
        elif op in (0x02, 0x03):  # J / JAL
            calls += 1

    # PS2 code averages ~180-320 bytes/function. Estimate, never a claim.
    est_lo = max(1, code_bytes // 320)
    est_hi = max(1, code_bytes // 180)

    strings: dict[str, int] = {}
    for needle in INTERESTING_STRINGS:
        n = data.count(needle)
        if n:
            strings[needle.decode()] = n

    sdk_hits: dict[str, int] = {}
    for pref in PS2_SDK_PREFIXES:
        n = len(re.findall(rb"\b" + pref.encode(), data))
        if n:
            sdk_hits[pref] = n

    return {
        "type": e_type, "machine": e_machine, "entry": e_entry,
        "phnum": e_phnum, "shnum": e_shnum,
        "loads": loads,
        "text_off": body_off, "text_filesz": body_sz,
        "text_sections": len(text_secs),
        "load_sections": len(load_secs),
        "overlays": overlays,
        "calls": calls, "syscalls": syscalls,
        "syscall_imms": syscall_imms, "strings": strings, "sdk_hits": sdk_hits,
        "words": words,
    }


def parse_sections(data: bytes):
    """Return (body_code_file_ranges, other_exec, overlay_count).

    Mirrors the rule that made the analyzer correct: a section holds function
    bodies only if it is EXECUTABLE and NOT WRITABLE. RE4 marks .data R|W|X
    because the EE jumps through pointer arrays in it."""
    e_shoff, = struct.unpack_from("<I", data, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 46)
    if not e_shoff or not e_shnum:
        return [], [], 0
    raw = [struct.unpack_from("<10I", data, e_shoff + i * e_shentsize)
           for i in range(e_shnum)]
    str_off = raw[e_shstrndx][4] if e_shstrndx < len(raw) else 0

    def nm(x: int) -> str:
        b = str_off + x
        end = data.find(b"\0", b)
        return data[b:end].decode("latin1") if end > b else ""

    SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR = 0x1, 0x2, 0x4
    body, other, overlays = [], [], 0
    for r in raw:
        name_off, sh_type, flags, addr, off, size = r[0], r[1], r[2], r[3], r[4], r[5]
        name = nm(name_off)
        if "overlay" in name.lower():
            overlays += 1
            continue
        if sh_type == 8 or not (flags & SHF_EXECINSTR) or not size:
            continue
        if flags & SHF_WRITE:
            other.append((addr, size, name))
        else:
            body.append((off, size, name))
    return body, other, overlays


def survey_disc(root: Path) -> list[tuple[str, int]]:
    """Deduplicate by lowercase name: on Windows glob is case-insensitive, so
    '*.afs' and '*.AFS' return the same files twice."""
    found: dict[str, tuple[str, int]] = {}
    pats = ("*.afs", "*.dat", "*.img", "*.bin", "*.vld", "0*list.dir", "SYSTEM.CNF")
    for p in sorted(root.rglob("*")):
        if not p.is_file() or not any(p.match(pat) for pat in pats):
            continue
        # Skip generated trees; we want the disc's own data.
        if any(part.lower() in ("generated", "build", ".git", "out") for part in p.parts):
            continue
        st = p.stat()
        key = str(p.relative_to(root)).lower()
        prev = found.get(key)
        if prev is None or st.st_size > prev[1]:
            found[key] = (str(p.relative_to(root)), st.st_size)
    return sorted(found.values(), key=lambda t: -t[1])


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}GB"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    raw = Path(argv[1])
    if not raw.exists():
        die(f"{raw} does not exist")

    elf = find_boot_elf(raw if raw.is_dir() else raw.parent)
    if elf.is_dir():
        die(f"no ELF found under {elf}")
    if elf.suffix.lower() not in (".elf", "") and elf.read_bytes()[:4] != b"\x7fELF":
        die(f"{elf} is not an ELF (and no SYSTEM.CNF BOOT2 resolved)")

    data = elf.read_bytes()
    info = parse_elf(data, elf)
    root = elf.parent

    print("=" * 72)
    print(f"LODESTONE fingerprint   {elf}")
    print("=" * 72)
    print(f"  size        {len(data):,} bytes")
    print(f"  sha256      {sha256_of(elf)}")
    print(f"  elf         type={info['type']} machine=0x{info['machine']:X} "
          f"({'MIPS/PS2-EE' if info['machine'] == 8 else 'UNEXPECTED'})")
    print(f"  entry       0x{info['entry']:08X}")
    print(f"  phnum/shnum {info['phnum']} / {info['shnum']}")
    for off, va, fsz, msz, fl in info["loads"]:
        bss = msz - fsz
        print(f"  LOAD        off=0x{off:08X} vaddr=0x{va:08X} "
              f"filesz=0x{fsz:X} memsz=0x{msz:X} flags=0x{fl:X} "
              f"bss={human(bss)}")
        if len(info["loads"]) == 1:
            print("              ^ one segment, but that says NOTHING about overlays")
            print("                (RE4 has 93; run `lodestone analyze` to see them)")

    print("-" * 72)
    print("  CODE SIZE  (from section headers, not PT_LOAD filesz)")
    print(f"    body sections   {info['text_sections']}   "
          f"{human(info['text_filesz'])} ({info['words']:,} words)")
    print(f"    exec+write      {info['load_sections']} sections (jump tables, "
          f"not function bodies)")
    print(f"    J/JAL sites     {info['calls']:,}")
    print(f"    SYSCALL sites   {info['syscalls']:,}")
    print(f"    est. functions  {info['text_filesz']//320:,} .. "
          f"{info['text_filesz']//180:,}   (180-320 B/fn)")
    if info["overlays"]:
        print(f"    overlays        {info['overlays']}  <- "
              f"`lodestone analyze` will enumerate them")

    print("-" * 72)
    print("  SYSCALL CODE FIELDS  (does not establish retail/homebrew origin or runtime IDs)")
    top = sorted(info["syscall_imms"].items(), key=lambda kv: -kv[1])
    for imm, n in top[:12]:
        print(f"    0x{imm:05X}  x{n:>5}")
    if len(top) > 12:
        print(f"    ... {len(top) - 12} more distinct syscall immediates")

    if info["strings"]:
        print("-" * 72)
        print("  STRING FINGERPRINTS")
        for k, v in sorted(info["strings"].items(), key=lambda kv: -kv[1])[:16]:
            print(f"    {k:<12} x{v}")

    if info["sdk_hits"]:
        print("-" * 72)
        print("  SDK SYMBOL HITS  (absent = stripped; low count = need Ghidra)")
        for k, v in sorted(info["sdk_hits"].items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {k:<12} x{v}")

    disc = survey_disc(root)
    if disc:
        print("-" * 72)
        print("  DISC SURVEY  (the runner needs ALL of this at runtime)")
        for name, size in disc:
            print(f"    {name:<28} {human(size)}")
        big = [d for d in disc if d[1] > 16 * 1024 * 1024]
        if big:
            print(f"    ^ {len(big)} file(s) > 16MB must be streamed, not loaded.")

    print("-" * 72)
    print("  NEXT")
    print("    lodestone check   <terms>      # failure memory, before you try anything")
    print(f"    lodestone analyze {elf}")
    print("    lodestone status                # stage tracker")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    import sys as _sys
    for _s in (_sys.stdout, _sys.stderr):   # a Windows console is not UTF-8
        _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv))

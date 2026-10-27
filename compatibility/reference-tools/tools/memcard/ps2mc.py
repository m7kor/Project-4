"""Read-only browser for PS2 memory card images (8 MB, 528-byte pages with ECC).

    python tools/memcard/ps2mc.py CARD.ps2 ls [DIR]
    python tools/memcard/ps2mc.py CARD.ps2 get DIR/FILE OUT
    python tools/memcard/ps2mc.py CARD.ps2 hexdump DIR/FILE [--offset N] [--length N]

Never writes to the card image.
"""
import argparse
import struct
import sys

MAGIC = b"Sony PS2 Memory Card Format "
DF_DIRECTORY = 0x0020
DF_EXISTS = 0x8000


class Card:
    def __init__(self, path):
        self.raw = open(path, "rb").read()
        sb = self._page(0)
        if not sb.startswith(MAGIC):
            sys.exit(f"{path}: not a formatted PS2 memory card (no superblock)")
        (self.page_len, self.pages_per_cluster, _ppb) = struct.unpack_from("<HHH", sb, 0x28)
        (self.clusters_per_card, self.alloc_offset, self.alloc_end,
         self.rootdir_cluster) = struct.unpack_from("<IIII", sb, 0x30)
        self.ifc_list = struct.unpack_from("<32I", sb, 0x50)
        self.raw_page = self.page_len + (16 if len(self.raw) % (self.page_len + 16) == 0 else 0)
        self.cluster_len = self.page_len * self.pages_per_cluster
        self._fat = None

    def _page(self, index):
        size = 528 if len(self.raw) % 528 == 0 else 512
        return self.raw[index * size:index * size + 512]

    def cluster(self, absolute):
        first = absolute * self.pages_per_cluster
        return b"".join(self._page(first + i) for i in range(self.pages_per_cluster))

    def fat(self):
        if self._fat is None:
            per = self.cluster_len // 4
            entries = []
            for ifc in self.ifc_list:
                if ifc == 0 or ifc == 0xFFFFFFFF:
                    continue
                for fat_cluster in struct.unpack(f"<{per}I", self.cluster(ifc)):
                    if fat_cluster == 0xFFFFFFFF:
                        continue
                    entries.extend(struct.unpack(f"<{per}I", self.cluster(fat_cluster)))
            self._fat = entries
        return self._fat

    def chain(self, start):
        fat, out, c = self.fat(), [], start
        while c != 0x7FFFFFFF and len(out) < len(fat):
            out.append(c)
            entry = fat[c]
            if entry == 0xFFFFFFFF or not entry & 0x80000000:
                break
            c = entry & 0x7FFFFFFF
        return out

    def read_chain(self, start, length):
        data = b"".join(self.cluster(c + self.alloc_offset) for c in self.chain(start))
        return data[:length]

    def entries(self, cluster, count):
        data = self.read_chain(cluster, count * 512)
        for i in range(count):
            e = data[i * 512:(i + 1) * 512]
            mode, length = struct.unpack_from("<HxxI", e, 0)
            first = struct.unpack_from("<I", e, 0x10)[0]
            name = e[0x40:0x60].split(b"\0")[0].decode("ascii", "replace")
            if mode & DF_EXISTS:
                yield name, mode, length, first

    def root(self):
        # The root's own "." entry stores the number of entries in its length.
        first = self.read_chain(self.rootdir_cluster, 512)
        count = struct.unpack_from("<I", first, 4)[0]
        return self.rootdir_cluster, count

    def lookup(self, path):
        cluster, count = self.root()
        parts = [p for p in path.strip("/").split("/") if p]
        for i, part in enumerate(parts):
            for name, mode, length, first in self.entries(cluster, count):
                if name == part:
                    if i == len(parts) - 1:
                        return name, mode, length, first
                    cluster, count = first, length
                    break
            else:
                sys.exit(f"not found: {path}")
        return "/", DF_DIRECTORY | DF_EXISTS, count, cluster


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("card")
    ap.add_argument("cmd", choices=["ls", "get", "hexdump"])
    ap.add_argument("path", nargs="?", default="/")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--offset", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--length", type=lambda v: int(v, 0), default=256)
    args = ap.parse_args()
    card = Card(args.card)
    name, mode, length, first = card.lookup(args.path)
    if args.cmd == "ls":
        if not mode & DF_DIRECTORY:
            sys.exit(f"{args.path} is a file of {length} bytes")
        for n, m, l, _ in card.entries(first, length):
            kind = "dir " if m & DF_DIRECTORY else "file"
            print(f"{kind} {l:8d}  {n}")
        return
    data = card.read_chain(first, length)
    if args.cmd == "get":
        if not args.out:
            sys.exit("get needs an output path")
        open(args.out, "wb").write(data)
        print(f"{args.out}: {len(data)} bytes")
        return
    chunk = data[args.offset:args.offset + args.length]
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        print(f"{args.offset + i:06x}  {row.hex(' ')}")


if __name__ == "__main__":
    main()

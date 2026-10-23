"""Name EE addresses with the original ELF's symbol table (STT_FUNC symbols).

    python -m tools.diagnostics.elf_symbolize ELF ADDR [ADDR...]
    python -m tools.diagnostics.elf_symbolize ELF --grep REGEX
"""
import argparse
import bisect
import re
import struct


def functions(elf):
    shoff = struct.unpack_from('<I', elf, 32)[0]
    shentsize, shnum = struct.unpack_from('<HH', elf, 46)
    sections = [struct.unpack_from('<10I', elf, shoff + i * shentsize) for i in range(shnum)]
    out = []
    for s in sections:
        if s[1] != 2:  # SHT_SYMTAB
            continue
        strtab = sections[s[6]]
        for at in range(s[4], s[4] + s[5], 16):
            name, value, size, info = struct.unpack_from('<IIIB', elf, at)
            if info & 15 != 2 or not value:
                continue
            end = elf.index(b'\0', strtab[4] + name)
            out.append((value, size, elf[strtab[4] + name:end].decode('latin-1')))
    return sorted(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('elf')
    parser.add_argument('addresses', nargs='*')
    parser.add_argument('--grep')
    args = parser.parse_args()
    table = functions(open(args.elf, 'rb').read())
    if args.grep:
        for value, size, name in table:
            if re.search(args.grep, name):
                print(f'{value:#08x} {size:6d} {name}')
    starts = [t[0] for t in table]
    for text in args.addresses:
        address = int(text, 0)
        i = bisect.bisect_right(starts, address) - 1
        if i >= 0 and address < table[i][0] + max(table[i][1], 4):
            print(f'{address:#08x} {table[i][2]}+{address - table[i][0]:#x}')
        else:
            print(f'{address:#08x} ?')


if __name__ == '__main__':
    main()

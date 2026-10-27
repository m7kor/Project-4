"""Locate selected SNR2 imports in original ELF exports without modifying bytes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.diagnostics.snr2_imports import resolve_imports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', type=Path)
    parser.add_argument('elf', type=Path)
    parser.add_argument('--name', nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Preserve existing resolution evidence')
    result = resolve_imports(args.module.read_bytes(), args.elf.read_bytes(), args.name)
    result['module_path'] = str(args.module.resolve())
    result['elf_path'] = str(args.elf.resolve())
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    for row in result['imports']:
        print(f"{row['name']}: 0x{row['address']:08x}, export 0x{row['export_record']:08x}")


if __name__ == '__main__':
    main()

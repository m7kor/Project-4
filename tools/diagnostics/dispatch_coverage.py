"""Find Ghidra function entries the recompiled runner cannot dispatch to.

A `[guest-branch:missing-target]` fault means guest code jumped (usually JALR
through a function pointer) to an address with no entry in the generated
dispatch table. This compares every function entry Ghidra knows (via the
GhidraMCP server) with the addresses registered in register_functions.cpp, and
ranks the gaps: entries whose address is taken as data (callbacks, vtables,
thread entries) are the ones an indirect call will reach.

    dependencies/GhidraMCP/.venv/Scripts/python.exe tools/diagnostics/dispatch_coverage.py \\
        [--generated recomp/generated/SLUS_211.34] [--xrefs] [--json out.json]
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / 'tools' / 'ghidra_mcp_call.py'
TEXT_BEGIN, TEXT_END = 0x100000, 0x2EF914  # dense dispatch table range of the main ELF


def mcp(tool, **args):
    command = [sys.executable, str(CLIENT), tool] + [f'{k}={v}' for k, v in args.items()]
    out = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    return json.loads(out[out.index('{'):])


def ghidra_functions():
    items, offset = [], 0
    while True:
        page = mcp('list_functions', offset=offset, limit=2000)
        items += page['items']
        if not page.get('has_more'):
            return items
        offset += len(page['items'])


def registered(generated):
    pattern = re.compile(r'// 0x([0-9a-fA-F]+)\s*$')
    out = set()
    with open(generated / 'register_functions.cpp', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = pattern.search(line)
            if m:
                out.add(int(m[1], 16))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--generated', type=Path, default=ROOT / 'recomp' / 'generated' / 'SLUS_211.34')
    parser.add_argument('--xrefs', action='store_true', help='classify each gap by its references (slower)')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()

    table = registered(args.generated)
    functions = ghidra_functions()
    gaps = []
    for fn in functions:
        address = int(fn['address'], 16)
        if TEXT_BEGIN <= address < TEXT_END and address not in table:
            gaps.append({'name': fn['name'], 'address': address})
    print(f'{len(functions)} Ghidra functions, {len(table)} registered dispatch addresses, '
          f'{len(gaps)} Ghidra entries in the main text without a dispatch entry')
    if args.xrefs:
        for gap in gaps:
            refs = mcp('get_xrefs_to', address=f'0x{gap["address"]:08x}')['items']
            kinds = sorted({r['type'] for r in refs})
            gap['refs'] = [{'from': r['from'], 'type': r['type'],
                            'function': (r.get('from_function') or {}).get('name')} for r in refs]
            gap['pointer'] = any(k in ('DATA', 'PARAM', 'READ', 'INDIRECTION') for k in kinds)
            gap['called'] = any('CALL' in k for k in kinds)
        gaps.sort(key=lambda g: (not g['pointer'], g['address']))
    for gap in gaps:
        line = f'  0x{gap["address"]:06X} {gap["name"]}'
        if args.xrefs:
            tag = 'POINTER' if gap['pointer'] else ('called' if gap['called'] else 'no refs')
            sources = ', '.join(f'{r["from"]}({r["type"]})' for r in gap['refs'][:3])
            line += f'  [{tag}] {sources}'
        print(line)
    if args.json:
        args.json.write_text(json.dumps(gaps, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()

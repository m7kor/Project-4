"""Compare one captured ADX call's original EE instructions and generated code.

Full RAM comparison includes decoder history, keys and stack writes, in addition
to PCM. Controlled checkpoints test generated resume entries; no other guest
threads execute. A match does not exclude wrong inputs or production scheduling.
"""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile

from replay_ee_adx import IntegerEE, signed


def compare(prefix, harness, report, periods=(0, 1, 8)):
    prefix, report = Path(prefix), Path(report)
    if report.exists():
        raise FileExistsError(report)
    metadata = json.loads(Path(str(prefix) + '.json').read_text())
    ram_path = Path(str(prefix) + '.ram.bin')
    ram = ram_path.read_bytes()
    if metadata['schema'] != 1 or metadata['ram_bytes'] != len(ram) or len(ram) != 32 * 1024 * 1024:
        raise ValueError('invalid snapshot')
    if metadata['target'] not in (0x19b1f8, 0x189870, 0x189a60, 0x189c30, 0x2af3ac,
                                0x18f758, 0x18f6c8, 0x18f698, 0x18f738, 0x1937c0,
                                0x18b490, 0x18b4f0, 0x189be0, 0x18f8e0,
                                0x192be0, 0x18ac18, 0x192758) or len(metadata['gpr_hex']) != 32:
        raise ValueError('unsupported call layout')
    cpu = IntegerEE(ram, metadata)
    return_pc = cpu.r[31] & 0xffffffff
    while cpu.pc != return_pc:
        if cpu.instructions >= 10000000:
            raise ValueError('original instruction limit reached')
        cpu.step()
    registers = [int(v, 16) for pair in metadata['gpr_hex'] for v in pair]
    context = struct.pack('<64Q4Q2I', *registers, *(int(v, 16) for v in metadata['hi_lo_hex']), metadata['target'], metadata['sa'])
    rows = []
    with tempfile.TemporaryDirectory(prefix='adx-compare-', dir=report.parent) as directory:
        directory = Path(directory)
        context_path = directory / 'context.bin'
        context_path.write_bytes(context)
        for period in periods:
            out = directory / f'compiled-{period}.ram.bin'
            run = subprocess.run([str(Path(harness).resolve()), str(ram_path.resolve()), str(context_path.resolve()),
                                  str(out.resolve()), str(period)], capture_output=True, text=True, timeout=60)
            if run.returncode:
                raise RuntimeError(f'compiled replay failed ({period}): {run.stderr}')
            compiled = out.read_bytes()
            if len(compiled) != len(cpu.ram):
                raise ValueError('compiled replay output size mismatch')
            differences = sum(a != b for a, b in zip(cpu.ram, compiled))
            first = next((i for i, (a, b) in enumerate(zip(cpu.ram, compiled)) if a != b), None)
            state = json.loads(run.stdout)
            expected = [[cpu.r[i], cpu.r_upper[i]] for i in range(32)]
            actual = [[int(v, 16) for v in pair] for pair in state['gpr_hex']]
            bad_registers = [i for i in range(32) if expected[i] != actual[i]]
            hi_lo_match = [cpu.hi, cpu.lo, cpu.hi1, cpu.lo1] == [int(v, 16) for v in state['hi_lo_hex']]
            rows.append({'period': period, 'different_ram_bytes': differences,
                         'first_difference_address': first, 'different_gprs': bad_registers,
                         'hi_lo_match': hi_lo_match, 'compiled': state})
    result = {'schema': 1, 'snapshot': str(prefix), 'original_instructions': cpu.instructions,
              'original_return_value': signed(cpu.r[2], 32), 'comparisons': rows,
              'all_match': all(r['different_ram_bytes'] == 0 and not r['different_gprs'] and r['hi_lo_match'] and r['compiled']['return_value'] == signed(cpu.r[2], 32) for r in rows),
              'scope': 'One integer call; no devices or competing threads. Does not validate input keys or scheduling.'}
    if report.exists():
        raise FileExistsError(report)
    report.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix')
    parser.add_argument('--harness', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.prefix, args.harness, args.out), indent=2))

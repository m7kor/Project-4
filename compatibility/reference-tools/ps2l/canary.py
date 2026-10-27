"""Compile and execute a known, redistributable EE program through the pipeline.

This checks generated CPU arithmetic and branch delay slots, not game playback.
The host harness invokes actual generated functions with a real R5900Context.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def fixture() -> bytes:
    # v0: 5 + taken-branch slot 7 + 3 + return slot 2 = 17.
    # Both +100 (branch bypass) and +1000 (annulled likely slot) must not run.
    words = [0x24080001, 0x24020005, 0x11080002, 0x24420007,
             0x24420064, 0x55080002, 0x244203E8, 0x24420003,
             0x03E00008, 0x24420002]
    return elf_for_words(words)


def tailcall_fixture() -> bytes:
    # The final +2 is executed in another translation unit via a direct jump.
    # A gap keeps the two mapped bodies distinct without needing a scheduler.
    words = [0x2402000F, 0x08040004, 0, 0, 0x03E00008, 0x24420002]
    return elf_for_words(words)


def quad_fixture() -> bytes:
    # All low-nibble combinations must transfer exactly one aligned quadword.
    words = []
    for offset in range(16):
        words.extend([(0x1e << 26) | (8 << 16) | (0x1010 + offset),
                      (0x1f << 26) | (8 << 16) | (0x2010 + offset * 32 + 15 - offset)])
    words.extend([(0x1e << 26) | (4 << 21) | (9 << 16) | 0xfff8,
                  (0x1f << 26) | (5 << 21) | (9 << 16) | 0xfff8,
                  0x24020011, 0x03e00008, 0])
    return elf_for_words(words)


def branch_fixture() -> tuple[bytes, int, int]:
    # a0=0x100000000 (positive, low word zero), a1=0x8000000000000001
    # (negative, low word positive). These distinguish hardware low64 tests
    # from the incorrect low32 comparisons, including likely annulment.
    words = [0x24080001, 0x24020005, 0x11080002, 0x24420007,
             0x24420064, 0x55080002, 0x244203E8, 0x24420003]
    cases = []
    for opcode, equal, likely in [(4, True, False), (5, False, False),
                                  (20, True, True), (21, False, True)]:
        cases.extend([(opcode, 4, 0, not equal, likely),
                      (opcode, 4, 4, equal, likely)])
    for opcode, greater, likely in [(6, False, False), (7, True, False),
                                    (22, False, True), (23, True, True)]:
        for reg, positive in [(4, True), (5, False)]:
            cases.append((opcode, reg, 0, positive == greater, likely))
    for subop in [0, 1, 2, 3, 16, 17, 18, 19]:
        for reg, positive in [(4, True), (5, False)]:
            cases.append((1, reg, subop, positive == bool(subop & 1), bool(subop & 2)))
    slots = 0
    for opcode, rs, rt, taken, likely in cases:
        offset = 2 if taken else 3
        words.extend([(opcode << 26) | (rs << 21) | (rt << 16) | offset,
                      0x24630001])  # addiu v1,v1,1 in the conditional slot
        slots += int(taken or not likely)
        if not taken:
            words.extend([0x10000002, 0])  # bypass failure counter
        words.append(0x24420064)  # wrong decision adds 100 to v0
    # REGIMM link instructions overwrite ra; return via untouched t9.
    words.extend([0x0320F82D, 0x03E00008, 0x24420002])
    return elf_for_words(words), slots, len(cases)


def compare_fixture() -> tuple[bytes, int, int]:
    # Harness registers distinguish low64 operands from identical/contradictory
    # low32 values. Include the exact unsigned threshold shape used by RE4.
    words = [0x24020011]
    cases = [(0x2a, 5, 0, 1), (0x2a, 4, 6, 1), (0x2a, 6, 4, 0),
             (0x2b, 0, 4, 1), (0x2b, 6, 7, 1), (0x2b, 7, 6, 0)]
    immediates = [(10, 4, 1, 0), (10, 5, 1, 1), (10, 6, 0, 0),
                  (11, 6, -1, 1), (11, 7, -1, 1), (11, 4, 1, 0),
                  (10, 0, -1, 0), (10, 5, -32768, 1), (11, 7, -32768, 1)]
    instructions = [(rs << 21) | (rt << 16) | (8 << 11) | fn
                    for fn, rs, rt, _ in cases]
    instructions += [(op << 26) | (rs << 21) | (8 << 16) | (imm & 0xffff)
                     for op, rs, imm, _ in immediates]
    for instruction, expected in zip(instructions, [c[3] for c in cases + immediates]):
        words.extend([instruction, 0x24090000 | expected, 0x11090002, 0, 0x24420064])
    # Finite probe of RE4's doubling loop: 2^32 exceeds 2^60-1 after 28 steps.
    words.extend([0x0080502D, 0x24080000])  # daddu t2,a0,zero; addiu t0,zero,0
    # Unroll the bounded loop so the standalone harness needs no scheduler.
    for _ in range(32):
        words.extend([0x15000004, 0, 0x000A5078, 0x24630001, 0x00CA402B])
    words.extend([0x15000002, 0, 0x244203E8])
    words.extend([0x03E00008, 0])
    return elf_for_words(words), 28, len(instructions)


def elf_for_words(words: list[int]) -> bytes:
    code = struct.pack(f'<{len(words)}I', *words)
    names = b'\0.text\0.shstrtab\0'
    names_offset = (0x100 + len(code) + 15) & ~15
    sections_offset = (names_offset + len(names) + 15) & ~15
    data = bytearray(sections_offset + 3 * 40)
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 0, ident, 2, 8, 1,
                     0x100000, 52, sections_offset, 0x20924001, 52, 32, 1, 40, 3, 2)
    struct.pack_into('<8I', data, 52, 1, 0x100, 0x100000, 0x100000,
                     len(code), len(code), 5, 16)
    data[0x100:0x100 + len(code)] = code
    data[names_offset:names_offset + len(names)] = names
    struct.pack_into('<10I', data, sections_offset + 40, 1, 1, 6, 0x100000, 0x100,
                     len(code), 0, 0, 4, 0)
    struct.pack_into('<10I', data, sections_offset + 80, 7, 3, 0, 0, names_offset,
                     len(names), 0, 0, 1, 0)
    return bytes(data)


def move_fixture() -> tuple[bytes, int, int]:
    # Taken, untaken, zero-source and self-aliasing conditional scalar moves.
    # The harness seeds distinct upper halves, which must remain unchanged.
    cases = [(8, 4, 0, 10), (9, 4, 4, 11), (10, 4, 4, 10),
             (11, 4, 0, 11), (12, 0, 0, 10), (13, 5, 5, 11),
             (14, 14, 0, 10), (15, 15, 15, 11)]
    words = [0x24020011]
    words += [(rs << 21) | (rt << 16) | (rd << 11) | fn
              for rd, rs, rt, fn in cases]
    words += [(4 << 21) | 10, (4 << 21) | (4 << 16) | 11,
              0x03e00008, 0]
    return elf_for_words(words), 0, len(cases) + 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='lodestone canary')
    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts/canary')
    parser.add_argument('--runtime-root', type=Path, default=ROOT / 'core',
                        help='Existing read-only core headers; output stays under --out')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--branch64', action='store_true', help='execute low64 branch and likely-slot probes')
    mode.add_argument('--compare64', action='store_true', help='execute low64 set-less-than and RE4 doubling probes')
    mode.add_argument('--tailcall', action='store_true', help='execute a direct transfer between generated source files')
    mode.add_argument('--move64', action='store_true', help='check scalar conditional moves preserve upper register halves')
    mode.add_argument('--quad-align', action='store_true', help='execute all sixteen LQ/SQ address alignments')
    parser.add_argument('--recompiler', type=Path, default=ROOT / 'core/out/build/ps2xRecomp' /
                        ('ps2_recomp.exe' if os.name == 'nt' else 'ps2_recomp'))
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'generated-ee-low64-conditional-moves' if args.move64 else 'generated-ee-direct-transfer-and-incremental-dependencies' if args.tailcall else 'generated-ee-low64-comparisons' if args.compare64 else 'generated-ee-low64-branches-and-delay-slots' if args.branch64 else 'generated-ee-arithmetic-and-delay-slots',
              'game_compatibility': 'unverified', 'expected_v0': 17, 'checks': [], 'passed': False}

    def run(name: str, command: list[str]) -> str:
        print(f'Checking canary {name}...', flush=True)
        start = time.monotonic()
        result = subprocess.run(command, cwd=out, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=180)
        (out / f'{name}.stdout.txt').write_text(result.stdout, encoding='utf-8')
        (out / f'{name}.stderr.txt').write_text(result.stderr, encoding='utf-8')
        report['checks'].append({'name': name, 'exit_code': result.returncode,
                                 'seconds': round(time.monotonic() - start, 3)})
        if result.returncode:
            raise RuntimeError(f'{name} failed ({result.returncode}); see {out}')
        return result.stdout

    try:
        if not args.recompiler.is_file():
            raise RuntimeError('Build ps2_recomp before running the canary.')
        from build import _prepend_path
        _prepend_path()
        elf = out / 'canary.elf'
        program, expected_slots, branch_cases = move_fixture() if args.move64 else compare_fixture() if args.compare64 else branch_fixture() if args.branch64 else (tailcall_fixture() if args.tailcall else fixture(), 0, 0)
        elf.write_bytes(program)
        if args.quad_align:
            elf.write_bytes(quad_fixture())
            report['scope'] = 'generated-ee-lq-sq-alignment'
        report.update(branch_cases=branch_cases, expected_slots=expected_slots)
        report['elf_sha256'] = hashlib.sha256(elf.read_bytes()).hexdigest()
        run('analyze', [sys.executable, str(ROOT / 'ps2l/analyze.py'), str(elf),
                        '--out', str(out / 'analysis')])
        generated = out / 'generated'
        config = out / 'config.toml'
        config.write_text('[general]\n' + '\n'.join(
            f'{key} = {json.dumps(str(value).replace(chr(92), "/"))}'
            for key, value in [('input', elf), ('output', generated),
                               ('ghidra_output', out / 'analysis/functions.csv')]) +
            '\nsingle_file_output = false\n', encoding='utf-8')
        run('recompile', [str(args.recompiler.resolve()), str(config), '--prune-stale'])
        timestamps = {p.name: p.stat().st_mtime_ns for p in generated.glob('*.cpp')}
        run('recompile-repeat', [str(args.recompiler.resolve()), str(config), '--prune-stale'])
        if timestamps != {p.name: p.stat().st_mtime_ns for p in generated.glob('*.cpp')}:
            raise RuntimeError('Unchanged generated C++ was rewritten during repeat recompilation.')
        (out / 'main.cpp').write_text('''#include "ps2_runtime.h"
#include "ps2_recompiled_functions.h"
#include <iostream>
int main() {
    R5900Context ctx{};
    ctx.pc = 0x100000u;
    ctx.r[31] = _mm_set_epi64x(0, 0x123456u);
    ctx.r[25] = _mm_set_epi64x(0, 0x123456u);
    ctx.r[4] = _mm_set_epi64x(0, 0x100000000ll);
    ctx.r[5] = _mm_set_epi64x(0, static_cast<int64_t>(0x8000000000000001ull));
    ctx.r[6] = _mm_set_epi64x(0, 0x0fffffffffffffffll);
    ctx.r[7] = _mm_set_epi64x(0, 0x1000000000000000ll);
    MOVE_SETUP
    FUN_00100000_0x100000(nullptr, &ctx, nullptr);
    bool movesOkay = true;
    MOVE_CHECK
    const auto value = _mm_cvtsi128_si32(ctx.r[2]);
    const auto slots = _mm_cvtsi128_si32(ctx.r[3]);
    std::cout << "v0=" << value << " slots=" << slots << " pc=" << ctx.pc << " moves_ok=" << movesOkay << std::endl;
    return value == 17 && ctx.pc == 0x123456u &&
           _mm_cvtsi128_si32(ctx.r[0]) == 0 && slots == EXPECTED_SLOTS && movesOkay ? 0 : 1;
}
'''.replace('EXPECTED_SLOTS', str(expected_slots)).replace('MOVE_SETUP', '''
    ctx.r[4] = _mm_set_epi64x(0x4444444444444444ll, 0x100000000ll);
    ctx.r[5] = _mm_set_epi64x(0x5555555555555555ll, static_cast<int64_t>(0x8000000000000001ull));
    for (int reg = 8; reg <= 15; ++reg)
        ctx.r[reg] = _mm_set_epi64x(static_cast<int64_t>(0xabc0000000000000ull + reg), 0x100 + reg);
''' if args.move64 else '').replace('MOVE_CHECK', '''
    const uint64_t expected[] = {0x100000000ull, 0x100000000ull, 0x10a, 0x10b,
                                0, 0x8000000000000001ull, 0x10e, 0x10f};
    for (int reg = 8; reg <= 15; ++reg) {
        const uint64_t low = static_cast<uint64_t>(_mm_cvtsi128_si64(ctx.r[reg]));
        const uint64_t high = static_cast<uint64_t>(_mm_cvtsi128_si64(_mm_srli_si128(ctx.r[reg], 8)));
        movesOkay &= low == expected[reg - 8] && high == 0xabc0000000000000ull + reg;
    }
    movesOkay &= _mm_movemask_epi8(_mm_cmpeq_epi8(ctx.r[0], _mm_setzero_si128())) == 0xffff;
''' if args.move64 else ''), encoding='utf-8')
        if args.quad_align:
            (out / 'main.cpp').write_text('''#include "ps2_runtime.h"
#include "ps2_recompiled_functions.h"
#include <vector>
#include <iostream>
#include <cstdlib>
// Link guards: this probe must only touch ordinary RAM, never MMIO.
__m128i PS2Runtime::Load128(uint8_t*, R5900Context*, uint32_t) { std::abort(); }
void PS2Runtime::Store128(uint8_t*, R5900Context*, uint32_t, __m128i) { std::abort(); }
int main() {
    std::vector<uint8_t> ram(0x4000, 0xa5);
    for (unsigned i = 0; i < 16; ++i) ram[0x1010+i] = static_cast<uint8_t>(i*11+3);
    R5900Context ctx{};
    unsigned failures = 0;
    for (unsigned offset = 0; offset < 16; ++offset) {
        ctx.pc = 0x100000;
        ctx.r[31] = _mm_set_epi64x(0, 0x123456);
        ctx.r[4] = _mm_set_epi64x(0, 0x1018+offset);
        ctx.r[5] = _mm_set_epi64x(0, 0x3018+15-offset);
        FUN_00100000_0x100000(ram.data(), &ctx, nullptr);
        for (unsigned i = 0x3000; i < 0x3030; ++i) {
            const uint8_t expected = i >= 0x3010 && i < 0x3020
                ? static_cast<uint8_t>((i-0x3010)*11+3) : 0xa5;
            failures += ram[i] != expected;
            ram[i] = 0xa5;
        }
        failures += ctx.pc != 0x123456 || _mm_cvtsi128_si32(ctx.r[2]) != 17;
    }
    for (unsigned i = 0; i < ram.size(); ++i) {
        uint8_t expected = 0xa5;
        if (i >= 0x1010 && i < 0x1020) expected = static_cast<uint8_t>((i-0x1010)*11+3);
        if (i >= 0x2010 && i < 0x2210 && (i-0x2010)%32 < 16)
            expected = static_cast<uint8_t>(((i-0x2010)%32)*11+3);
        failures += ram[i] != expected;
    }
    std::cout << "constant_quad_cases=16 dynamic_quad_cases=16 failures=" << failures << std::endl;
    return failures == 0 && ctx.pc == 0x123456 && _mm_cvtsi128_si32(ctx.r[2]) == 17 ? 0 : 1;
}
''', encoding='utf-8')
        includes = [args.runtime_root / 'ps2xRuntime/include', args.runtime_root / 'ps2xRuntime/src/lib/Kernel',
                    args.runtime_root / 'ps2xIOP/include', generated]
        (out / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(EECanary LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
file(GLOB EE_SOURCES CONFIGURE_DEPENDS "generated/FUN_*.cpp")
add_executable(ee_canary main.cpp ${EE_SOURCES})
target_include_directories(ee_canary PRIVATE
''' + '\n'.join('  "' + p.as_posix() + '"' for p in includes) + ''')
if(NOT MSVC)
  target_compile_options(ee_canary PRIVATE -msse4.1)
endif()
''', encoding='utf-8')
        run('configure', ['cmake', '-S', str(out), '-B', str(out / 'build'), '-G', 'Ninja',
                          '-DCMAKE_BUILD_TYPE=Release',
                          *(['-DCMAKE_CXX_COMPILER=clang-cl'] if os.name == 'nt' else [])])
        run('build', ['cmake', '--build', str(out / 'build'), '--parallel', '2'])
        if args.tailcall:
            objects = list((out / 'build').rglob('FUN_*.cpp.obj')) + list((out / 'build').rglob('FUN_*.cpp.o'))
            if len(objects) < 2:
                raise RuntimeError('Direct-transfer probe must compile at least two generated function objects.')
            timestamps = {str(p): p.stat().st_mtime_ns for p in objects}
            header = generated / 'ps2_recompiled_functions.h'
            with header.open('a', encoding='utf-8') as stream:
                stream.write('\n// Incremental probe: a new unrelated function declaration.\n'
                             'void independent_map_probe(uint8_t*, R5900Context*, PS2Runtime*);\n')
            run('build-map-header-change', ['cmake', '--build', str(out / 'build'), '--parallel', '2'])
            if timestamps != {str(p): p.stat().st_mtime_ns for p in objects}:
                raise RuntimeError('Changing the global map header rebuilt independent function objects.')
            report['map_header_change_preserved_function_objects'] = True
        exe = out / 'build' / ('ee_canary.exe' if os.name == 'nt' else 'ee_canary')
        report['executable_sha256'] = hashlib.sha256(exe.read_bytes()).hexdigest()
        report['observed'] = run('execute', [str(exe)]).strip()
        report['passed'] = True
        if args.quad_align:
            print('PASS: generated LQ/SQ constant and dynamic addresses for all sixteen alignments; surrounding RAM preserved.')
        elif args.move64:
            print(f'PASS: {branch_cases} scalar conditional moves; upper halves preserved.')
        elif args.compare64:
            print(f'PASS: {branch_cases} low64 comparison probes; doubling loop exited after {expected_slots} steps.')
        elif args.branch64:
            print(f'PASS: generated EE arithmetic and delay slots; {branch_cases} low64 branch probes.')
        elif args.tailcall:
            print('PASS: direct transfer across generated files; map header change preserved function objects.')
        else:
            print('PASS: generated EE arithmetic and delay slots.')
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        report['error'] = str(exc)
        print(str(exc), file=sys.stderr)
    finally:
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

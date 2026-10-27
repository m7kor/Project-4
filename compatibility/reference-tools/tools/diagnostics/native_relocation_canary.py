"""Compile and execute the production emitter's relocated scalar operands.

The relative-PC mode also validates local control flow and re-entry at several
load bases. Neither mode validates module registration, imports, external J26
dispatch or RE4 playback.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from ps2l.build import _prepend_path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--relative-pc', action='store_true', help='execute the same bodies at three code load bases and resume after a local call')
    args = parser.parse_args()
    out = (args.out or ROOT / ('artifacts/canary-relative-module-pc' if args.relative_pc else 'artifacts/canary-runtime-relocation')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    _prepend_path()
    report = {'schema': 1, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Native variable-base operands, PC, local calls, branches, delay slots and resume' if args.relative_pc else __doc__,
              'game_compatibility': 'unverified', 'checks': [], 'passed': False}

    def run(name, command):
        started = time.monotonic()
        result = subprocess.run(command, cwd=out, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=180)
        (out / (name + '.stdout.txt')).write_text(result.stdout, encoding='utf-8')
        (out / (name + '.stderr.txt')).write_text(result.stderr, encoding='utf-8')
        report['checks'].append({'name': name, 'exit_code': result.returncode,
                                 'seconds': round(time.monotonic() - started, 3)})
        if result.returncode:
            raise RuntimeError(f'{name} failed; see {out}')
        return result.stdout

    try:
        generator = ROOT / 'core/out/build/ps2xTest/ps2x_relocation_codegen_probe.exe'
        if os.name != 'nt':
            generator = generator.with_suffix('')
        run('generate', [str(generator), str(out / 'generated.cpp'), *(['--relative-pc'] if args.relative_pc else [])])
        report['generated_sha256'] = hashlib.sha256((out / 'generated.cpp').read_bytes()).hexdigest()
        main_code = r'''#include "ps2_runtime.h"
#include <vector>
#include <iostream>
#include <cstring>
#include <cstdlib>
void native_relocation_operand_probe(uint8_t*, R5900Context*, PS2Runtime*);
// This probe must resolve only RAM; an accidental MMIO address fails loudly.
uint16_t PS2Runtime::Load16(uint8_t*, R5900Context*, uint32_t) { std::abort(); }
uint32_t PS2Runtime::Load32(uint8_t*, R5900Context*, uint32_t) { std::abort(); }
void PS2Runtime::Store32(uint8_t*, R5900Context*, uint32_t, uint32_t) { std::abort(); }
bool PS2Runtime::dispatchGuestBranch(uint8_t*, R5900Context*, uint32_t, uint32_t, uint32_t, GuestBranchKind, const char*) { std::abort(); }
int main() {
    std::vector<uint8_t> ram(32u*1024u*1024u);
    unsigned failures = 0;
    const uint32_t targets[] = {0x1138730u, 0x1207FF0u, 0x1280010u};
    auto put16 = [&](uint32_t at, uint16_t value) { std::memcpy(ram.data()+at, &value, 2); };
    auto put32 = [&](uint32_t at, uint32_t value) { std::memcpy(ram.data()+at, &value, 4); };
    auto get32 = [&](uint32_t at) { uint32_t v; std::memcpy(&v, ram.data()+at, 4); return v; };
    for (uint32_t target : targets) {
        std::fill(ram.begin(), ram.end(), 0);
        put16(0x1000, static_cast<uint16_t>((target+0x8000u)>>16));
        put16(0x1004, static_cast<uint16_t>(target));
        put16(0x1008, static_cast<uint16_t>(target+4));
        put16(0x100C, static_cast<uint16_t>(target+8));
        put16(0x1010, 0x8001u);
        put16(0x1014, 0x8001u);
        put16(0x1018, 0x8001u);
        put32(target, 0x80FFEE11u);
        R5900Context ctx{};
        ctx.pc = 0x1000;
        native_relocation_operand_probe(ram.data(), &ctx, nullptr);
        failures += ctx.pc != 0x101C;
        failures += static_cast<uint64_t>(_mm_cvtsi128_si64(ctx.r[2])) != 0xFFFFFFFF80FFEE11ull;
        failures += static_cast<uint32_t>(_mm_cvtsi128_si32(ctx.r[4])) != target+8;
        failures += _mm_cvtsi128_si64(ctx.r[5]) != 0x8001;
        failures += _mm_cvtsi128_si64(ctx.r[6]) != 0;
        failures += _mm_cvtsi128_si64(ctx.r[7]) != 1;
        failures += get32(target+4) != 0x80FFEE11u;
        failures += get32(target-4) != 0 || get32(target+8) != 0;
        failures += get32(0x3AF30) != 0;
    }
    std::cout << "operand_binding_cases=3 native_instructions=7 failures=" << failures << std::endl;
    return failures ? 1 : 0;
}
'''
        if args.relative_pc:
            main_code = main_code.replace('R5900Context*, PS2Runtime*);', 'R5900Context*, PS2Runtime*, uint32_t);')
            main_code = main_code.replace('int main() {', '''void native_relative_flow_probe(uint8_t*, R5900Context*, PS2Runtime*, uint32_t);
void native_relative_branch_probe(uint8_t*, R5900Context*, PS2Runtime*, uint32_t);
int main() {''')
            main_code = main_code.replace('for (uint32_t target : targets) {', '''unsigned caseIndex = 0;
    const uint32_t codeBases[] = {0x10FD800u, 0x100000u, 0x1A00000u};
    for (uint32_t target : targets) {
        const uint32_t codeBase = codeBases[caseIndex++];''')
            for offset in range(0, 0x1C, 4):
                main_code = main_code.replace(f'put16(0x{0x1000 + offset:X},', f'put16(codeBase+0x{offset:X},')
            main_code = main_code.replace('ctx.pc = 0x1000;', 'ctx.pc = codeBase;')
            main_code = main_code.replace('ctx.pc != 0x101C', 'ctx.pc != codeBase+0x1C')
            main_code = main_code.replace('native_relocation_operand_probe(ram.data(), &ctx, nullptr);',
                                          'native_relocation_operand_probe(ram.data(), &ctx, nullptr, codeBase);')
            main_code = main_code.replace('failures += get32(0x3AF30) != 0;', '''failures += get32(0x3AF30) != 0;
        ctx = R5900Context{};
        ctx.pc = codeBase;
        ctx.r[31] = _mm_set_epi64x(0, 0x12345670u);
        native_relative_flow_probe(ram.data(), &ctx, nullptr, codeBase);
        failures += ctx.pc != codeBase+0x10;
        failures += static_cast<uint32_t>(_mm_cvtsi128_si32(ctx.r[31])) != codeBase+0x10;
        failures += _mm_cvtsi128_si64(ctx.r[2]) != 36;
        if (ctx.pc == codeBase+0x10) {
            native_relative_flow_probe(ram.data(), &ctx, nullptr, codeBase);
            failures += ctx.pc != 0x12345670u || _mm_cvtsi128_si64(ctx.r[2]) != 41;
        }
        ctx = R5900Context{};
        ctx.pc = codeBase;
        ctx.r[31] = _mm_set_epi64x(0, 0x12345670u);
        native_relative_branch_probe(ram.data(), &ctx, nullptr, codeBase);
        failures += ctx.pc != 0x12345670u || _mm_cvtsi128_si64(ctx.r[2]) != 17;
        failures += ctx.in_delay_slot;''')
            main_code = main_code.replace('operand_binding_cases=3 native_instructions=7',
                                          'module_bases=3 operand_instructions=7 local_call_resume_cases=3 branch_delay_cases=3')
        (out / 'main.cpp').write_text(main_code, encoding='utf-8')
        includes = [ROOT / 'core/ps2xRuntime/include', ROOT / 'core/ps2xRuntime/src/lib/Kernel',
                    ROOT / 'core/ps2xIOP/include']
        cmake = '''cmake_minimum_required(VERSION 3.20)
project(RuntimeRelocationCanary LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
add_executable(relocation_canary main.cpp generated.cpp)
target_include_directories(relocation_canary PRIVATE
'''
        cmake += '\n'.join('  "' + path.as_posix() + '"' for path in includes)
        cmake += ''')
if(NOT MSVC)
  target_compile_options(relocation_canary PRIVATE -msse4.1)
endif()
'''
        (out / 'CMakeLists.txt').write_text(cmake, encoding='utf-8')
        run('configure', ['cmake', '-S', str(out), '-B', str(out / 'build'), '-G', 'Ninja',
                          '-DCMAKE_BUILD_TYPE=Release',
                          *(['-DCMAKE_CXX_COMPILER=clang-cl'] if os.name == 'nt' else [])])
        run('build', ['cmake', '--build', str(out / 'build'), '--parallel', '2'])
        exe = out / 'build' / ('relocation_canary.exe' if os.name == 'nt' else 'relocation_canary')
        report['executable_sha256'] = hashlib.sha256(exe.read_bytes()).hexdigest()
        report['observed'] = run('execute', [str(exe)]).strip()
        report['passed'] = True
        print(report['observed'])
    finally:
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

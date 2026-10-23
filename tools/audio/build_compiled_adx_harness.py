"""Build an isolated copy of the current generated ADX functions.

Preserves production arithmetic/register/memory macros. Replaces checkpoint
calls only, removes unused include/logging blocks, disables strict-return
dispatch. Does not edit generated sources or link the whole game.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def build(root, out, compiler):
    root, out = Path(root).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    provenance = []
    routes = []
    includes = []
    for address in ('19aeb0', '19aae8', '19b1f8', '189870', '189a60', '189c30', '2af3ac',
                    '18f758', '18f6c8', '18f698', '18f738', '1937c0',
                    '18b490', '18b4f0', '18b580', '18b598', '188970', '188988', '189be0',
                    '18f8e0', '1936c8', '1937a8', '1937d8', '1937c8', '18e9c8',
                    '192be0', '192c10', '18ac18', '189a10', '18f158', '18f478',
                    '18f480', '18f438', '18f0c0', '192758', '189810', '189f70', '18f0a8'):
        source = root / f'recomp/generated/SLUS_211.34/FUN_00{address.upper()}_0x{address}.cpp'
        data = source.read_bytes()
        text = data.decode('utf-8-sig')
        text = re.sub(r'^#include .*\n', '', text, flags=re.M)
        text = re.sub(r'#ifdef PS2_FUNCTION_LOG_TRACKER\s*.*?#endif', '', text, flags=re.S)
        count = text.count('runtime->eeCheckpointDue()')
        text = text.replace('runtime->eeCheckpointDue()', 'decoderCheckpointDue()')
        text = text.replace('runtime->dispatchGuestBranch(', 'decoderDispatchGuestBranch(')
        (out / f'decoder_{address}.inc').write_text(text, encoding='utf-8')
        bounds = re.search(r'// Address: 0x([0-9a-f]+) - 0x([0-9a-f]+)', text)
        if not bounds:
            raise ValueError(f'missing function bounds: {source}')
        start, end = bounds.groups()
        routes.append(f'if (ctx->pc >= 0x{start}u && ctx->pc < 0x{end}u) {{ FUN_00{address.upper()}_0x{address}(ram, ctx, nullptr); return; }}')
        includes.append(f'#include "decoder_{address}.inc"')
        provenance.append({'source': str(source), 'sha256': hashlib.sha256(data).hexdigest(), 'checkpoints_replaced': count})
    shutil.copyfile(root / 'tools/audio/compiled_adx_harness.cpp', out / 'harness.cpp')
    (out / 'decoder_routes.inc').write_text('\n'.join(includes) + '\nstatic void decoderDispatchFunction(uint8_t* ram, R5900Context* ctx) {\n' + '\n'.join(routes) + '\nthrow std::runtime_error("unsupported resume PC");\n}\n')
    command = [compiler, '/nologo', '/std:c++20', '/EHsc', '/O2', '-msse4.1',
               '/DPS2X_STRICT_RETURN_DIAGNOSTICS=0',
               '/I' + str(root / 'core/ps2xRuntime/include'), '/I' + str(root / 'core/ps2xIOP/include'),
               '/I' + str(root / 'core/deps/raylib/src'), 'harness.cpp', '/Fe:harness.exe']
    result = subprocess.run(command, cwd=out, capture_output=True, text=True)
    (out / 'build.log').write_text(result.stdout + result.stderr)
    (out / 'provenance.json').write_text(json.dumps({'sources': provenance, 'command': command, 'exit_code': result.returncode}, indent=2))
    if result.returncode:
        raise RuntimeError(f'compile failed; see {out / "build.log"}')
    return out / 'harness.exe'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--compiler', default='C:/Program Files/LLVM/bin/clang-cl.exe')
    args = parser.parse_args()
    print(build(Path(__file__).resolve().parents[2], args.out, args.compiler))

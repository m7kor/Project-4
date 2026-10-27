"""Run installed diagnostic tools with evidence gates and a single summary.

python -m tools.diagnostics.toolchain_check --snapshots SNAPSHOT_DIR --out NEW_DIR
--pcsx2 additionally probes MCP readiness; it does not require or boot a game.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def run_step(command, expected, key, logs, name, timeout=60):
    record = {'name': name, 'command': command, 'status': 'failed'}
    started = time.monotonic()
    try:
        if expected.exists():
            raise ValueError('Evidence already exists; refusing stale acceptance')
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=timeout)
        record['exit_code'] = process.returncode
        for suffix, contents in (('stdout', process.stdout), ('stderr', process.stderr)):
            with (logs / f'{name}.process.{suffix}.log').open('x', encoding='utf-8') as output:
                output.write(contents)
        if process.returncode:
            raise ValueError('Process failed; inspect captured logs')
        evidence = json.loads(expected.read_text(encoding='utf-8'))
        if not isinstance(evidence, dict) or evidence.get(key) is not True:
            raise ValueError(f'Acceptance field {key} missing or false')
        record.update(status='passed', evidence=str(expected.resolve()))
    except subprocess.TimeoutExpired as error:
        record['error'] = 'Timed out; no acceptance'
        for suffix, contents in (('stdout', error.stdout), ('stderr', error.stderr)):
            if isinstance(contents, bytes):
                contents = contents.decode('utf-8', errors='replace')
            with (logs / f'{name}.process.{suffix}.log').open('x', encoding='utf-8') as output:
                output.write(contents or '')
    except (OSError, ValueError) as error:
        record['error'] = str(error)
    record['host_seconds'] = time.monotonic() - started
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--snapshots', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New evidence directory')
    parser.add_argument('--limit', type=int, default=24)
    parser.add_argument('--pcsx2', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 4096:
        parser.error('limit must be 1..4096')
    args.out = args.out.resolve()
    args.snapshots = args.snapshots.resolve(strict=True)
    if not args.snapshots.is_dir():
        parser.error('snapshots must be a directory')
    args.out.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'Installed tool/replay readiness; not game speed or campaign acceptance',
              'accepted': False, 'game_frame_captured': False, 'full_game_lockstep_tested': False,
              'steps': [], 'identities': {}}
    bench = ROOT / 'core/out/build/ps2xTest/ps2x_vu1_bench.exe'
    renderdoc = ROOT / 'dependencies/tools/renderdoc-1.46/RenderDoc_1.46_64/renderdoc.dll'
    tracy = ROOT / 'dependencies/tools/tracy-0.14.1'
    mcp_python = ROOT / 'dependencies/GhidraMCP/.venv/Scripts/python.exe'
    assets = [bench, renderdoc, tracy / 'tracy-import-chrome.exe', tracy / 'tracy-csvexport.exe']
    assets += [Path(__file__).resolve(), *[ROOT / f'tools/diagnostics/{module}.py'
               for module in ('renderdoc_api_probe', 'vu1_mode_compare', 'tracy_roundtrip')]]
    if args.pcsx2:
        assets += [mcp_python, ROOT / 'tools/diagnostics/pcsx2_mcp_probe.py',
                   ROOT / 'tools/diagnostics/pcsx2_probe_schema.py',
                   ROOT / 'dependencies/PCSX2-MCP/pcsx2-mcp-server/dist/index.js']
    missing = [str(asset) for asset in assets if not asset.is_file()]
    if missing:
        report['missing_tools'] = missing
    else:
        for asset in assets:
            report['identities'][str(asset)] = hashlib.sha256(asset.read_bytes()).hexdigest()
        py = sys.executable
        def step(name, module, argv, expected, key, interpreter=py, timeout=60):
            result = run_step([str(interpreter), '-m', module, *argv], expected,
                              key, args.out, name, timeout)
            report['steps'].append(result)
            return result['status'] == 'passed'
        step('renderdoc', 'tools.diagnostics.renderdoc_api_probe',
             [str(renderdoc), '--out', str(args.out / 'renderdoc.json')],
             args.out / 'renderdoc.json', 'accepted')
        vu = args.out / 'vu1'
        vu_pass = step('vu1', 'tools.diagnostics.vu1_mode_compare',
                      [str(bench), str(args.snapshots), '--limit', str(args.limit), '--out', str(vu)],
                      vu / 'comparison.json', 'equivalent')
        if vu_pass:
            step('tracy', 'tools.diagnostics.tracy_roundtrip',
                 ['--trace', str(vu / 'subprocess-trace.json'),
                  '--importer', str(tracy / 'tracy-import-chrome.exe'),
                  '--exporter', str(tracy / 'tracy-csvexport.exe'), '--out', str(args.out / 'tracy')],
                 args.out / 'tracy/report.json', 'accepted', timeout=60)
        else:
            report['steps'].append({'name': 'tracy', 'status': 'skipped',
                                    'error': 'VU1 trace prerequisite failed'})
        if args.pcsx2:
            passed = step('pcsx2', 'tools.diagnostics.pcsx2_mcp_probe',
                          ['--out', str(args.out / 'pcsx2.json')], args.out / 'pcsx2.json',
                          'connection_attempt_valid', mcp_python, timeout=45)
            if passed:
                pcsx = json.loads((args.out / 'pcsx2.json').read_text(encoding='utf-8'))
                report['pcsx2_debugserver_connected'] = pcsx.get('debugserver_connected') is True
        report['identities_stable'] = all(asset.is_file() and
            report['identities'][str(asset)] == hashlib.sha256(asset.read_bytes()).hexdigest()
            for asset in assets)
        report['accepted'] = report['identities_stable'] and all(
            result['status'] == 'passed' for result in report['steps'])
    with (args.out / 'summary.json').open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({'accepted': report['accepted'], 'summary': str(args.out / 'summary.json'),
                      'steps': [{'name': item['name'], 'status': item['status']} for item in report['steps']],
                      'pcsx2_debugserver_connected': report.get('pcsx2_debugserver_connected'),
                      'game_frame_captured': False, 'full_game_lockstep_tested': False}))
    if not report['accepted']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

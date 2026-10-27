"""Import extracted Sony IOP ELF images into an isolated Ghidra project.

Records Ghidra's import identity and analysis output, not semantic correctness.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--java', type=Path, required=True)
    parser.add_argument('--ghidra', type=Path, required=True)
    parser.add_argument('--scripts', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    images = [row for row in json.loads(args.manifest.read_text(encoding='utf-8'))['images']
              if row['format'] == 'elf' and row['metadata']['type'] == 0xff80]
    if not images or args.out_dir.exists():
        parser.error('Need IOP images and a fresh output directory')
    for row in images:
        if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Extracted image identity changed')
    root = args.out_dir.resolve()
    root.mkdir(parents=True)
    reports = root / 'reports'
    reports.mkdir()
    env = dict(os.environ)
    env['JAVA_TOOL_OPTIONS'] = f'-Dapplication.settingsdir={root.as_posix()}/settings -Dapplication.cachedir={root.as_posix()}/cache'
    vmargs = subprocess.check_output([str(args.java.resolve()), '-cp',
        str(args.ghidra.resolve() / 'support/LaunchSupport.jar'), 'LaunchSupport',
        str(args.ghidra.resolve()), '-vmargs'], env=env, text=True, timeout=30).splitlines()
    command = [str(args.java.resolve()), *vmargs, '-Xmx2G', '-Djava.awt.headless=true',
        '-cp', str(args.ghidra.resolve() / 'Ghidra/Framework/Utility/lib/Utility.jar'),
        'ghidra.Ghidra', 'ghidra.app.util.headless.AnalyzeHeadless', str(root), 'iop-review']
    for row in images:
        command.extend(['-import', row['path']])
    command.extend(['-processor', 'MIPS:LE:32:default', '-max-cpu', '2',
        '-analysisTimeoutPerFile', '45', '-scriptPath', str(args.scripts.resolve()),
        '-postScript', 'BinaryCoverageReport.java', str(reports), '-log', str(root / 'ghidra.log')])
    started = time.monotonic()
    with (root / 'console.log').open('w', encoding='utf-8') as output:
        try:
            code = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                  env=env, timeout=600).returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
    result = {'exit_code': code, 'seconds': time.monotonic() - started, 'images': [],
              'scope': 'Import identity and analyzer counts; IOP relocations and semantics remain unverified.'}
    for row in images:
        report = reports / (Path(row['path']).name + '.txt')
        fields = {}
        if report.exists():
            for line in report.read_text(encoding='utf-8').splitlines():
                key, _, value = line.partition('=')
                if key != 'block':
                    fields[key] = value
        result['images'].append({'sha256': row['sha256'], 'report': str(report),
                                'identity_matches': fields.get('sha256') == row['sha256'],
                                'analysis_report': fields})
    result['identity_matched_reports'] = sum(row['identity_matches'] for row in result['images'])
    console = (root / 'console.log').read_text(encoding='utf-8', errors='replace')
    result['import_success_count'] = console.count('REPORT: Import succeeded')
    result['analysis_success_count'] = console.count('REPORT: Analysis succeeded')
    result['all_expected_analysis_reports'] = (result['identity_matched_reports'] == len(images)
        and result['import_success_count'] == len(images)
        and result['analysis_success_count'] == len(images)
        and all(row['analysis_report'].get('language') == 'MIPS:LE:32:default'
                for row in result['images']))
    (root / 'coverage.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'exit_code': code, 'identity_matched_reports': result['identity_matched_reports'],
                      'expected': len(images), 'seconds': result['seconds']}))
    if code != 0 or not result['all_expected_analysis_reports']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

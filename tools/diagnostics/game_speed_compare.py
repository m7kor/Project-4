"""Compare matching guest-field ranges, exposing sparse endpoint uncertainty."""
import argparse
import hashlib
import json
import re
from pathlib import Path
if __package__:
    from .game_speed_report import summarize
else:
    from game_speed_report import summarize

HZ = 60000 / 1001


def endpoint(rows, field):
    for before, after in zip(rows, rows[1:]):
        a, b = before['ee_vsync_tick'], after['ee_vsync_tick']
        if a <= field <= b and b > a:
            start, end = before['elapsed_seconds'], after['elapsed_seconds']
            if field == a:
                return start, [start, start]
            if field == b:
                return end, [end, end]
            return start + (end - start) * (field - a) / (b - a), [start, end]
    raise ValueError(f'Field {field} not bracketed by samples')


def measure(identity_path, first, last):
    identity = json.loads(identity_path.read_text(encoding='utf-8'))
    activity = identity.get('external_activity', [])
    if not isinstance(activity, list) or any(not isinstance(item, str) or not item.strip() for item in activity):
        raise ValueError('External activity must be a list of nonempty descriptions')
    if identity.get('fault_counts') or identity['user_card_before'] != identity['user_card_after']:
        raise ValueError('Run contains faults or changed original card')
    run = Path(identity['run'])
    validity = summarize(run)
    if validity['clock'] != 'monotonic' or validity['malformed_rows']:
        raise ValueError('Need valid monotonic timed samples')
    report = json.loads((run / 'report.json').read_text())
    state = run / 'diagnostics/state.jsonl'
    rows = [json.loads(line) for line in state.read_text().splitlines()]
    start, start_bounds = endpoint(rows, first)
    end, end_bounds = endpoint(rows, last)
    shortest, longest = end_bounds[0] - start_bounds[1], end_bounds[1] - start_bounds[0]
    if shortest <= 0:
        raise ValueError('Endpoint intervals overlap; need longer phase or denser samples')
    guest_seconds = (last - first) / HZ
    graphics_modes = set(map(int, re.findall(r'\(super-sampling x(\d+)\)', (run / 'stderr.txt').read_text(errors='replace'))))
    if len(graphics_modes) != 1:
        raise ValueError('Need one evidenced GPU supersampling mode from initialization')
    gs_ssaa = graphics_modes.pop()
    if gs_ssaa not in (1, 2, 4, 8, 16) or identity.get('gs_ssaa', gs_ssaa) != gs_ssaa:
        raise ValueError('Graphics setting disagrees with initialization or is unsupported')
    return {'run': str(run), 'runner_sha256': report['runner_sha256'],
            'elf_sha256': report['elf_sha256'], 'pad_sha256': identity['pad_sha256'],
            'state_sha256': hashlib.sha256(state.read_bytes()).hexdigest(),
            'capture_every_host_ticks': identity.get('capture_every_host_ticks'),
            'gs_ssaa': gs_ssaa,
            'instrumentation': {
                'external_activity': activity,
                'record_audio': bool(identity.get('audio_prefix')),
                'rpc_census': bool(identity.get('trace_rpc_census')),
                'gs_page_trace': bool(identity.get('trace_gs_pages')),
                'gif_capture_from': identity.get('gif_capture_from'),
                'gif_capture_count': identity.get('gif_capture_count'),
                'vif_direct_capture_from_ee': identity.get('vif_direct_capture_from_ee'),
                'vif_direct_capture_count': identity.get('vif_direct_capture_count'),
                'preserve_gif_continuations': identity.get('preserve_gif_continuations'),
                'call_snapshot_from': identity.get('snapshot_from'),
                'call_snapshot_fields': identity.get('snapshot_fields'),
                'vu1_snapshot_from': identity.get('vu1_snapshot_from_ee_vsync'),
                'vu1_code_capture': bool(identity.get('vu1_code_directory')),
                'trace_from': identity.get('trace_from'),
                'signal_from': identity.get('signal_from'),
                'pipeline_from': identity.get('pipeline_from')},
            'start_elapsed_bounds': start_bounds, 'end_elapsed_bounds': end_bounds,
            'estimated_wall_seconds': end - start, 'estimated_speed': guest_seconds / (end - start),
            'speed_bounds_from_sparse_endpoints': [guest_seconds / longest, guest_seconds / shortest]}


def validate_workload(baseline, candidate, allow_instrumentation_differences=False):
    for key in ('elf_sha256', 'pad_sha256', 'capture_every_host_ticks', 'gs_ssaa'):
        if baseline[key] != candidate[key] or baseline[key] is None:
            raise ValueError(f'Comparison mismatch or missing identity: {key}')
    if (baseline['instrumentation'] != candidate['instrumentation'] and
            not allow_instrumentation_differences):
        raise ValueError('Instrumentation differs; use explicit diagnostic comparison override')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True, help='Probe identity JSON')
    parser.add_argument('--candidate', type=Path, required=True, help='Probe identity JSON')
    parser.add_argument('--from-ee', type=int, required=True)
    parser.add_argument('--to-ee', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allow-instrumentation-differences', action='store_true',
                        help='Diagnostic estimate only; does not establish a controlled speed gain')
    args = parser.parse_args()
    if not 0 <= args.from_ee < args.to_ee or args.out.exists():
        parser.error('Need increasing field interval and new output path')
    baseline = measure(args.baseline, args.from_ee, args.to_ee)
    candidate = measure(args.candidate, args.from_ee, args.to_ee)
    validate_workload(baseline, candidate, args.allow_instrumentation_differences)
    low_b, high_b = baseline['speed_bounds_from_sparse_endpoints']
    low_c, high_c = candidate['speed_bounds_from_sparse_endpoints']
    result = {'scope': 'matching guest-field workload; sparse capture is not every-frame FPS or campaign coverage',
              'from_ee': args.from_ee, 'to_ee': args.to_ee, 'vsync_hz': HZ,
              'baseline': baseline, 'candidate': candidate,
              'estimated_relative_gain_percent': (candidate['estimated_speed'] / baseline['estimated_speed'] - 1) * 100,
              'relative_gain_bounds_percent': [(low_c / high_b - 1) * 100, (high_c / low_b - 1) * 100],
              'instrumentation_matches': baseline['instrumentation'] == candidate['instrumentation'],
              'controlled_performance_gain_proven': False,
              'natural_speed_proven': False}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

"""Follow bounded experimental waypoints using read-only poses and native pad input.

This is diagnostic navigation, not a game-state editor or campaign verifier.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time


def pose_from_sample(sample):
    if (not sample.get('player_pointer_stable')
            or sample.get('player_pointer') != sample.get('player_pointer_after')):
        raise ValueError('Unstable player identity')
    raw = bytes.fromhex(sample.get('player_bytes_hex') or '')
    if len(raw) < 0xd8:
        raise ValueError('Missing player pose')
    position = struct.unpack_from('<3f', raw, 0xc0)
    yaw = struct.unpack_from('<f', raw, 0xd4)[0]
    if not all(math.isfinite(v) for v in (*position, yaw)) or any(abs(v) > 1e7 for v in position):
        raise ValueError('Unusable player pose')
    room = sample['room_state']
    if not room.get('game_pointer_stable') or type(room.get('room_dispatch_argument_u16')) is not int:
        raise ValueError('Unstable room identity')
    return {'position': position, 'yaw': yaw, 'room': room['room_dispatch_argument_u16']}


def plan_step(pose, target, tolerance=400):
    x, _, z = pose['position']
    dx, dz = target['x'] - x, target['z'] - z
    distance = math.hypot(dx, dz)
    error = (math.atan2(dx, dz) - pose['yaw'] + math.pi) % (2 * math.pi) - math.pi
    degrees = math.degrees(error)
    result = {'distance': distance, 'heading_error_degrees': degrees, 'lx': 128, 'ly': 128}
    if distance <= tolerance:
        return dict(result, kind='arrived', duration=0)
    if abs(degrees) > 5:
        return dict(result, kind='turn', lx=0 if degrees > 0 else 255,
                    duration=min(45, max(2, math.ceil(abs(degrees) / 2.195) + 1)))
    return dict(result, kind='move', ly=0,
                duration=min(120, max(4, int((distance - tolerance) / 28))))


def validate_route(route):
    if not isinstance(route, dict) or type(route.get('schema')) is not int or route['schema'] != 1 or type(route.get('expected_room')) is not int or not 0 <= route['expected_room'] <= 65535:
        raise ValueError('Expected route schema1 and original room id')
    tolerance = route.get('tolerance', 400)
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 50 <= tolerance <= 1000:
        raise ValueError('Tolerance must be 50..1000 guest units')
    points = route.get('waypoints')
    if not isinstance(points, list) or not 1 <= len(points) <= 32:
        raise ValueError('Expected 1..32 explicit waypoints')
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get('evidence'), str) or not point['evidence']:
            raise ValueError('Every waypoint needs its evidence/assumption')
        for axis in ('x', 'z'):
            if type(point.get(axis)) not in (int, float) or not math.isfinite(point[axis]) or abs(point[axis]) > 1e7:
                raise ValueError('Invalid waypoint coordinate')
    return tolerance


def latest_state(run):
    with (run / 'diagnostics/state.jsonl').open('rb') as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - 65536))
        tail = stream.read(65536)
    for line in reversed(tail.splitlines()):
        try:
            state = json.loads(line)
            if type(state.get('ee_vsync_tick')) is int:
                return state
        except (ValueError, AttributeError):
            continue
    raise ValueError('No complete recent diagnostic state')


def wait_for_end(run, end, deadline):
    limit = min(deadline, time.monotonic() + 35)
    while time.monotonic() < limit:
        if (run / 'report.json').exists():
            return False
        if latest_state(run)['ee_vsync_tick'] >= end + 8:
            return True
        time.sleep(0.1)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--rdram-base', required=True)
    parser.add_argument('--room-exports', type=Path, required=True)
    parser.add_argument('--movie-witness', type=Path)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--max-commands', type=int, default=80)
    parser.add_argument('--label', default='feedback-route')
    args = parser.parse_args()
    if not args.label or not args.label.replace('-', '').isalnum() or len(args.label) > 64:
        parser.error('Use a simple output label of at most64 characters')
    if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 1800 or not 1 <= args.max_commands <= 80:
        parser.error('Use timeout1..1800 seconds and max-commands1..80')
    root = Path(__file__).resolve().parents[2]
    run = args.run.resolve(strict=True)
    run.relative_to(root / 'artifacts/runs')
    if run.parent.name != 'captures' or (run / 'report.json').exists():
        raise ValueError('Expected an unfinished owned diagnostic')
    owner = run.parents[1]
    identity = json.loads((owner / 'identity.json').read_text(encoding='utf-8'))
    destination = Path(identity['settings']['PS2X_NATIVE_PAD_LIVE'])
    if destination.resolve() != owner / 'live-pad.csv':
        raise ValueError('Unexpected native live input path')
    route_bytes = args.route.read_bytes()
    route = json.loads(route_bytes)
    tolerance = validate_route(route)
    out = owner / args.label
    out.mkdir(exist_ok=False)
    (out / 'route.json').write_bytes(route_bytes)
    lock = owner / 'feedback-active.json'
    with lock.open('x', encoding='utf-8') as stream:
        json.dump({'controller_pid': os.getpid(), 'run': str(run)}, stream)
    deadline = time.monotonic() + args.timeout
    result = {'scope': 'Experimental route through native input; no state writes or campaign completion claim',
              'route_sha256': hashlib.sha256(route_bytes).hexdigest(), 'pid': args.pid,
              'runner_sha256': identity['runner_sha256'], 'commands': [], 'status': 'incomplete'}
    index = snapshots = stalled = 0
    previous_move = None
    last_command = None
    journal = (out / 'observations.jsonl').open('x', encoding='utf-8')
    try:
        while index < len(route['waypoints']) and len(result['commands']) < args.max_commands and time.monotonic() < deadline:
            snapshot = out / f'snapshot-{snapshots:03d}.json'
            snapshots += 1
            memory_command = [sys.executable, str(root / 'tools/diagnostics/re4_live_memory.py'),
                '--pid', str(args.pid), '--run', str(run), '--rdram-base', args.rdram_base,
                '--room-exports', str(args.room_exports.resolve()), '--out', str(snapshot)]
            if args.movie_witness:
                memory_command += ['--movie-witness', str(args.movie_witness.resolve(strict=True))]
            memory = subprocess.run(memory_command,
                cwd=root, capture_output=True, text=True, timeout=min(20, max(0.1, deadline - time.monotonic())))
            if memory.returncode:
                (out / 'memory-error.txt').write_text(memory.stdout + memory.stderr, encoding='utf-8')
                result['status'] = 'memory_error'
                break
            sample = json.loads(snapshot.read_text(encoding='utf-8'))['observations'][-1]
            pose = pose_from_sample(sample)
            if pose['room'] != route['expected_room']:
                result.update(status='room_changed', observed_room=pose['room'])
                break
            if args.movie_witness:
                active = sample.get('movie_state', {}).get('game_movie_bit_10000000')
                if type(active) is not bool:
                    raise ValueError('Missing or unstable movie observation; refusing further input')
                if active:
                    # Scripted movies reposition the player and ignore walking.
                    # Do not classify those movements as collision failures.
                    previous_move = None
                    stalled = 0
                    result['movie_wait_samples'] = result.get('movie_wait_samples', 0) + 1
                    journal.write(json.dumps({'waypoint': index, 'pose': pose, 'plan': {'kind': 'wait_movie'}, 'snapshot': snapshot.name}) + '\n')
                    journal.flush()
                    time.sleep(min(0.25, max(0, deadline-time.monotonic())))
                    continue
            target = route['waypoints'][index]
            plan = plan_step(pose, target, tolerance)
            journal.write(json.dumps({'waypoint': index, 'pose': pose, 'plan': plan, 'snapshot': snapshot.name}) + '\n')
            journal.flush()
            if previous_move is not None:
                stalled = stalled + 1 if previous_move - plan['distance'] < 25 else 0
                previous_move = None
                if stalled >= 2:
                    result.update(status='stalled', waypoint=index, reason='Two forward commands failed to approach target; inspect pictures/path')
                    break
            if plan['kind'] == 'arrived':
                index += 1
                stalled = 0
                continue
            receipt = None
            for _ in range(2):
                if len(result['commands']) >= args.max_commands or time.monotonic() >= deadline:
                    break
                publication = subprocess.run([sys.executable, '-m', 'tools.diagnostics.live_pad_command',
                    '--run', str(run), '--duration', str(plan['duration']), '--delay', '40',
                    '--lx', str(plan['lx']), '--ly', str(plan['ly'])],
                    cwd=root, capture_output=True, text=True, timeout=min(10, max(0.1, deadline - time.monotonic())))
                try:
                    receipt = json.loads(publication.stdout)
                except ValueError:
                    (out / 'publisher-error.txt').write_text(publication.stdout + publication.stderr, encoding='utf-8')
                    raise RuntimeError('Publisher failed without a structured receipt')
                result['commands'].append(receipt)
                if receipt['status'] == 'accepted':
                    break
                if receipt['status'] != 'rejected' or 'reason=interval ' not in receipt.get('acknowledgement', ''):
                    break
            if receipt is None or receipt['status'] != 'accepted':
                result['status'] = 'command_rejected'
                break
            last_command = receipt['command']
            end = int(last_command.splitlines()[1].split(',')[2])
            if not wait_for_end(run, end, deadline):
                result['status'] = 'command_wait_ended'
                break
            if plan['kind'] == 'move':
                previous_move = plan['distance']
        else:
            result['status'] = 'route_reached' if index == len(route['waypoints']) else 'budget_ended'
        result['waypoints_reached'] = index
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result.update(status='error', error=str(exc))
    finally:
        journal.close()
        # Cancel only our own last publication; retain every receipt and snapshot.
        try:
            if last_command is not None and destination.read_text(encoding='utf-8') == last_command:
                destination.unlink()
        except OSError as exc:
            if not isinstance(exc, FileNotFoundError):
                result['cancel_error'] = str(exc)
        try:
            lock.unlink()
        except OSError as exc:
            result['lock_cleanup_error'] = str(exc)
        (out / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'commands'}))
    raise SystemExit(0 if result['status'] in ('route_reached', 'room_changed') else 1)


if __name__ == '__main__':
    main()

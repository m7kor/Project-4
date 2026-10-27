import copy
import math
import struct
import tempfile
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import unittest
from tools.diagnostics.re4_feedback_route import plan_step, pose_from_sample, validate_route, latest_state
from tools.diagnostics import re4_feedback_route as controller
from tools.diagnostics.live_pad_command import command_text


class FeedbackRouteTests(unittest.TestCase):
    def simulate(self, directory, mode='moving', max_commands=80):
        root = Path(directory)
        (root / 'tools/diagnostics').mkdir(parents=True)
        owner = root / 'artifacts/runs/simulation'
        run = owner / 'captures/capture'
        run.mkdir(parents=True)
        destination = owner / 'live-pad.csv'
        (owner / 'identity.json').write_text(json.dumps({'runner_sha256': 'test-only', 'settings': {'PS2X_NATIVE_PAD_LIVE': str(destination)}}))
        route = root / 'route.json'
        route.write_text(json.dumps({'schema': 1, 'expected_room': 256, 'waypoints': [
            {'x': 0, 'z': 1000, 'evidence': 'simulation'}, {'x': 1000, 'z': 1000, 'evidence': 'simulation'}]}))
        state = {'x': 0., 'z': 0., 'yaw': 0., 'sequence': 0, 'room': 256, 'movie_reads': 0}
        witness = root / 'movie.json'
        witness.write_text('{}')
        def tool_call(command, **kwargs):
            def arg(name): return command[command.index(name) + 1]
            if command[1].endswith('re4_live_memory.py'):
                raw = bytearray(512)
                struct.pack_into('<3f', raw, 0xc0, state['x'], 0, state['z'])
                struct.pack_into('<f', raw, 0xd4, state['yaw'])
                sample = {'player_pointer_stable': True, 'player_pointer': '0x4000', 'player_pointer_after': '0x4000',
                    'player_bytes_hex': raw.hex(), 'room_state': {'game_pointer_stable': True, 'room_dispatch_argument_u16': state['room']}}
                if mode in ('movie', 'movie_invalid'):
                    self.assertIn('--movie-witness', command)
                    active = state['sequence'] == 1 and state['movie_reads'] < 3
                    if active: state['movie_reads'] += 1
                    sample['movie_state'] = {'game_movie_bit_10000000': None if mode == 'movie_invalid' else active}
                Path(arg('--out')).write_text(json.dumps({'observations': [sample]}))
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            state['sequence'] += 1
            duration, lx, ly = int(arg('--duration')), int(arg('--lx')), int(arg('--ly'))
            text = command_text(state['sequence'], 100 * state['sequence'], 40, duration, 65535, [lx, ly, 128, 128])
            destination.write_text(text)
            if mode == 'moving' or (mode == 'movie' and state['sequence'] > 1):
                if lx == 0: state['yaw'] += math.radians(2 * duration)
                elif lx == 255: state['yaw'] -= math.radians(2 * duration)
                elif ly == 0:
                    state['x'] += math.sin(state['yaw']) * 20 * duration
                    state['z'] += math.cos(state['yaw']) * 20 * duration
            if mode == 'room_change': state['room'] = 257
            receipt = {'command': text, 'status': 'rejected' if mode == 'reject' else 'accepted',
                       'acknowledgement': '[pad live] rejected reason=interval ' if mode == 'reject' else '[pad live] accepted'}
            return SimpleNamespace(returncode=int(mode == 'reject'), stdout=json.dumps(receipt), stderr='')
        argv = ['controller', '--run', str(run), '--pid', '123', '--rdram-base', '0x100000',
                '--room-exports', str(root / 'room.json'), '--route', str(route), '--max-commands', str(max_commands)]
        if mode in ('movie', 'movie_invalid'):
            argv += ['--movie-witness', str(witness)]
        with patch.object(controller, '__file__', str(root / 'tools/diagnostics/re4_feedback_route.py')), \
                patch.object(controller.sys, 'argv', argv), patch.object(controller.subprocess, 'run', side_effect=tool_call), \
                patch.object(controller, 'wait_for_end', return_value=True):
            with self.assertRaises(SystemExit) as stopped:
                controller.main()
        result = json.loads((owner / 'feedback-route/summary.json').read_text())
        self.assertFalse((owner / 'feedback-active.json').exists())
        return result, stopped.exception.code, destination.exists()

    def test_simulated_route_executes_feedback_then_releases_own_command(self):
        with tempfile.TemporaryDirectory() as directory:
            result, code, exists = self.simulate(directory)
            self.assertEqual((result['status'], code), ('route_reached', 0))
            self.assertEqual(result['waypoints_reached'], 2)
            self.assertGreater(len(result['commands']), 2)
            self.assertFalse(exists)

    def test_movie_ignored_movement_waits_then_resumes_without_false_stall(self):
        with tempfile.TemporaryDirectory() as directory:
            result, code, exists = self.simulate(directory, 'movie')
            self.assertEqual((result['status'], code), ('route_reached', 0))
            self.assertEqual(result['movie_wait_samples'], 3)
            self.assertEqual(result['waypoints_reached'], 2)
            self.assertFalse(exists)

    def test_unstable_movie_evidence_stops_before_publishing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            result, code, _ = self.simulate(directory, 'movie_invalid')
            self.assertEqual((result['status'], code), ('error', 1))
            self.assertEqual(result['commands'], [])

    def test_stalled_route_and_room_change_stop_input(self):
        for mode, expected, code in [('stalled', 'stalled', 1), ('room_change', 'room_changed', 0)]:
            with tempfile.TemporaryDirectory() as directory:
                result, actual, exists = self.simulate(directory, mode)
                self.assertEqual((result['status'], actual), (expected, code))
                self.assertFalse(exists)
                self.assertLessEqual(len(result['commands']), 2)

    def test_retry_cannot_exceed_total_command_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            result, code, _ = self.simulate(directory, 'reject', 1)
            self.assertEqual(code, 1)
            self.assertEqual(len(result['commands']), 1)

    def test_heading_sign_wrap_and_bounded_input(self):
        pose = {'position': (0, 0, 0), 'yaw': 0}
        self.assertEqual(plan_step(pose, {'x': 1000, 'z': 0})['lx'], 0)
        self.assertEqual(plan_step(pose, {'x': -1000, 'z': 0})['lx'], 255)
        pose['yaw'] = math.radians(179)
        step = plan_step(pose, {'x': -100, 'z': -10000})
        self.assertEqual(step['kind'], 'move')  # Crosses the +/-pi boundary without a full spin.
        self.assertLessEqual(step['duration'], 120)
        self.assertEqual(plan_step(pose, {'x': 0, 'z': 10000})['duration'], 45)

    def test_arrival_ignores_ground_height_and_pose_feedback_corrects_underturn(self):
        pose = {'position': (0, 860, 0), 'yaw': 0}
        self.assertEqual(plan_step(pose, {'x': 100, 'z': 100})['kind'], 'arrived')
        target = {'x': 1000, 'z': 0}
        first = plan_step(pose, target)
        pose['yaw'] = math.radians(80)
        correction = plan_step(pose, target)
        self.assertEqual(correction['kind'], 'turn')
        self.assertLess(correction['duration'], first['duration'])
        pose['yaw'] = math.pi / 2
        self.assertEqual(plan_step(pose, target)['kind'], 'move')

    def test_bad_route_coordinates_and_unexplained_points_are_rejected(self):
        good = {'schema': 1, 'expected_room': 256, 'waypoints': [{'x': -80000, 'z': -32000, 'evidence': 'observed'}]}
        self.assertEqual(validate_route(good), 400)
        for key, value in [('expected_room', -1), ('tolerance', float('nan')), ('waypoints', [])]:
            bad = copy.deepcopy(good); bad[key] = value
            with self.assertRaises(ValueError): validate_route(bad)
        for key, value in [('x', float('inf')), ('z', True), ('evidence', '')]:
            bad = copy.deepcopy(good); bad['waypoints'][0][key] = value
            with self.assertRaises(ValueError): validate_route(bad)

    def test_snapshot_identity_and_nonfinite_pose_are_rejected(self):
        raw = bytearray(512)
        struct.pack_into('<3f', raw, 0xc0, 1, 2, 3)
        sample = {'player_pointer_stable': True, 'player_pointer': '0x4000', 'player_pointer_after': '0x4000',
                  'player_bytes_hex': raw.hex(), 'room_state': {'game_pointer_stable': True, 'room_dispatch_argument_u16': 256}}
        self.assertEqual(pose_from_sample(sample)['room'], 256)
        changed = dict(sample, player_pointer_after='0x5000')
        with self.assertRaises(ValueError): pose_from_sample(changed)
        struct.pack_into('<f', raw, 0xd4, float('nan'))
        with self.assertRaises(ValueError): pose_from_sample(dict(sample, player_bytes_hex=raw.hex()))

    def test_state_tail_ignores_partial_last_line(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory); (run / 'diagnostics').mkdir()
            (run / 'diagnostics/state.jsonl').write_text('{"ee_vsync_tick":100}\n{"ee_vsync_tick":', encoding='utf-8')
            self.assertEqual(latest_state(run)['ee_vsync_tick'], 100)


if __name__ == '__main__':
    unittest.main()

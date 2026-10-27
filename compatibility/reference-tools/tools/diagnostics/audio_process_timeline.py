"""Relate loopback callback delivery observations to native process lifetime.

This is an approximate listening aid, not a hardware audio clock or causal test.
Requires capture_speakers --timing and the process fields from ps2l run.
"""
import argparse
import json
from pathlib import Path
import re
import wave


def summarize(run_report, capture_log, recording):
    report = json.loads(Path(run_report).read_text(encoding='utf-8'))
    log = Path(capture_log).read_text(encoding='utf-8')
    matches = re.findall(r'Delivery timing: first_unix_ns=(\d+) last_unix_ns=(\d+) last_start_frame=(\d+) last_frames=(\d+)', log)
    saved = re.findall(r'Saved (\d+) frames .*Queue overflow=(\d+), null input=(\d+) frames', log)
    if len(matches) != 1 or len(saved) != 1:
        raise ValueError('Expected one completed recording with delivery timing')
    first, last, last_start, last_count = map(int, matches[0])
    frames, overflow, null = map(int, saved[0])
    if first <= 0 or last < first or overflow or null or last_start + last_count != frames:
        raise ValueError('Incomplete or invalid callback delivery evidence')
    with wave.open(str(recording), 'rb') as stream:
        rate = stream.getframerate()
        if stream.getnframes() != frames or stream.getnchannels() != 2 or stream.getsampwidth() != 2:
            raise ValueError('WAV header does not match the completed stereo recording')
        # Check actual payload too: a declared length alone is insufficient.
        actual = 0
        while payload := stream.readframes(65536):
            actual += len(payload)
        if actual != frames * 4:
            raise ValueError('WAV payload is truncated')
    keys = ['process_spawn_requested_unix_ns', 'process_start_observed_unix_ns', 'process_exit_observed_unix_ns']
    times = [report.get(k) for k in keys]
    if any(type(t) is not int or t <= 0 for t in times) or times != sorted(times):
        raise ValueError('Missing or invalid observed process lifetime')
    nominal = [(t - first) / 1e9 for t in times]
    return {
        'schema': 1, 'recording': str(Path(recording).resolve()),
        'sample_rate': rate, 'frames': frames, 'duration_seconds': frames / rate,
        'process_pid': report.get('process_pid'),
        'process_exit_forced': report.get('process_exit_forced'),
        'nominal_process_spawn_seconds_in_recording': nominal[0],
        'nominal_process_start_seconds_in_recording': nominal[1],
        'nominal_process_exit_seconds_in_recording': nominal[2],
        'first_callback_unix_ns': first, 'last_callback_unix_ns': last,
        'last_packet_start_frame': last_start, 'last_packet_frames': last_count,
        'endpoint_delivery_drift_seconds': (last - first) / 1e9 - last_start / rate,
        'scope': 'Callback delivery observations mapped by nominal sample rate; not exact endpoint sample times',
        'limitations': [
            'Backend buffering delays callback delivery relative to hardware playback.',
            'The first and last callback observations cannot bound intermediate packet jitter.',
            'System clock adjustments can affect Unix timestamps.',
            'Proximity to process exit does not prove that exit caused an audio event.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_report', type=Path)
    parser.add_argument('capture_log', type=Path)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.run_report, args.capture_log, args.recording)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

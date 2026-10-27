"""Objective quality report for recorded game audio (PS2X_AUDIO_WAV).

The runtime writes <prefix>-spu2.wav (raw SPU2 mix, emulation time) and
<prefix>-out.wav (what the speakers got, real time). Per window this reports
level, clipping, silence candidates and click candidates
(sample-to-sample jumps far above the local signal slope), so audio changes can
be judged without listening.

    python -I tools/diagnostics/audio_quality_report.py PREFIX-out.wav [--window 5]
"""
import argparse
import math
import wave

import numpy as np


def load(path):
    with wave.open(str(path), 'rb') as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 2:
            raise SystemExit('expected 16-bit stereo')
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').reshape(-1, 2)
    return rate, data.astype(np.float32)


def analyse(rate, x, window):
    if rate <= 0 or not math.isfinite(window) or window <= 0 or int(rate * window) < 1:
        raise ValueError('Need positive rate and a window containing at least one sample')
    step = int(rate * window)
    rows = []
    for start in range(0, len(x), step):
        stereo = x[start:start + step]
        if len(stereo) < rate // 10:
            break
        rms = float(np.sqrt(np.mean(stereo ** 2)))
        peak = float(np.abs(stereo).max())
        clipped = int(np.count_nonzero(np.abs(stereo) >= 32700))
        # Dropouts: runs of >= 10 ms near silence while the window has sound.
        # Preserve both channels: averaging antiphase stereo can fabricate
        # silence even though each headphone channel contains sound.
        quiet = np.max(np.abs(stereo), axis=1) < 40
        gaps, gap_ms = 0, 0.0
        if rms > 300:
            edges = np.diff(np.concatenate(([0], quiet.astype(np.int8), [0])))
            starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
            lengths = ends - starts
            long_runs = lengths[lengths >= rate // 100]
            gaps, gap_ms = len(long_runs), float(long_runs.sum()) * 1000.0 / rate
        # Clicks: first difference far beyond the local typical slope.
        d = np.max(np.abs(np.diff(stereo, axis=0)), axis=1)
        if len(d):
            width = min(256, len(d))
            typical = np.convolve(d, np.ones(width) / width, mode='same') + 1.0
            clicks = int(np.count_nonzero((d > 12 * typical) & (d > 2000)))
        else:
            clicks = 0
        rows.append((start / rate, rms, peak, clipped, gaps, gap_ms, clicks))
    return rows


def measured_seconds(rows, total_frames, rate, window):
    return sum(min(window, max(0.0, total_frames / rate - row[0])) for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('wav')
    parser.add_argument('--window', type=float, default=5.0, help='seconds per row')
    args = parser.parse_args()
    rate, x = load(args.wav)
    rows = analyse(rate, x, args.window)
    print(f'{args.wav}: {len(x) / rate:.1f} s at {rate} Hz')
    print('   time    rms   peak  clipped  silence_candidates(ms)  click_candidates')
    for t, rms, peak, clipped, gaps, gap_ms, clicks in rows:
        print(f'{t:7.1f} {rms:6.0f} {peak:6.0f} {clipped:8d}  {gaps:4d} ({gap_ms:6.0f})  {clicks:6d}')
    sound = [r for r in rows if r[1] > 300]
    if sound:
        total = measured_seconds(sound, len(x), rate, args.window)
        print(f'above-threshold windows: {total:.3f} s, silence candidates {sum(r[5] for r in sound) / total / 10:.1f}% of time, '
              f'click candidates/min {sum(r[6] for r in sound) / total * 60:.1f}, clipped samples {sum(r[3] for r in sound)}')
    print('Silence and click candidates can include intentional game audio; they are not proven playback defects.')


if __name__ == '__main__':
    main()

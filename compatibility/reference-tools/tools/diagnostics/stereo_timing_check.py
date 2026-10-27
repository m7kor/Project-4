"""Measure a common stereo signal's lag; report candidates, never auto-shift audio.

Motivated by Urban Reign's documented opening-video channel timing issue.
Independent stereo effects need not match and cannot prove a timing defect.
"""
import argparse
import json
from pathlib import Path
import wave
import numpy as np


def measure(samples, rate, maximum_ms=250):
    step = max(1, rate // 4000)
    data = samples[::step].astype(np.float64)
    data -= data.mean(axis=0)
    n = len(data)
    rms = np.sqrt(np.mean(data * data, axis=0))
    if n < 8 or np.min(rms) < 3:
        return {'usable': False, 'reason': 'quiet or insufficient samples'}
    bound = min(n // 4, int(maximum_ms * rate / step / 1000))
    lags = np.arange(-bound, bound + 1)
    length = 1 << (2 * n - 1).bit_length()
    dots = np.fft.irfft(np.fft.rfft(data[:, 1], length) * np.conj(np.fft.rfft(data[:, 0], length)), length)[lags % length]
    left, right = (np.r_[0., np.cumsum(data[:, c] ** 2)] for c in (0, 1))
    left_energy = left[n - np.maximum(lags, 0)] - left[np.maximum(-lags, 0)]
    right_energy = right[n - np.maximum(-lags, 0)] - right[np.maximum(lags, 0)]
    correlation = dots / np.maximum(np.sqrt(left_energy * right_energy), 1e-12)
    best = int(np.argmax(correlation))
    peak, zero = float(correlation[best]), float(correlation[bound])
    lag_ms = float(lags[best] * step / rate * 1000)
    return {'usable': True, 'right_delay_ms': lag_ms, 'peak_correlation': peak,
            'zero_lag_correlation': zero,
            'timing_candidate': peak >= .92 and peak - zero >= .08 and abs(lag_ms) >= 2,
            'common_signal_confident': peak >= .92}


def selftest():
    rng = np.random.default_rng(431)
    mono = rng.normal(0, 2000, 96000)
    delay = 8208  # 171 ms at 48 kHz.
    shifted = np.r_[np.zeros(delay), mono[:-delay]]
    aligned = measure(np.column_stack((mono, mono)), 48000)
    delayed = measure(np.column_stack((mono, shifted)), 48000)
    advanced = measure(np.column_stack((shifted, mono)), 48000)
    separate = measure(np.column_stack((mono, rng.normal(0, 2000, len(mono)))), 48000)
    quiet = measure(np.zeros((96000, 2)), 48000)
    assert aligned['right_delay_ms'] == 0 and not aligned['timing_candidate']
    assert delayed['timing_candidate'] and abs(delayed['right_delay_ms'] - 171) < .26
    assert advanced['timing_candidate'] and abs(advanced['right_delay_ms'] + 171) < .26
    assert not separate['common_signal_confident'] and not separate['timing_candidate']
    assert not quiet['usable']
    return {'passed': True, 'cases': ['aligned', 'right-delayed-171ms', 'right-advanced-171ms', 'independent-stereo', 'silence']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav', type=Path, nargs='?')
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Existing reports are preserved')
    if args.selftest:
        result = selftest()
    else:
        if args.wav is None:
            parser.error('Supply a WAV or --selftest')
        rows = []
        with wave.open(str(args.wav), 'rb') as audio:
            if audio.getnchannels() != 2 or audio.getsampwidth() != 2 or audio.getcomptype() != 'NONE':
                parser.error('Expected uncompressed 16-bit stereo WAV')
            rate, frame = audio.getframerate(), 0
            while payload := audio.readframes(rate * 5):
                samples = np.frombuffer(payload, dtype='<i2').reshape(-1, 2)
                row = measure(samples, rate)
                rows.append(dict(start_seconds=frame / rate, **row))
                frame += len(samples)
        result = {'schema': 1, 'wav': str(args.wav.resolve()), 'frames': frame, 'rate': rate,
                  'scope': 'common-signal stereo timing; candidates are not proof of a game defect',
                  'positive_delay_means': 'right channel follows left',
                  'candidate_windows': sum(r.get('timing_candidate', False) for r in rows), 'windows': rows}
    args.out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'windows'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

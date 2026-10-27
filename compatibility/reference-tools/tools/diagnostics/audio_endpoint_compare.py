"""Find corresponding PCM windows in internal output and speaker loopback.

Coarse RMS-envelope search followed by stereo PCM alignment. This verifies
sample correspondence at selected windows, not sound quality or game timing.
Both files must use the same sample rate; no tempo/pitch correction is applied.
"""
import argparse
import json
from pathlib import Path
import wave

import numpy as np


def read(path):
    with wave.open(str(path), 'rb') as stream:
        if stream.getnchannels() != 2 or stream.getsampwidth() != 2 or stream.getcomptype() != 'NONE':
            raise ValueError('Expected uncompressed 16-bit stereo WAV')
        rate, frames = stream.getframerate(), stream.getnframes()
        payload = stream.readframes(frames)
        if len(payload) != frames * 4:
            raise ValueError('Truncated declared WAV payload')
        return np.frombuffer(payload, '<i2').reshape(-1, 2), rate


def correlate_valid(source, target):
    if len(source) < len(target):
        raise ValueError('Search is shorter than the target')
    size = 1 << (len(source) + len(target) - 2).bit_length()
    convolution = np.fft.irfft(np.fft.rfft(source, size) * np.fft.rfft(target[::-1], size), size)
    return convolution[len(target) - 1:len(source)]


def normalized_search(source, target):
    # Each channel is centered independently; common gain is estimated later.
    if source.ndim == 1:
        source, target = source[:, None], target[:, None]
    score = np.zeros(len(source) - len(target) + 1)
    energy = np.zeros_like(score)
    target_energy = 0.0
    for channel in range(source.shape[1]):
        x = source[:, channel].astype(np.float64)
        y = target[:, channel].astype(np.float64)
        y -= np.mean(y)
        target_energy += float(y @ y)
        score += correlate_valid(x, y)
        total = np.concatenate(([0.0], np.cumsum(x)))
        squares = np.concatenate(([0.0], np.cumsum(x * x)))
        sums = total[len(y):] - total[:-len(y)]
        energy += np.maximum(0, squares[len(y):] - squares[:-len(y)] - sums * sums / len(y))
    if target_energy <= 1e-10:
        return None
    denominator = np.sqrt(energy * target_energy)
    correlations = np.divide(score, denominator, out=np.full_like(score, -1), where=denominator > 1e-8)
    index = int(np.argmax(correlations))
    return index, float(np.clip(correlations[index], -1, 1))


def envelope(pcm, block):
    count = len(pcm) // block
    return np.sqrt(np.mean(pcm[:count * block].astype(np.float64).reshape(count, block, 2) ** 2, axis=1))


def channel_mix_fit(source, target):
    x, y = source.astype(np.float64), target.astype(np.float64)
    x -= x.mean(axis=0)
    y -= y.mean(axis=0)
    coefficients, _, rank, singular = np.linalg.lstsq(x, y, rcond=None)
    total = float(np.sum(y * y))
    residual = y - x @ coefficients
    ratio = float(singular[-1] / singular[0]) if singular[0] else 0.0
    return {'source_to_heard_matrix': coefficients.tolist(), 'rank': int(rank),
            'channel_mix_identifiable': rank == 2 and ratio >= .05,
            'singular_value_ratio': ratio,
            'residual_rms_fraction': float(np.sqrt(np.sum(residual * residual) / total)) if total else None,
            'scope': 'Diagnostic linear channel fit only; does not establish cause or authorize channel correction.'}


def timeline_recheck(internal, heard, rate, rows):
    # Repeated ambience can win the global envelope search at the wrong time.
    # Require independent strong PCM anchors spanning ten seconds before using
    # a common recording offset. Keep the original global results unchanged.
    anchors = [row for row in rows if row.get('usable') and row.get('pcm_correlation', 0) >= .95]
    clusters = []
    for anchor in anchors:
        cluster = [row for row in anchors if abs(row['internal_start_offset_seconds'] -
                                                anchor['internal_start_offset_seconds']) <= .005]
        span = max(row['heard_seconds'] for row in cluster) - min(row['heard_seconds'] for row in cluster)
        if len({row['heard_seconds'] for row in cluster}) >= 2 and span >= 10:
            offset = float(np.median([row['internal_start_offset_seconds'] for row in cluster]))
            if not any(abs(offset - existing[1]) <= .005 for existing in clusters):
                clusters.append((len(cluster), offset, cluster))
    clusters.sort(key=lambda group: group[0], reverse=True)
    if not clusters or (len(clusters) > 1 and clusters[0][0] == clusters[1][0]):
        return {'established': False, 'reason': 'insufficient or competing independent PCM anchors', 'windows': []}
    _, offset_seconds, selected = clusters[0]
    verified = []
    for row in rows:
        seconds = row['heard_seconds']
        start = int(seconds * rate)
        target = heard[start:start + rate // 2]
        predicted = int(round((seconds + offset_seconds) * rate))
        low, high = max(0, predicted - rate // 50), min(len(internal), predicted + len(target) + rate // 50)
        if high - low < len(target):
            verified.append({'heard_seconds': seconds, 'usable': False, 'reason': 'outside recorded internal payload'})
            continue
        fine = normalized_search(internal[low:high], target)
        if fine is None:
            verified.append({'heard_seconds': seconds, 'usable': False, 'reason': 'silent PCM'})
            continue
        match_start = low + fine[0]
        verified.append({'heard_seconds': seconds, 'usable': True, 'internal_seconds': match_start / rate,
                         'pcm_correlation': fine[1], 'offset_residual_seconds': match_start / rate - seconds - offset_seconds,
                         'channel_mix_fit': channel_mix_fit(internal[match_start:match_start + len(target)], target),
                         'correspondence_candidate': fine[1] >= .90})
    # The anchors themselves must still match in the local check.
    by_time = {row['heard_seconds']: row for row in verified}
    established = all(by_time[row['heard_seconds']].get('correspondence_candidate', False) for row in selected)
    return {'established': established, 'start_offset_seconds': offset_seconds,
            'anchor_heard_seconds': [row['heard_seconds'] for row in selected],
            'offset_cluster_tolerance_seconds': .005, 'search_radius_seconds': .02,
            'windows': verified, 'candidate_windows': sum(row.get('correspondence_candidate', False) for row in verified),
            'scope': 'PCM at a common recording offset; no time stretch, drift correction or quality acceptance.'}


def compare(internal, heard, rate, starts):
    if rate < 1000:
        raise ValueError('Sample rate must be at least 1000 Hz')
    block = max(1, rate // 1000)
    source_envelope = envelope(internal, block)
    heard_envelope = envelope(heard, block)
    rows = []
    for seconds in starts:
        start = int(seconds * rate)
        if start < 0 or start + rate * 2 > len(heard):
            raise ValueError('Each listening window needs two seconds within the WAV')
        target_start = start // block
        coarse = normalized_search(source_envelope, heard_envelope[target_start:target_start + rate * 2 // block])
        if coarse is None:
            rows.append({'heard_seconds': seconds, 'usable': False, 'reason': 'constant or silent envelope'})
            continue
        center = coarse[0] * block + start % block
        low, high = max(0, center - rate // 10), min(len(internal), center + rate // 2 + rate // 10)
        target = heard[start:start + rate // 2]
        fine = normalized_search(internal[low:high], target)
        if fine is None:
            rows.append({'heard_seconds': seconds, 'usable': False, 'reason': 'silent PCM'})
            continue
        offset, correlation = fine
        match_start = low + offset
        matched = internal[match_start:match_start + len(target)].astype(np.float64)
        observed = target.astype(np.float64)
        energy = float(np.sum(matched * matched))
        gain = float(np.sum(matched * observed) / energy) if energy else 0
        residual = observed - gain * matched
        heard_energy = float(np.sum(observed * observed))
        rows.append({'heard_seconds': seconds, 'usable': True,
                     'internal_seconds': match_start / rate,
                     'internal_start_offset_seconds': match_start / rate - start / rate,
                     'envelope_correlation': coarse[1], 'pcm_correlation': correlation,
                     'gain': gain,
                     'residual_rms_fraction': float(np.sqrt(np.sum(residual * residual) / heard_energy)) if heard_energy else None,
                     'correspondence_candidate': correlation >= 0.90 and coarse[1] >= 0.80})
    return {'scope': __doc__.strip(), 'sample_rate': rate, 'pcm_window_seconds': .5,
            'windows': rows, 'candidate_windows': sum(r.get('correspondence_candidate', False) for r in rows),
            'timeline_recheck': timeline_recheck(internal, heard, rate, rows),
            'limits': ['Alignment candidates require review; repeated sounds can have several possible matches.',
                       'Device resampling, effects and other applications can reduce correspondence.',
                       'Selected half-second windows do not prove that the whole recording matches.',
                       'WAV declared payload only; forced-termination tails are not reconstructed.']}


def selftest():
    rate = 48000
    rng = np.random.default_rng(23829)
    pcm = rng.normal(0, 1800, (rate * 8, 2))
    levels = rng.uniform(.1, 1, (800, 1))
    pcm *= np.repeat(levels, 480, axis=0)
    pcm = pcm.astype(np.int16)
    offset = 59213
    heard = (pcm[offset:offset + rate * 5].astype(np.float64) * .7).astype(np.int16)
    result = compare(pcm, heard, rate, [0, 1, 2])
    assert result['candidate_windows'] == 3
    for row in result['windows']:
        assert abs(row['internal_start_offset_seconds'] * rate - offset) <= 1
        assert row['pcm_correlation'] > .999 and abs(row['gain'] - .7) < .002
    unrelated = rng.normal(0, 1500, heard.shape).astype(np.int16)
    negative = compare(pcm, unrelated, rate, [0, 1, 2])
    assert negative['candidate_windows'] == 0
    # A deliberately wrong global middle match models ambiguous ambience.
    # Two independent byte-correlated anchors must recover it locally.
    long_pcm = rng.normal(0, 1800, (rate * 18, 2)).astype(np.int16)
    long_heard = (long_pcm[offset:offset + rate * 14].astype(np.float64) * .7).astype(np.int16)
    coarse_rows = [{'heard_seconds': seconds, 'usable': True, 'pcm_correlation': .999 if seconds != 5 else .2,
                    'internal_start_offset_seconds': offset / rate if seconds != 5 else 4.0} for seconds in (0, 5, 10)]
    recovered = timeline_recheck(long_pcm, long_heard, rate, coarse_rows)
    assert recovered['established'] and recovered['candidate_windows'] == 3
    assert max(abs(row['offset_residual_seconds']) for row in recovered['windows']) <= 1 / rate
    wrong_audio = rng.normal(0, 1800, long_heard.shape).astype(np.int16)
    rejected = timeline_recheck(long_pcm, wrong_audio, rate, coarse_rows)
    assert not rejected['established'] and rejected['candidate_windows'] == 0
    assert not timeline_recheck(long_pcm, long_heard, rate, coarse_rows[:1])['established']
    competing = coarse_rows + [{'heard_seconds': seconds, 'usable': True, 'pcm_correlation': .999,
                               'internal_start_offset_seconds': 4.0} for seconds in (1, 11)]
    assert not timeline_recheck(long_pcm, long_heard, rate, competing)['established']
    probe = long_pcm[:rate]
    swapped = (probe[:, ::-1].astype(np.float64) * .7).astype(np.int16)
    mixing = channel_mix_fit(probe, swapped)
    assert mixing['channel_mix_identifiable'] and mixing['residual_rms_fraction'] < .001
    assert np.max(np.abs(np.asarray(mixing['source_to_heard_matrix']) - np.array([[0, .7], [.7, 0]]))) < .001
    centered = np.repeat(probe[:, :1], 2, axis=1)
    assert not channel_mix_fit(centered, centered)['channel_mix_identifiable']
    return {'passed': True, 'positive_windows': 3, 'negative_windows': 3, 'offset_frames': offset,
            'timeline_cases': ['ambiguous-middle-recovered', 'unrelated-rejected', 'single-anchor-rejected', 'competing-anchors-rejected'],
            'mix_cases': ['known-channel-swap-recovered', 'centered-mono-unidentifiable']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('internal', type=Path, nargs='?')
    parser.add_argument('heard', type=Path, nargs='?')
    parser.add_argument('--starts', type=float, nargs='+', default=[5, 20, 40, 60, 80])
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Preserve previous reports')
    if args.selftest:
        result = selftest()
    else:
        if args.internal is None or args.heard is None:
            parser.error('Supply internal output and loopback WAVs')
        internal, rate = read(args.internal)
        heard, heard_rate = read(args.heard)
        if rate != heard_rate:
            parser.error('Sample rates must match; implicit resampling is not allowed')
        result = compare(internal, heard, rate, args.starts)
        result.update(internal=str(args.internal.resolve()), heard=str(args.heard.resolve()))
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

"""Inspect PS2X_AUDIO_WAV recordings, independently in their own time bases.

python tools/diagnostics/audio_check.py PREFIX --run CAPTURE --out REPORT.json
Also accepts one 16-bit stereo WAV. Silence/click candidates are measurements,
not proof of a bug: menus and game sounds can legitimately contain both.
"""
import argparse
from collections import Counter
import html
import json
import math
import os
from pathlib import Path
import re
import wave
from urllib.parse import quote

import numpy as np


def regions(mask, minimum):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [(int(a), int(b)) for a, b in zip(starts, ends) if b - a >= minimum]


def inspect(path, window=5.0, compensate_gain=True):
    if not math.isfinite(window) or window <= 0:
        raise ValueError('window must be finite and positive')
    windows, events = [], []
    total_frames = sound_frames = gap_frames = clipped = clicks = 0
    leading_quiet = 0
    found_sound = False
    channel_sum = np.zeros(2)
    channel_squared = np.zeros(2)
    cross_sum = side_squared = 0.0
    audible_frames = identical_audible_frames = 0
    with wave.open(str(path), 'rb') as stream:
        rate = stream.getframerate()
        if stream.getsampwidth() != 2 or stream.getnchannels() != 2 or stream.getcomptype() != 'NONE':
            raise ValueError('expected uncompressed 16-bit stereo WAV')
        step = max(1, int(rate * window))
        declared = stream.getnframes()
        recording_peak = 0
        if compensate_gain:
            while payload := stream.readframes(65536):
                samples = np.frombuffer(payload, dtype='<i2').astype(np.int32)
                if len(samples):
                    recording_peak = max(recording_peak, int(np.abs(samples).max()))
            stream.rewind()
        # A low Windows app volume must not make the fixed step floor blind.
        # Compensate only the click analysis, cap gain to avoid amplifying tiny
        # quantization noise, and retain original levels/clip tests/WAV bytes.
        click_gain = min(32.0, max(1.0, 10000.0 / max(recording_peak, 1))) if compensate_gain else 1.0
        while payload := stream.readframes(step):
            if len(payload) % 4:
                raise ValueError('truncated stereo frame')
            x = np.frombuffer(payload, dtype='<i2').reshape(-1, 2).astype(np.float64)
            count = len(x)
            rms = float(np.sqrt(np.mean(x * x)))
            peak = int(np.abs(x).max())
            clip = int(np.count_nonzero(np.abs(x) >= 32700))
            # Both channels must be quiet. Averaging stereo would incorrectly
            # classify opposite-phase audio as silence.
            quiet = np.max(np.abs(x), axis=1) < 40
            channel_sum += x.sum(axis=0)
            channel_squared += (x * x).sum(axis=0)
            cross_sum += float(np.sum(x[:, 0] * x[:, 1]))
            side_squared += float(np.sum(((x[:, 0] - x[:, 1]) * .5) ** 2))
            audible_frames += int(np.count_nonzero(~quiet))
            identical_audible_frames += int(np.count_nonzero((~quiet) & (x[:, 0] == x[:, 1])))
            audible = np.flatnonzero(~quiet)
            if not found_sound:
                leading_quiet += int(audible[0]) if len(audible) else count
                found_sound = bool(len(audible))
            gaps = regions(quiet, max(1, math.ceil(rate * .01))) if rms > 300 else []
            local_gaps = sum(b - a for a, b in gaps)
            for a, b in gaps:
                events.append({'kind': 'silence_candidate', 'start_seconds': (total_frames + a) / rate,
                               'duration_ms': (b - a) * 1000 / rate})
            d = np.max(np.abs(np.diff(x, axis=0)), axis=1) * click_gain
            if len(d):
                width = min(256, len(d))
                typical = np.convolve(d, np.ones(width) / width, mode='same') + 1
                candidates = (d > 12 * typical) & (d > 2000)
                # A discontinuity can span several samples: count clusters.
                click_regions = regions(candidates, 1)
                for a, b in click_regions:
                    events.append({'kind': 'click_candidate', 'start_seconds': (total_frames + a + 1) / rate,
                                   'peak_step': int(d[a:b].max())})
            else:
                click_regions = []
            windows.append({'start_seconds': total_frames / rate, 'duration_seconds': count / rate,
                            'rms': round(rms, 2), 'peak': peak, 'clipped_samples': clip,
                            'silence_candidates': len(gaps), 'silence_ms': local_gaps * 1000 / rate,
                            'click_candidates': len(click_regions)})
            if rms > 300:
                sound_frames += count
                gap_frames += local_gaps
            total_frames += count
            clipped += clip
            clicks += len(click_regions)
    if not total_frames:
        raise ValueError('empty WAV')
    variance = np.maximum(0, channel_squared - channel_sum * channel_sum / total_frames)
    divisor = float(np.sqrt(variance[0] * variance[1]))
    correlation = float(np.clip((cross_sum - channel_sum[0] * channel_sum[1] / total_frames) / divisor, -1, 1)) if divisor else None
    click_events = [event for event in events if event['kind'] == 'click_candidate']
    phases = Counter(round(event['start_seconds'] * rate) % 256 for event in click_events)
    return {'path': str(Path(path).resolve()), 'sample_rate': rate,
            'declared_frames': declared, 'read_frames': total_frames,
            'truncated': total_frames < declared, 'duration_seconds': total_frames / rate,
            'leading_quiet_seconds': leading_quiet / rate,
            'digital_silence': all(w['peak'] == 0 for w in windows),
            'audible_frames': audible_frames,
            'click_analysis_gain': click_gain,
            'audible_window_seconds': sound_frames / rate,
            'silence_analysis_rms_floor': 300,
            'silence_analysis_available': sound_frames > 0,
            'silence_percent_in_audible_windows': gap_frames * 100 / sound_frames if sound_frames else None,
            'clipped_samples': clipped, 'click_candidates': clicks,
            'click_phase_256': {'top_phases': [{'phase': p, 'count': c} for p, c in phases.most_common(4)],
                                'top_two_percent': sum(c for _, c in phases.most_common(2)) * 100 / clicks if clicks else None,
                                'note': 'Concentration at fixed phases can reveal block-boundary errors in raw PS2 audio. It does not locate the responsible code; stretching changes phase.'},
            'stereo': {'channel_rms': np.sqrt(channel_squared / total_frames).tolist(),
                       'channel_correlation': correlation,
                       'side_rms': math.sqrt(side_squared / total_frames),
                       'identical_channels_percent_of_audible_frames': identical_audible_frames * 100 / audible_frames if audible_frames else None,
                       'note': 'Centered dialogue can legitimately be identical on both channels; this does not prove unwanted duplication or echo.'},
            'windows': windows, 'events': events,
            'limits': 'Window-based candidates; runs crossing window boundaries may be split. '
                      'Natural silence and sharp sounds can trigger candidates. WAV time is local to each recording.'}


def audio_log(path):
    samples = []
    pattern = re.compile(r'\[audio\] requested=(\d+) delivered=(\d+) underrun=(\d+) tempo=([0-9.eE+-]+)')
    with Path(path).open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            match = pattern.search(line)
            if match:
                requested, delivered, underrun = map(int, match.group(1, 2, 3))
                samples.append({'output_seconds': requested / 48000, 'requested_frames': requested,
                                'delivered_frames': delivered, 'underrun_frames': underrun,
                                'tempo': float(match[4])})
    return {'samples': samples,
            'underrun_growth_after_first_sample': samples[-1]['underrun_frames'] - samples[0]['underrun_frames'] if samples else None}


def check(source, window=5.0, run=None, compensate_gain=True):
    source = Path(source)
    paths = {'single': source} if source.suffix.lower() == '.wav' else {
        'spu2': Path(str(source) + '-spu2.wav'), 'output': Path(str(source) + '-out.wav')}
    report = {'schema': 1, 'recordings': {key: inspect(path, window, compensate_gain) for key, path in paths.items()}}
    report['audible_evidence_available'] = all(r['audible_frames'] > 0 for r in report['recordings'].values())
    if run:
        report['host_audio'] = audio_log(Path(run) / 'stderr.txt')
        # Import only when a run is supplied; preserve the speed tool's clock
        # distinction instead of inferring gameplay speed from WAV durations.
        if __package__:
            from . import game_speed_report
        else:
            import game_speed_report
        report['emulation_speed'] = game_speed_report.summarize(Path(run))
    report['interpretation'] = [
        'SPU2 WAV uses emulation time; output WAV uses speaker time. Event timestamps cannot be directly paired.',
        'Growing host underrun counts show missing output frames; a stable count indicates no new buffer starvation in the logged interval.',
        'Slow emulation and tempo below 1 prolong sounds. Fixing playback gaps does not restore gameplay speed.',
        'Click and silence candidates require listening or a matching scene reference before calling them defects.']
    return report


def render_html(report, destination):
    sections = []
    titles = {'spu2': 'الصوت الخام من SPU2', 'output': 'الصوت المرسل للسماعات', 'single': 'تسجيل الصوت'}
    for key, result in report['recordings'].items():
        silent_notice = ('<p>التسجيل صامت بالكامل؛ لا يصلح للحكم على سلامة أصوات اللعبة. افحص الكتم ومخرج الصوت.</p>'
                         if result.get('digital_silence') else '')
        if not result.get('digital_silence') and result.get('audible_window_seconds') == 0:
            silent_notice += ('<p>التسجيل يحتوي صوتًا، لكن مستوى المقاطع لم يتجاوز عتبة تحليل الصمت. '
                             'نسبة الصمت غير متاحة؛ هذا لا يعني أن التسجيل صامت.</p>')
        gain_notice = (f"<p>عُوّض انخفاض الشدة في تحليل النقرات بمعامل {result.get('click_analysis_gain', 1):.2f}.</p>"
                       if not result.get('digital_silence') and result.get('click_analysis_gain', 1) > 1.01 else '')
        try:
            relative = quote(os.path.relpath(result['path'], Path(destination).resolve().parent).replace('\\', '/'), safe='/:')
        except ValueError:  # Windows recordings can be on another drive.
            relative = Path(result['path']).as_uri()
        rows = ''.join(f"<tr><td>{w['start_seconds']:.2f}</td><td>{w['duration_seconds']:.2f}</td>"
                       f"<td>{w['rms']:.0f}</td><td>{w['peak']}</td><td>{w['clipped_samples']}</td>"
                       f"<td>{w['silence_ms']:.1f}</td><td>{w['click_candidates']}</td></tr>" for w in result['windows'])
        events = ''.join(f"<li><button data-audio='{key}' data-time='{max(0, e['start_seconds'] - .5):.3f}'>"
                         f"استمع عند {e['start_seconds']:.3f} ثانية</button> — "
                         f"{'صمت مرشح ' + format(e['duration_ms'], '.1f') + ' ms' if e['kind'] == 'silence_candidate' else 'نقرة مرشحة'}</li>"
                         for e in result['events'][:200])
        sections.append(f"<section><h2>{titles[key]}</h2>{silent_notice}{gain_notice}<p>المدة {result['duration_seconds']:.2f} ثانية؛ "
                        f"النقرات المرشحة {result['click_candidates']}؛ العينات المقصوصة {result['clipped_samples']}.</p>"
                        f"<audio id='{key}' controls preload='none' src='{html.escape(relative, quote=True)}'></audio>"
                        f"<p>التوقيت خاص بهذا التسجيل. الصمت والأصوات الحادة قد تكون طبيعية؛ استمع قبل الحكم. "
                        f"ترابط القناتين: {result['stereo']['channel_correlation']}. وجود الحوار في القناتين قد يكون طبيعيًا.</p>"
                        f"<details><summary>مواضع الاشتباه ({len(result['events'])}، يعرض أول 200)</summary><ul>{events}</ul></details>"
                        f"<div class='scroll'><table><thead><tr><th>البداية s</th><th>المدة s</th><th>RMS</th><th>الذروة</th>"
                        f"<th>عينات القص</th><th>الصمت المرشح ms</th><th>النقرات</th></tr></thead><tbody>{rows}</tbody></table></div></section>")
    host = report.get('host_audio', {})
    speed = report.get('emulation_speed', {}).get('overall', {}).get('wall_speed')
    context = ''
    if host.get('samples'):
        context += f"<p>زيادة نقص الخرج بعد أول عينة: {host['underrun_growth_after_first_sample']} إطار صوتي. "
        context += 'سرعة التمديد في آخر عينة: ' + format(host['samples'][-1]['tempo'], '.3f') + '.</p>'
    if speed is not None:
        context += f'<p>سرعة المحاكاة المقيسة بزمن حقيقي بين عينات التشغيل: {speed:.3f}×.</p>'
    return """<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>فحص صوت اللعبة</title>
<style>body{background:#101923;color:#e7edf5;font:16px system-ui;margin:24px auto;padding:0 20px;max-width:1100px}
section{background:#1c2938;padding:20px;margin:20px 0;border-radius:12px}h1,h2{color:#8dc8ff}audio{width:100%}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:10px;border-bottom:1px solid #445466;text-align:right}
.scroll{overflow:auto}button{background:#b8dcff;color:#102030;border:0;border-radius:6px;padding:8px;cursor:pointer}li{margin:10px 0}</style>
<h1>فحص صوت اللعبة</h1><p>الخام يتبع زمن المحاكاة، والخرج يتبع زمن السماعات. لا تقارن توقيتيهما مباشرةً.
بطء اللعبة يطيل الصوت عند استخدام التمديد؛ هذا التقرير يقيس الأعراض ولا يثبت السبب وحده.</p>""" + context + ''.join(sections) + """
<script>document.querySelectorAll('button[data-audio]').forEach(button=>button.addEventListener('click',()=>{
const player=document.getElementById(button.dataset.audio);player.currentTime=Number(button.dataset.time);player.play().catch(()=>{});
}));</script></html>"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='PS2X_AUDIO_WAV prefix or a single WAV')
    parser.add_argument('--window', type=float, default=5)
    parser.add_argument('--run', type=Path, help='capture directory with stderr.txt and diagnostics')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--recorded-level', action='store_true', help='Use the original fixed click floor without compensating low app volume')
    args = parser.parse_args(argv)
    if args.out.suffix.lower() != '.json':
        parser.exit(2, '--out must use a .json extension to preserve both reports\n')
    try:
        report = check(args.source, args.window, args.run, not args.recorded_level)
    except (OSError, ValueError, wave.Error, EOFError) as error:
        parser.exit(2, f'audio check failed: {error}\n')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    html_path = args.out.with_suffix('.html')
    html_path.write_text(render_html(report, html_path), encoding='utf-8')
    for key, result in report['recordings'].items():
        gaps = result['silence_percent_in_audible_windows']
        unavailable = ('digital silence' if result['digital_silence'] else
                       'unavailable: no windows above analysis RMS floor 300; PCM is nonzero')
        print(f"{key}: {result['duration_seconds']:.2f}s, clicks={result['click_candidates']}, "
              f"clipped={result['clipped_samples']}, silence-in-sound={gaps if gaps is not None else unavailable}")
    if 'host_audio' in report:
        print('new underrun frames after first log:', report['host_audio']['underrun_growth_after_first_sample'])
    print('Report:', args.out)
    print('Listening report:', html_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

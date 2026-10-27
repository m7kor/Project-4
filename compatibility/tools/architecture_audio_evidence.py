"""Summarize existing host-audio counters without treating WAV equality as AV sync."""
from pathlib import Path
import hashlib
import json
import re
import wave

ROOT = Path(__file__).resolve().parents[1]


def main():
    run = ROOT / 'artifacts/runs/architecture-input-clock-01'
    out = ROOT / 'artifacts/architecture/audio-01'
    out.mkdir(exist_ok=False)
    text = (run / 'stderr.txt').read_text(errors='replace')
    pattern = r'\[audio\] requested=(\d+) delivered=(\d+) underrun=(\d+) tempo=([\d.]+) peak=(\d+)'
    rows = [dict(zip(('requested', 'delivered', 'underrun', 'tempo', 'peak'),
                    (int(a), int(b), int(c), float(d), int(e))))
            for a, b, c, d, e in re.findall(pattern, text)]
    assert rows and all(r['requested'] == r['delivered'] + r['underrun'] for r in rows)
    assert all(a['requested'] <= b['requested'] and a['underrun'] <= b['underrun']
               for a, b in zip(rows, rows[1:]))
    last_change = next(i for i in range(len(rows)-1, -1, -1)
                       if i == 0 or rows[i]['underrun'] > rows[i-1]['underrun'])
    wavs = {}
    for name in ('audio-out.wav', 'audio-spu2.wav'):
        path = run / 'diagnostics' / name
        with wave.open(str(path), 'rb') as wav:
            wavs[name] = {'frames': wav.getnframes(), 'rate': wav.getframerate(),
                          'seconds': wav.getnframes() / wav.getframerate(),
                          'channels': wav.getnchannels(), 'sample_bytes': wav.getsampwidth()}
        wavs[name]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'passed': True, 'samples': rows, 'last_counter': rows[-1],
              'last_underrun_growth_at_requested': rows[last_change]['requested'],
              'subsequent_requests_without_underrun_growth': rows[-1]['requested'] - rows[last_change]['requested'],
              'wav_files': wavs,
              'scope': 'Host audio requested/delivered cumulative counters and recorded PCM metadata; silence is not automatically an underrun',
              'unavailable': ['Exact SPU2-to-host event timeline', 'Speaker loopback', 'AV synchronization error', 'Independent scheduling-versus-decoder attribution'],
              'buffer_changes': False}
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ('samples', 'wav_files')}, indent=2))


if __name__ == '__main__':
    main()

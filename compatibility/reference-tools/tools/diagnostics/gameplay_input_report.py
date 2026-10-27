"""Map controlled input events to real captured frames by guest vsync.

Pixel differences and delivered buttons do not establish playability. The
report deliberately leaves movement/combat/saving for visual/state review.
"""
import argparse
import csv
import html
import json
from pathlib import Path


def nearest_frame(states, directory, guest_tick, tolerance=150, minimum=None, maximum=None):
    candidates = [s for s in states if s.get('host_frame') and
                  (minimum is None or s['ee_vsync_tick'] >= minimum) and
                  (maximum is None or s['ee_vsync_tick'] <= maximum) and
                  (directory / f"frame-{s['tick']}.png").is_file()]
    if not candidates:
        return None
    state = min(candidates, key=lambda s: abs(s['ee_vsync_tick'] - guest_tick))
    delta = state['ee_vsync_tick'] - guest_tick
    if abs(delta) > tolerance:
        return None
    return {'requested_guest_tick': guest_tick,
            'snapshot_guest_tick': state['ee_vsync_tick'],
            'snapshot_host_tick': state['tick'],
            'presentation_guest_tick': state.get('presentation_vsync_tick'),
            'guest_tick_difference': delta,
            'elapsed_seconds': state['elapsed_seconds'],
            'frame': str(directory / f"frame-{state['tick']}.png")}


def check(run, tape, out, min_tick=20000):
    out = out.resolve()
    if out.suffix != '.json':
        raise ValueError('Use a .json output')
    page = out.with_suffix('.html')
    if out.exists() or page.exists():
        raise FileExistsError('Preserve existing report evidence')
    directory = run.resolve() / 'diagnostics'
    states = [json.loads(line) for line in (directory / 'state.jsonl').read_text().splitlines() if line.strip()]
    if not states:
        raise ValueError('No guest state captured')
    with tape.open(newline='') as source:
        events = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(source)]
    rows = []
    for event in events:
        rows.append({'input': event,
                     'before': nearest_frame(states, directory, event['begin'] - 1, maximum=event['begin']-1),
                     'during': nearest_frame(states, directory, (event['begin'] + event['end']) // 2,
                                             minimum=event['begin'], maximum=event['end']-1),
                     'after': nearest_frame(states, directory, event['end'] + 60, minimum=event['end'])})
    result = {'scope': 'Guest tick alignment for visual review, not automatic gameplay success',
              'movement_verified': False, 'combat_verified': False, 'saving_verified': False,
              'last_guest_tick': max(s['ee_vsync_tick'] for s in states),
              'run': str(run.resolve()), 'tape': str(tape.resolve()), 'events': rows}
    with out.open('x', encoding='utf-8') as dest:
        json.dump(result, dest, ensure_ascii=False, indent=2)
    content = ['<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">',
               '<title>فحص استجابة اللعب</title><style>body{font:18px system-ui;background:#14191f;color:#eee;margin:24px}figure{display:inline-block;width:30%;vertical-align:top;margin:1%}img{width:100%}section{border-top:1px solid #555;padding:20px 0}a{color:#9dd6ff}</style>',
               '<h1>فحص استجابة اللعب</h1><p>الصور مرتبطة بعداد اللعبة الفعلي. وصول الأزرار أو تغيّر الصورة لا يثبت وحده حركة الشخصية أو القتال أو نجاح الحفظ.</p>']
    for row in rows:
        event = row['input']
        if event['begin'] < min_tick:
            continue
        content.append(f"<section><h2>الإدخال عند {event['begin']}–{event['end']}</h2><p>الأزرار: {event['buttons']:#06x}، العصا اليسرى: {event['lx']}/{event['ly']}</p>")
        for key, label in [('before', 'قبل الإدخال'), ('during', 'أثناء الإدخال'), ('after', 'بعد الإدخال')]:
            frame = row[key]
            if frame is None:
                content.append(f'<figure>{label}: لا توجد صورة قريبة كفاية.</figure>')
            else:
                from os.path import relpath
                path = Path(relpath(frame['frame'], page.parent)).as_posix()
                content.append(f'<figure><img src="{html.escape(path, quote=True)}"><figcaption>{label} — عداد اللعبة {frame["snapshot_guest_tick"]}، فرق {frame["guest_tick_difference"]}</figcaption></figure>')
        content.append('</section>')
    content.append('</html>')
    with page.open('x', encoding='utf-8') as dest:
        dest.write(''.join(content))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('tape', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--min-tick', type=int, default=20000, help='First input tick shown in the visual report')
    args = parser.parse_args()
    result = check(args.run, args.tape, args.out, args.min_tick)
    print(f"Aligned {len(result['events'])} events; gameplay still requires review.")


if __name__ == '__main__':
    main()

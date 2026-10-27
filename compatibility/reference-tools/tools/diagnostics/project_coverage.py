"""Build an evidence-backed status view; manual green labels never suffice."""
from pathlib import Path
import argparse
import hashlib
import html
import json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'docs/status/re4_evidence.json')
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new output directory; previous evidence is preserved')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    items, errors = [], []
    for item in manifest['items']:
        row = dict(item)
        row['checked_evidence'] = []
        state = row['state']
        if state not in ('verified', 'incomplete', 'unverified'):
            errors.append(f'Unknown state: {row["name"]}')
        proofs = row.get('evidence', [])
        failures = []
        if state == 'verified' and not proofs:
            failures.append('No evidence for verified claim')
        for proof in proofs:
            path = (ROOT / proof['path']).resolve()
            if not path.is_relative_to(ROOT) or not proof.get('checks'):
                failures.append('Evidence must be inside the project and have explicit checks')
                continue
            try:
                raw = path.read_bytes()
                data = json.loads(raw)
                for field, rule in proof['checks'].items():
                    value = data
                    for key in field.split('.'):
                        value = value[key]
                    if set(rule) == {'eq'}:
                        good = type(value) is type(rule['eq']) and value == rule['eq']
                    elif set(rule) == {'gte'}:
                        good = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= rule['gte']
                    else:
                        good = False
                    if not good:
                        failures.append(f'{proof["path"]}: {field} failed its criterion')
                row['checked_evidence'].append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
            except (OSError, ValueError, KeyError, TypeError) as error:
                failures.append(f'{proof["path"]}: {error}')
        if failures:
            row['state'] = 'unverified'
            row['evidence_errors'] = failures
            errors.extend(failures)
        items.append(row)
    verified = sum(row['state'] == 'verified' for row in items)
    result = {'schema': 1, 'scope': 'named requirements and stated test scopes; no full hardware percentage',
              'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
              'verified_items': verified, 'total_items': len(items),
              'all_requirements_verified': bool(items) and verified == len(items) and not errors,
              'evidence_valid': not errors, 'errors': errors, 'items': items}
    args.out.mkdir(parents=True)
    (args.out / 'coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    labels = {'verified': 'ثبت في نطاق الاختبار المذكور', 'incomplete': 'غير مكتمل', 'unverified': 'غير مثبت'}
    cards = []
    for row in items:
        links = ' · '.join(f'<a href="{Path(p["path"]).as_uri()}">دليل الاختبار</a>' for p in row['checked_evidence'])
        cards.append(f'<article class="{row["state"]}"><h2>{html.escape(row["name"])}</h2>'
                     f'<strong>{labels[row["state"]]}</strong><p>{html.escape(row["scope"])}</p>'
                     f'<p>{html.escape(row.get("reason", ""))}</p>{links}</article>')
    page = '<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>تغطية التحقق</title>' \
           '<style>body{font:18px system-ui;background:#111820;color:#eee;margin:40px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}article{border:2px solid #7c8794;padding:20px;border-radius:12px}.verified{border-color:#3caf72}.incomplete{border-color:#e8a64b}h2{font-size:21px}a{color:#89c9ff}p{line-height:1.6}</style>' \
           f'<h1>{html.escape(manifest["title"])}</h1><p>{verified} من {len(items)} بنود ثبتت في نطاقها المحدد. كل بند يوضح حدود الدليل.</p>' \
           '<p>هذا التقرير لا يعلن اكتمال اللعبة؛ المتطلبات غير المكتملة أو غير المثبتة تظل ظاهرة.</p><main>' + ''.join(cards) + '</main></html>'
    (args.out / 'coverage.html').write_text(page, encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('verified_items', 'total_items', 'all_requirements_verified', 'evidence_valid', 'errors')}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())

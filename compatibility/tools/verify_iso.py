from pathlib import Path
import json,hashlib,difflib
ROOT=Path(__file__).resolve().parents[1]
d=json.loads((ROOT/'artifacts/discovery/discovery.json').read_text())
game=Path('C:/Project/PS2redmption/game')
image=next(game.glob('*.iso'))
known={Path(r['file']).relative_to(game/'Resident Evil 4 (USA)').as_posix().lower():r['sha256'] for r in d['files']}
rows=[]
with image.open('rb') as f:
    for r in d['images'][0]['files']:
        if r['directory']:continue
        name=r['path'].lower()
        if name not in known:continue
        f.seek(r['lba']*2048);h=hashlib.sha256();remaining=r['size']
        while remaining:
            b=f.read(min(8*1024*1024,remaining));assert b
            h.update(b);remaining-=len(b)
        rows.append(dict(path=r['path'],lba=r['lba'],bytes=r['size'],sha256=h.hexdigest(),matches_extracted=h.hexdigest()==known[name]))
        print(r['path'],rows[-1]['matches_extracted'],flush=True)
(ROOT/'artifacts/discovery/iso-file-verification.json').write_text(json.dumps(rows,indent=2))
patch=[]
for name in json.loads((ROOT/'artifacts/gif-integration.json').read_text())['files']:
    a=(ROOT/'artifacts/gif-before'/name).read_text().splitlines(keepends=True)
    b=(ROOT/'engines/project4/ps2xRuntime/src/lib'/name).read_text().splitlines(keepends=True)
    patch.extend(difflib.unified_diff(a,b,fromfile='a/ps2xRuntime/src/lib/'+name,tofile='b/ps2xRuntime/src/lib/'+name))
(ROOT/'reports/GIF_IMAGE2_INTEGRATION.patch').write_text(''.join(patch))
assert len(rows)==8 and all(r['matches_extracted'] for r in rows)

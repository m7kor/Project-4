from pathlib import Path
import shutil,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
source=Path('C:/Project/PS2redmption/artifacts/verification')
out=ROOT/'artifacts/navigation-inputs';out.mkdir(exist_ok=True)
files={
 'player-exports.json':source/'pad-transport-20261018/original-player-key-exports.json',
 'room-exports.json':source/'room-map-20261018/original-room-exports.json',
 'movie-witness.json':source/'house-movie-20261019/original-ps2-witness.json',
}
manifest=[]
for name,path in files.items():
    assert path.is_file(),path
    shutil.copy2(path,out/name)
    manifest.append(dict(file=name,source=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
route=json.loads((source/'room-map-20261018/house-route-v1.json').read_text())
points=[p for p in route['waypoints'] if p['name'] in ('hall-centre','west-passage','beyond-partition')]
points.append(dict(name='approach-original-actor-area',x=-78900,z=-36500,evidence='Experimental approach toward original actor(-77630,860,-36500); no assumption that the straight line is passable; bounded stall stop applies'))
route.update(scope='Experimental house navigation after known startup tape; geometry is not yet verified; stop on two stalled moves or room change',waypoints=points)
(out/'house-route.json').write_text(json.dumps(route,indent=2))
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('Pinned three existing observation witnesses and four bounded experimental waypoints')

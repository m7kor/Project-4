"""Read-only bounded VU fixture inventory, not a claim of replay execution."""
from pathlib import Path
import collections,hashlib,json,struct,subprocess
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('C:/Project/PS2redmption/artifacts')
paths=set()
for folder in (SOURCE/'verification').glob('review-*-vu1'):
    paths.update(folder.glob('vu1snap*.bin'))
listing=subprocess.run(['rg','--files',str(SOURCE/'research'),'-g','vu1snap*.bin'],capture_output=True,text=True,check=True)
paths.update(Path(line) for line in listing.stdout.splitlines())
valid=[];invalid=[];images=collections.Counter()
for path in sorted(paths):
    data=path.read_bytes()
    if len(data)<40:invalid.append({'path':str(path),'reason':'short header'});continue
    magic,version,pc,top,itop,state,code,memory,vsync=struct.unpack_from('<8IQ',data)
    if magic!=0x53315556 or version!=1 or code!=16384 or memory!=16384 or len(data)!=40+state+code+memory:
        invalid.append({'path':str(path),'reason':'invalid header or length'});continue
    image=data[40+state:40+state+code];identity=0xcbf29ce484222325
    for byte in image:identity=((identity^byte)*0x100000001b3)&0xffffffffffffffff
    key=f'{identity:016x}';images[key]+=1
    valid.append({'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'image':key,'state_bytes':state,'pc':pc,'vsync':vsync})
report={'scope':'Fixture existence/header/length/hash validation only, NOT execution of all snapshots',
    'valid':valid,'invalid':invalid,'counts':dict(images)}
(ROOT/'artifacts/phase4/vu-fixture-inventory.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'valid':len(valid),'invalid':len(invalid),'images':dict(images)}))

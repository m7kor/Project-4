"""Index existing VU snapshots only; retain bounded private fixtures for new aliases."""
from pathlib import Path
import json,struct,collections,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
source=Path('C:/Project/PS2redmption/artifacts/verification')
out=ROOT/'artifacts/experiments/vu-shared-regions'
targets=set(json.loads((out/'proof.json').read_text())['aliases'])
counts=collections.Counter();selected=collections.defaultdict(list);seen=set()
research=source.parent/'research'
listing=subprocess.run(['rg','--files',str(research),'-g','vu1snap*.bin'],capture_output=True,text=True,check=True)
folders=set(source.glob('review-*-vu1')) | {Path(p).parent for p in listing.stdout.splitlines()}
for folder in sorted(folders):
    if not folder.is_dir():continue
    for p in sorted(folder.glob('*.bin')):
        data=p.read_bytes()
        if len(data)<40:continue
        magic,version,pc,top,itop,state_bytes,code_bytes,data_bytes,vsync=struct.unpack_from('<8IQ',data)
        if magic!=0x53315556 or version!=1 or code_bytes!=16384 or data_bytes!=16384:continue
        assert len(data)==40+state_bytes+code_bytes+data_bytes
        code=data[40+state_bytes:40+state_bytes+code_bytes]
        h=0xcbf29ce484222325
        for b in code:h=((h^b)*0x100000001b3)&0xffffffffffffffff
        key=f'{h:016x}';counts[key]+=1
        identity=(key,pc,hash(data[40:40+state_bytes]))
        if key in targets and len(selected[key])<16 and identity not in seen:
            seen.add(identity)
            dest=out/'snapshots'/key;dest.mkdir(parents=True,exist_ok=True)
            target=dest/f'vu1snap_{len(selected[key]):05}.bin'
            if target.exists():assert target.read_bytes()==data
            else:shutil.copy2(p,target)
            selected[key].append({'source':str(p),'start_pc':pc,'vsync':vsync,'bytes':len(data)})
record={'scope':'Existing original VU snapshots, metadata only; fixture payloads private',
        'available_by_image':dict(counts),'selected':dict(selected)}
(out/'snapshot-coverage.json').write_text(json.dumps(record,indent=2))
print(json.dumps({'available':dict(counts),'selected':{k:len(v) for k,v in selected.items()}},indent=2))
assert targets<=selected.keys(),'Missing actual snapshots for a new alias; do not claim validation'

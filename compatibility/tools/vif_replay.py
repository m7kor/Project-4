"""Scoped real-workload VIF DIRECT replay, using production VIF and CPU GS."""
from pathlib import Path
import argparse,hashlib,json,os,struct,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'artifacts/phase2/vif-direct'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def fnv(data,h=0xcbf29ce484222325):
    for b in data:h=((h^b)*0x100000001b3)&0xffffffffffffffff
    return h
def read_events(path):
    data=Path(path).read_bytes()
    if len(data)<32 or struct.unpack_from('<4Q',data)!=(0x31594c5052464956,1,4,0):raise ValueError('Invalid VIF fixture header')
    rows=[];pos=32
    for i in range(4):
        if pos+48>len(data):raise ValueError('Incomplete VIF event header')
        h=struct.unpack_from('<6Q',data,pos);pos+=48
        if h[0]!=i or h[2]>4*1024*1024 or not h[2] or h[2]%16 or pos+h[2]>len(data):raise ValueError('Incomplete or unordered VIF event')
        if h[1]>0xffffffff or (h[1]>>24)&127!=0x50 or (h[1]&65535 or 65536)*16!=h[2]:raise ValueError('Invalid DIRECT opcode or length')
        if rows and h[3]<rows[-1][0][3]:raise ValueError('VIF event timestamps regress')
        payload=data[pos:pos+h[2]];pos+=h[2];rows.append((h,payload))
    if pos!=len(data):raise ValueError('Unexpected VIF fixture tail')
    return rows
def expected_packets(events):
    h=0xcbf29ce484222325;values=[]
    for header,payload in events:
        # Captured setup transactions contain a GIF IMAGE tag. For the CPU
        # backend the production VIF emits a fresh tag for each continuation.
        if header[5]:payload=struct.pack('<2Q',(header[2]//16)|0x8000|(2<<58),0)+payload
        h=fnv(struct.pack('<I',len(payload)),h);h=fnv(payload,h);values.append(f'{h:016x}')
    return values
def validate_identity(binary,identity):
    if sha(binary)!=identity['binary_sha256']:raise ValueError('VIF executable identity mismatch')
    if sha(ROOT/'tests/vif_direct_replay.cpp')!=identity['harness_sha256']:raise ValueError('VIF harness source dependency changed')
    if sha(ROOT/'engines/project4/ps2xRuntime/src/lib/ps2_vif1_interpreter.cpp')!=identity['vif_source_sha256']:raise ValueError('VIF production source dependency changed')
    for name,digest in identity['linked_objects'].items():
        if sha(name)!=digest:raise ValueError('Linked dependency changed: '+name)
    for name,digest in identity.get('headers',{}).items():
        if sha(name)!=digest:raise ValueError('Header dependency changed: '+name)
def first_divergence(reference,candidate):
    if len(reference)!=len(candidate):return {'field':'event_count','reference':len(reference),'candidate':len(candidate)}
    for i,(a,b) in enumerate(zip(reference,candidate)):
        for key in sorted(set(a)|set(b)):
            if a.get(key)!=b.get(key):return {'event':i-1,'field':key,'reference':a.get(key),'candidate':b.get(key)}
    return None
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,default=DEFAULT/'fixture.bin');parser.add_argument('--golden',type=Path,default=DEFAULT/'golden.json')
    parser.add_argument('--binary',type=Path,default=ROOT/'lab/vif-replay-observed/vif_replay.exe')
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--record',action='store_true');args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    result={'passed':False,'real_re4_launched':False,'runs':[],'scope':'Two captured image uploads, initial reset transfer state, cross-command IMAGE state, packet bytes and VRAM. NOT full DMA scheduling or whole-game checkpoint.'}
    try:
        identity=json.loads((args.binary.parent/'identity.json').read_text());validate_identity(args.binary,identity)
        events=read_events(args.fixture);expected=expected_packets(events)
        env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
        env.update(PS2X_GS_BACKEND='cpu');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
        result.update(binary_sha256=sha(args.binary),fixture_sha256=sha(args.fixture),source_identity=identity)
        def execute(label,chunk,irq=False):
            p=subprocess.run([str(args.binary),str(args.fixture),str(chunk),*(['irq-probe'] if irq else [])],cwd=args.out,env=env,capture_output=True,text=True,timeout=30)
            (args.out/(label+'.stdout.txt')).write_text(p.stdout);(args.out/(label+'.stderr.txt')).write_text(p.stderr)
            if p.returncode:raise ValueError(label+': '+p.stderr)
            rows=[json.loads(s) for s in p.stdout.splitlines() if s.startswith('{')]
            if len(rows)!=5:raise ValueError('Incomplete replay observations')
            if rows[0]['register_hash']!=f'{fnv(bytes(92)):016x}':raise ValueError('Initial VIF register state differs from captured reset state')
            for i,row in enumerate(rows[1:]):
                if row['packet_hash']!=expected[i] or row['packets']!=i+1:raise ValueError(f'Independent packet oracle differs at event{i}')
                if row['ram']!=rows[0]['ram'] or row['vu_data']!=rows[0]['vu_data']:raise ValueError('DIRECT modified unrelated RAM/VU memory')
            result['runs'].append({'label':label,'chunk_bytes':chunk,'irq_probe':irq,'events':rows})
            return rows
        if args.record:
            if args.golden.exists():raise ValueError('Refuse to overwrite a golden oracle')
            normal=execute('record-normal',1048576);irq=execute('record-irq',4,True)
            if normal[-1]['vram']==normal[0]['vram']:raise ValueError('Fixture produced no VRAM effects')
            golden={'schema':1,'fixture_sha256':sha(args.fixture),'origin_binary_sha256':sha(args.binary),'normal':normal,'irq':irq,'initial_vif_register_words':[0]*23,'oracle':'Recorded accepted implementation plus independent GIF-byte oracle, not real-hardware proof'}
            args.golden.write_text(json.dumps(golden,indent=2))
        else:
            golden=json.loads(args.golden.read_text())
            if sha(args.fixture)!=golden['fixture_sha256']:raise ValueError('VIF fixture differs from golden identity')
            for chunk in (1048576,4,16,60):
                for repeat in range(2):
                    rows=execute(f'chunk-{chunk}-repeat-{repeat}',chunk);difference=first_divergence(golden['normal'],rows)
                    if difference:result['first_divergence']=difference;raise ValueError('VIF state/VRAM golden divergence')
            for chunk in (4,60):
                rows=execute('irq-'+str(chunk),chunk,True);difference=first_divergence(golden['irq'],rows)
                if difference:result['first_divergence']=difference;raise ValueError('VIF IRQ golden divergence')
        result['passed']=True
    except Exception as exc:result['error']=str(exc);print(str(exc),file=sys.stderr)
    finally:
        result['seconds']=time.monotonic()-start;(args.out/'report.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'passed':result['passed'],'runs':len(result['runs']),'seconds':result['seconds']}))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

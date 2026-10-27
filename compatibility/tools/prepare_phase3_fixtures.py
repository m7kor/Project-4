"""Private phase3 fixtures: captured bytes, explicitly synthetic transport setup."""
from pathlib import Path
import argparse,hashlib,json,re,struct
from vif_replay import read_events
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def create(out):
    out=Path(out).resolve()
    if not out.is_relative_to((ROOT/'artifacts').resolve()):raise ValueError('Private fixtures must stay inside artifacts')
    out.mkdir(parents=True,exist_ok=False);manifest={'schema':1,'fixtures':{},'real_re4_launched':False,'scope':'Captured payloads and SIF requests, synthetic DMA layouts and normalized initial state; no original DMA timing claimed'}
    original=ROOT/'artifacts/phase2/vif-direct/fixture.bin';events=read_events(original)[:2]
    def save(name,kind,initial,ops,provenance):
        fixture={'schema':1,'kind':kind,'initial':initial,'events':[dict(seq=i,**e) for i,e in enumerate(ops)],'provenance':provenance}
        path=out/(name+'.json');path.write_text(json.dumps(fixture,indent=2))
        manifest['fixtures'][name]={'path':path.name,'sha256':sha(path),'initial_sha256':hashlib.sha256(json.dumps(initial,sort_keys=True).encode()).hexdigest(),'kind':kind}
    def blob(address,b):return {'address':address,'hex':b.hex()}
    def mmio(address,value,**expect):return {'op':'mmio','address':address,'value':value,'expect':expect}
    def tag(qwc,id,address=0,irq=False):return struct.pack('<QQ',qwc|(id<<28)|(int(irq)<<31)|(address<<32),0)
    provenance={'payload_fixture_sha256':sha(original),'workload':'Two actual RE4 DIRECT transactions; DMA tags, addresses, interleaving and splits are synthetic. No original chain/timing checkpoint exists.'}
    for name,mode in [('dma-chain','chain'),('dma-split','split'),('dma-scratch','scratch'),('dma-tie','tie')]:
        initial=[];ops=[mmio(0x1000e010,1<<17,dstat=1<<17)];packet_count=0
        for i,(h,payload) in enumerate(events):
            header=struct.pack('<4I',0,0,0,h[1]);base=0x10000+i*0x1000;data=0x30000+i*0x1000
            if mode in ('chain','tie'):
                chain=tag(1,1)+header+tag(len(payload)//16,3,data,mode=='tie')+tag(0,7)
                initial.extend([blob(base,chain),blob(data,payload)])
                ops.extend([mmio(0x10009030,base),mmio(0x10009020,0),mmio(0x10009000,0x185 if mode=='tie' else 0x105,packets=i+1,image_qwc=64 if i==0 else 0,direct_remaining=0,vif_qwc=0,vif_tadr=base+48,vif_chcr=0xb0000085 if mode=='tie' else 0x70000005,pending_interrupt=True),{'op':'irq','expect':{'causes':[1],'pending_interrupt':False}}])
            else:
                # Complete DIRECT is split across independently completed normal DMAs.
                initial.append(blob(data,header+payload));offset=0;chunks=[16]+([32]*(len(payload)//32) if mode=='split' else [len(payload)])
                if mode=='scratch':
                    data=0x70000100+i*0x1000;initial.append(blob(data,header+payload))
                for n in chunks:
                    final=offset+n==16+len(payload)
                    remaining=len(payload) if offset==0 else len(payload)-(offset+n-16)
                    ops.extend([mmio(0x10009010,data+offset),mmio(0x10009020,n//16),mmio(0x10009000,0x101,packets=i+int(final),direct_remaining=0 if final else remaining,pending_interrupt=True),{'op':'irq','expect':{'causes':[1],'pending_interrupt':False}}]);offset+=n
            ops.append(mmio(0x1000e010,2,dstat=1<<17))
        save(name,'dma',initial,ops,provenance)
    # Actual physical scratchpad DMA8/9 copy, with wraparound and completion causes.
    initial=[blob(0x40000,bytes(range(32)))];ops=[mmio(0x1000d410,0x40000),mmio(0x1000d480,0x3ff0),mmio(0x1000d420,2),mmio(0x1000d400,0x100),{'op':'irq','expect':{'causes':[9],'pending_interrupt':False}},mmio(0x1000d010,0x41000),mmio(0x1000d080,0x3ff0),mmio(0x1000d020,2),mmio(0x1000d000,0x100),{'op':'irq','expect':{'causes':[8],'pending_interrupt':False}}]
    ops[-2]['expect']={'spr_roundtrip':list(range(32)),'spr_to_sadr':16,'spr_from_sadr':16,'spr_to_qwc':0,'spr_from_qwc':0}
    save('dma-spr-copy','dma',initial,ops,{'workload':'Synthetic32-byte SPR wraparound round trip, not recorded game traffic'})
    # A VIF DIRECT header remains live while a GIF path3 transfer completes.
    h,payload=events[0];initial=[blob(0x30000,struct.pack('<4I',0,0,0,h[1])+payload),blob(0x40000,struct.pack('<2Q',0x8000,0))]
    ops=[mmio(0x10009010,0x30000),mmio(0x10009020,1),mmio(0x10009000,0x101,direct_remaining=96,packets=0),{'op':'irq','expect':{'causes':[1]}},mmio(0x1000a010,0x40000),mmio(0x1000a020,1),mmio(0x1000a000,0x101,direct_remaining=96,packets=1,gif_chcr=1),{'op':'irq','expect':{'causes':[2]}},mmio(0x10009010,0x30010),mmio(0x10009020,6),mmio(0x10009000,0x101,direct_remaining=0,packets=2,image_qwc=64),{'op':'irq','expect':{'causes':[1],'pending_interrupt':False}}]
    save('dma-interleaved','dma',initial,ops,{'workload':'Real captured VIF setup interleaved with synthetic empty GIF packet; submission order only, no concurrent bus timing'})
    # Complete packets only; never fill missing trace bytes with invented zeros.
    log=ROOT/'artifacts/runs/acceptance-20261024-173321-636541/stderr.txt';packets=[]
    for line_no,line in enumerate(log.read_text(errors='replace').splitlines(),1):
        if not line.startswith('[SIF DMA]'):continue
        fields=dict(re.findall(r'(\w+)=(0x[0-9a-f]+|[0-9]+)',line));size=int(fields['bytes'],0)
        if size>64:raise ValueError('Incomplete capped SIF payload before selected sequence')
        words=[int(fields['w'+format(i,'x')],0) for i in range(size//4)]
        if size%4:raise ValueError('Non-word SIF capture not supported')
        packets.append({'src':int(fields['src'],0),'dst':int(fields['dst'],0),'attr':int(fields['attr'],0),'bytes':size,'payload':struct.pack('<'+'I'*len(words),*words),'line':line_no})
        if len(packets)==5:break
    if [x['bytes'] for x in packets]!=[20,16,64,4,64]:raise ValueError('Recorded boot sequence changed')
    initial=[blob(0x21000,struct.pack('<3I',0x22000,0,0))];ops=[]
    for i,p in enumerate(packets):
        ops.extend([{'op':'write','address':0x22000,'hex':bytes(64).hex(),'expect':{}},{'op':'write','address':p['src'],'hex':p['payload'].hex(),'expect':{}}])
        expect={'completion':-1}
        if i==1:expect['reply']=[24,0,0x80000001,0,0,1]+[0]*10
        if i==2:
            w=struct.unpack('<16I',p['payload']);expect['reply']=[64,0,0x80000008,0,*w[4:8],0x80000009,0x120000,0x120040,0,0,0,0,0]
        if i==4:
            w=struct.unpack('<16I',p['payload']);expect['reply']=[64,0,0x80000008,0,*w[4:8],0x8000000a,0,0,0,0,0,0,0];expect['receive']=[1,0,0x0226,0]
        ops.append({'op':'sif',**{k:p[k] for k in ('src','dst','attr','bytes')},'expect':expect})
    save('iop-sif-boot','iop',initial,ops,{'source_log_sha256':sha(log),'lines':[p['line'] for p in packets],'workload':'Five complete accepted-e179 SIF DMA requests: command init0/init1, CDVD bind, argument copy, CD init call. Initial command receiver normalized; actual reply bytes not captured. RPC_END identity fields checked from protocol; CDVDMAN version0x0226 is an implementation expectation from iop_cdvd.cpp, NOT hardware or recorded reply evidence.'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2));return manifest
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(create(a.out)))

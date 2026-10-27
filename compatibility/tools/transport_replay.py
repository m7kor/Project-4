"""Identity-checked, narrow production DMA and IOP/SIF offline replay gates."""
from pathlib import Path
import argparse,copy,hashlib,json,os,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'artifacts/phase3/fixtures-04'
BINARY=ROOT/'lab/dma-iop-replay-07/vif_replay.exe'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def validate_identity(binary,identity):
    if sha(binary)!=identity['binary_sha256']:raise ValueError('Transport executable identity mismatch')
    if sha(identity['harness_path'])!=identity['harness_sha256']:raise ValueError('Transport harness source changed')
    if sha(ROOT/'tests/vif_direct_replay.cpp')!=identity['included_harness_sha256']:raise ValueError('Included observer harness changed')
    for group in ('production_sources','headers','linked_objects'):
        if not identity.get(group):raise ValueError('Missing source/dependency identity')
        for p,digest in identity[group].items():
            if sha(p)!=digest:raise ValueError('Stale transport dependency: '+p)
def validate_fixture(path,entry):
    if sha(path)!=entry['sha256']:raise ValueError('Transport fixture identity mismatch')
    fixture=json.loads(Path(path).read_text())
    if hashlib.sha256(json.dumps(fixture['initial'],sort_keys=True).encode()).hexdigest()!=entry['initial_sha256']:raise ValueError('Initial-state identity mismatch')
    if fixture['schema']!=1 or fixture['kind']!=entry['kind'] or not fixture['events']:raise ValueError('Invalid fixture schema')
    if [r['seq'] for r in fixture['events']]!=list(range(len(fixture['events']))):raise ValueError('Replay command order invalid')
    for event in fixture['events']:
        if event['op'] not in ('mmio','write','drain','irq','sif') or not isinstance(event['expect'],dict):raise ValueError('Unsupported replay event')
    return fixture
def difference(a,b):
    if len(a)!=len(b):return {'field':'observation_count','expected':len(a),'actual':len(b)}
    for i,(left,right) in enumerate(zip(a,b)):
        for k in sorted(set(left)|set(right)):
            if left.get(k)!=right.get(k):return {'event':i-1,'field':k,'expected':left.get(k),'actual':right.get(k)}
def select_entries(manifest,group):
    expected={'dma-chain','dma-split','dma-scratch','dma-tie','dma-spr-copy','dma-interleaved'}
    if group=='iop':expected={'iop-sif-boot'}
    elif group=='all':expected.add('iop-sif-boot')
    entries={k:v for k,v in manifest['fixtures'].items() if group=='all' or v['kind']==group}
    if manifest.get('schema')!=1 or set(entries)!=expected:raise ValueError('Incomplete or unsupported transport fixture set')
    return entries
def execute(binary,fixture,out,label):
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
    env.update(PS2X_GS_BACKEND='cpu',PS2X_SIF_RPC_ASYNC='0')
    env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
    start=time.monotonic();p=subprocess.run([str(binary),str(fixture)],cwd=out,env=env,capture_output=True,text=True,timeout=90)
    (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr)
    rows=[json.loads(line) for line in p.stdout.splitlines() if line.startswith('{')]
    return p,rows,round(time.monotonic()-start,3)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--group',choices=('dma','iop','all'),default='all');p.add_argument('--fixtures',type=Path,default=DEFAULT);p.add_argument('--binary',type=Path,default=BINARY);p.add_argument('--out',type=Path,required=True);p.add_argument('--record',action='store_true');p.add_argument('--mutations',action='store_true');args=p.parse_args()
    out=args.out.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):raise ValueError('Reports must remain in lab artifacts')
    out.mkdir(parents=True,exist_ok=False);start=time.monotonic();report={'passed':False,'real_re4_launched':False,'runs':[],'mutations':[],'scope':'Normalized production DMAC scenarios and complete captured SIF requests. Runtime agreement, recorded-input agreement, and hardware agreement are separate. No cycle timing claim.'}
    try:
        identity=json.loads((args.binary.parent/'identity.json').read_text());validate_identity(args.binary,identity)
        manifest=json.loads((args.fixtures/'manifest.json').read_text());report.update(binary_sha256=sha(args.binary),source_identity=identity,manifest_sha256=sha(args.fixtures/'manifest.json'),oracle_categories={'runtime_agreement':'Full-state per-event golden and repeated determinism; normalized start, not whole-game checkpoint','recorded_re4_agreement':'Actual VIF payloads and five complete SIF input packets; DMA outputs cross-checked with phase2 VIF path; original SIF reply bytes unavailable','independent_protocol':'RPC_END correlation, DMA status/masks, split DIRECT completion, SPR roundtrip and IRQ cause expectations','independent_hardware':'No new hardware execution or captured cycle timing'})
        entries=select_entries(manifest,args.group);goldens={}
        for name,entry in entries.items():
            fixture=validate_fixture(args.fixtures/entry['path'],entry);golden=args.fixtures/(name+'.golden.json')
            if args.record and golden.exists():raise ValueError('Refuse to overwrite golden: '+name)
            if not args.record:
                baseline=json.loads(golden.read_text())
                if baseline['fixture_sha256']!=entry['sha256']:raise ValueError('Golden fixture identity differs')
                goldens[name]=baseline['observations']
            for repeat in range(2):
                child,rows,seconds=execute(args.binary,args.fixtures/entry['path'],out,name+'-'+str(repeat))
                if child.returncode:raise ValueError(name+': '+child.stderr[-1200:])
                if len(rows)!=len(fixture['events'])+1:raise ValueError('Incomplete replay capture: '+name)
                if repeat==0 and args.record:goldens[name]=rows
                delta=difference(goldens[name],rows)
                if delta:report['first_divergence']={'test':name,**delta};raise ValueError('Transport state divergence: '+name)
                report['runs'].append({'name':name,'repeat':repeat,'seconds':seconds,'observations':len(rows),'golden_sha256':None if args.record else sha(golden)})
            if args.record:golden.write_text(json.dumps({'fixture_sha256':entry['sha256'],'origin_binary_sha256':sha(args.binary),'observations':goldens[name],'oracle':'Normalized production runtime result, NOT hardware capture'},indent=2))
        # Match uploaded bytes and memory effects to the independently executed
        # phase2 VIF path, in addition to all per-event protocol assertions.
        phase2=json.loads((ROOT/'artifacts/phase2/vif-direct/golden.json').read_text())['normal'][2]
        for name,rows in goldens.items():
            if name in ('dma-chain','dma-split','dma-scratch','dma-tie'):
                for key in ('vram','packet_hash','packets','vu_data','image_qwc'):
                    if rows[-1][key]!=phase2[key]:raise ValueError('Recorded VIF cross-path output differs: '+name+'/'+key)
        if args.mutations:
            def mutation(name,case,edit):
                f=copy.deepcopy(json.loads((args.fixtures/(case+'.json')).read_text()));edit(f)
                path=out/(name+'.json');path.write_text(json.dumps(f));child,rows,seconds=execute(args.binary,path,out,name)
                delta=difference(goldens[case],rows);detected=child.returncode!=0 or delta is not None
                report['mutations'].append({'name':name,'detected':detected,'seconds':seconds,'native_exit':child.returncode,'first_divergence':delta,'error':child.stderr[-250:]})
                if not detected:raise ValueError('Mutation survived: '+name)
            if 'dma-chain' in goldens:
                mutation('chain-qwc','dma-chain',lambda f:f['initial'][0].update(hex='0000'+f['initial'][0]['hex'][4:]))
                mutation('dma-mask','dma-chain',lambda f:f['events'][0].update(value=0))
                mutation('command-order','dma-chain',lambda f:f['events'][1].update(seq=999))
                mutation('missing-tail','dma-chain',lambda f:f['events'].pop())
                mutation('dma-memory-effect','dma-chain',lambda f:f['initial'][3].update(hex=f['initial'][3]['hex'][:-2]+'ff'))
            if 'iop-sif-boot' in goldens:
                mutation('rpc-reply-identity','iop-sif-boot',lambda f:f['events'][7].update(hex=f['events'][7]['hex'][:48]+'99999999'+f['events'][7]['hex'][56:]))
                mutation('rpc-server-route','iop-sif-boot',lambda f:f['events'][13].update(hex=f['events'][13]['hex'][:104]+'efbeadde'+f['events'][13]['hex'][112:]))
                mutation('rpc-completion','iop-sif-boot',lambda f:f['events'][-1]['expect'].update(completion=0))
                mutation('iop-initial-state','iop-sif-boot',lambda f:f['initial'][0].update(hex='00000000'+f['initial'][0]['hex'][8:]))
        report['passed']=True
    except Exception as exc:report['error']=str(exc);print(str(exc),file=sys.stderr)
    finally:
        report['seconds']=round(time.monotonic()-start,3);(out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report['passed'],'runs':len(report['runs']),'mutations':len(report['mutations']),'seconds':report['seconds']}));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

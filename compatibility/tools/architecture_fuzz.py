"""Deterministic offline operand mutations of real microcode snapshots.

Never applied to a running game. These are synthetic operands, not recorded RE4
executions or PS2 hardware evidence. Code, VI/address state and data stay intact.
"""
from pathlib import Path
import hashlib,json,os,random,re,struct,subprocess,time
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture/operand-fuzz-01';out.mkdir(exist_ok=False);fixtures=out/'fixtures';fixtures.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();binary=ROOT/'lab/architecture-aot-state-02/state_probe.exe'
for p,h in json.loads((binary.parent/'identity.json').read_text()).items():assert sha(Path(p))==h,p
headers=[ROOT/'engines/project4/ps2xRuntime/include/runtime/ps2_vu1.h',Path('C:/Project/PS2redmption/core/ps2xRuntime/include/runtime/ps2_vu1.h')]
for h in headers:assert re.search(r'struct VU1State\s*\{\s*float vf\[32\]\[4\];\s*int32_t vi\[16\];\s*float acc\[4\];',h.read_text())
rng=random.Random(0xA071234);edges=[0,0x80000000,1,0x007fffff,0x00800000,0x00ffffff,0x01000000,0x7effffff,0x7f000000,0x7f7fffff,0x7f800000,0x7fc00001,0xff800000]
manifest=[]
for i in range(64):
 source=ROOT/f'artifacts/phase5/fixtures/image-53c46ebcaf7db574/vu1snap_{i:05}.bin';data=bytearray(source.read_bytes());magic,version,pc,top,itop,state_size,code_size,data_size,ee=struct.unpack_from('<8IQ',data)
 assert magic==0x53315556 and version==1 and state_size>=608 and len(data)==40+state_size+code_size+data_size
 mutations=[]
 for lane in [*rng.sample(range(4,128),8),144+rng.randrange(4)]:
  value=rng.choice(edges) if i%2 else rng.getrandbits(32);offset=40+lane*4;previous=struct.unpack_from('<I',data,offset)[0];struct.pack_into('<I',data,offset,value);mutations.append({'state_word':lane,'before':previous,'after':value})
 target=fixtures/f'vu1snap_{i:05}.bin';target.write_bytes(data);manifest.append({'source':str(source),'source_sha256':sha(source),'fixture_sha256':sha(target),'mutations':mutations})
(out/'fixtures.json').write_text(json.dumps(manifest,indent=2))
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
report={'passed':False,'seed':'0xA071234','rows':[],'binary_sha256':sha(binary),'header_sha256':{str(p):sha(p) for p in headers},'scope':__doc__};begin=time.monotonic()
try:
 for budget,resumes in [(1,16),(4,16),(31,16),(256,4),(4096,2)]:
  hashes=[]
  for mode in ('0','1'):
   label=f'{budget}-{mode}';log=out/(label+'.states.txt');p=subprocess.run([str(binary),str(fixtures),'--budget',str(budget),'--resumes',str(resumes),'--repeat','1','--gif-hash'],cwd=out,env={**env,'PS2X_VU1_AOT_COVERAGE':mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=90)
   (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,(label,p.stderr[-800:]);hashes.append(sha(log));report['rows'].append({'budget':budget,'mode':mode,'checkpoints':len(log.read_text().splitlines()),'sha256':hashes[-1]})
  assert hashes[0]==hashes[1],('Full state mismatch',budget)
  print('Operand mutations matched budget',budget,flush=True)
 report['passed']=True
finally:report['seconds']=time.monotonic()-begin;(out/'report.json').write_text(json.dumps(report,indent=2))

"""Actual golden replay and full pending-state comparisons, no game launches."""
from pathlib import Path
import hashlib,json,os,re,subprocess,time,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
vector='--vector' in sys.argv;fmac='--fmac' in sys.argv
requested_out=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--out=')),None)
out=Path(requested_out).resolve() if requested_out else ROOT/'artifacts/phase5'/('equivalence-03' if fmac else 'equivalence-02' if vector else 'equivalence-01')
assert out.is_relative_to(ROOT/'artifacts');out.mkdir(exist_ok=False);start=time.monotonic()
bench=ROOT/'lab'/('phase5-fmac-01' if fmac else 'phase5-vector-01' if vector else 'phase5-pipeline-01')/'ps2x_vu1_bench.exe'
probe=ROOT/'lab'/('phase5-fmac-state-01' if fmac else 'phase5-vector-state-01' if vector else 'phase5-state-probe-02')/'state_probe.exe'
probe_name=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--probe-dir=')),None)
if probe_name:probe=(ROOT/'lab'/probe_name/'state_probe.exe').resolve();assert probe.is_relative_to(ROOT/'lab')
mode_env='PS2X_VU1_FMAC_CLASSIFY' if fmac else 'PS2X_VU1_VECTOR_RETIRE' if vector else 'PS2X_VU1_PIPELINE_INDEX'
manifest=json.loads((bench.parent/'identity.json').read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(bench)==manifest[bench.name]
for path,digest in json.loads((probe.parent/'identity.json').read_text()).items():assert sha(path)==digest
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1',TEMP=str(out),TMP=str(out))
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
rows=[]
def run(label,args,extra=None,exe=probe):
 log=out/(label+'.state.txt')
 p=subprocess.run([str(exe),*map(str,args)],cwd=out,env={**env,'PS2X_VU1_PIPELINE_STATE_LOG':str(log),**(extra or {})},capture_output=True,text=True,timeout=240)
 (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr)
 row={'label':label,'returncode':p.returncode,'state_log_sha256':sha(log) if log.exists() else None,'checkpoints':len(log.read_text().splitlines()) if log.exists() else 0}
 rows.append(row);assert p.returncode==0,(label,p.stderr[-700:]);return p.stdout,row
trace=Path('C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands')
workloads=[('commands-964',trace)]+[(f'edge-{n}',Path('C:/Project/PS2redmption/artifacts/verification/vu-clean-blocks-v41/edge-replay-v2')/f'budget-{n}'/'commands') for n in (1,2,4,31,256,4096,65536)]
try:
 for label,folder in workloads:
  signatures=[]
  for mode in ('0','1'):
   text,row=run(label+'-'+mode,['--commands',folder,'--repeat','1'],{mode_env:mode})
   signatures.append(row['state_log_sha256'])
  assert signatures[0]==signatures[1],('Full pipeline state mismatch',label)
  print('Full pending state and recorded golden matched',label,flush=True)
 fixtures=ROOT/'artifacts/phase5/fixtures/image-53c46ebcaf7db574';reuse=fixtures.exists()
 if not reuse:fixtures.mkdir(parents=True,exist_ok=False)
 inventory=json.loads((ROOT/'artifacts/phase4/vu-fixture-inventory.json').read_text())
 selected=[r for r in inventory['valid'] if r['image']=='53c46ebcaf7db574'];assert len(selected)==800
 for number,row in enumerate(selected):
  assert sha(row['path'])==row['sha256']
  target=fixtures/f'vu1snap_{number:05}.bin'
  if reuse:assert sha(target)==row['sha256']
  else:shutil.copyfile(row['path'],target)
 if not reuse:(fixtures/'source-manifest.json').write_text(json.dumps(selected,indent=2))
 for budget,resumes in [(65536,0),(1,16),(4,16),(31,16),(4096,4)]:
  signatures=[];outputs=[]
  for mode in ('0','1'):
   text,row=run(f'snap800-{budget}-{mode}',[fixtures,'--budget',budget,'--resumes',resumes,'--repeat','1','--gif-hash'],{mode_env:mode})
   signatures.append(row['state_log_sha256']);outputs.append({key:re.search(pattern,text)[1] for key,pattern in [('state',r' result=([a-f0-9]{16})'),('cycles',r'vu1_cycles=(\d+)'),('gif_packets',r'gif_packets=(\d+)'),('gif_result',r'gif_result=([a-f0-9]{16})')]})
  assert signatures[0]==signatures[1] and outputs[0]==outputs[1],('Snapshot mismatch',budget)
  print('800 snapshots full state/cycles/GIF matched',budget,flush=True)
 result={'passed':True,'rows':rows,'seconds':time.monotonic()-start,'source_sha256':sha(ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'),'probe_sha256':sha(probe),'scope':'All fields, including inactive pipeline payloads. Padding/host pointers/decoded caches excluded by observer contract, no architectural flags excluded.'}
except Exception as exc:
 result={'passed':False,'error':str(exc),'rows':rows,'seconds':time.monotonic()-start};raise
finally:(out/'report.json').write_text(json.dumps(result,indent=2))

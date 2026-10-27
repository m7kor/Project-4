"""Seven alternating same-binary retirement-mode pairs after complete correctness."""
from pathlib import Path
import hashlib,json,os,statistics,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[1]
vector='--vector' in sys.argv;fmac='--fmac' in sys.argv
assert json.loads((ROOT/'artifacts/phase5'/('equivalence-03' if fmac else 'equivalence-02' if vector else 'equivalence-01')/'report.json').read_text())['passed']
against_phase4='--against-phase4' in sys.argv or vector or fmac
out=ROOT/'artifacts/phase5'/('timing-04' if fmac else 'timing-03' if vector else 'timing-02' if against_phase4 else 'timing-01')
recover='--summarize-existing' in sys.argv
if not recover:out.mkdir(exist_ok=False)
binary=ROOT/'lab'/('phase5-fmac-01' if fmac else 'phase5-vector-01' if vector else 'phase5-pipeline-01')/'ps2x_vu1_bench.exe'
reference=ROOT/'lab/phase4-suite-02/ps2x_vu1_bench.exe' if against_phase4 else binary
identity=json.loads((binary.parent/'identity.json').read_text())
assert hashlib.sha256(binary.read_bytes()).hexdigest()==identity[binary.name]
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1')
env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
trace='C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands'
rows=[];start=time.monotonic()
for pair in range(7):
 for mode in (('0','1') if pair%2==0 else ('1','0')):
  if recover:text=(out/f'{pair}-{mode}.stdout.txt').read_text()
  else:
   p=subprocess.run([str(reference if mode=='0' else binary),'--commands',trace,'--repeat','75','--timing-after-verify'],cwd=out,env={**env,('PS2X_VU1_FMAC_CLASSIFY' if fmac else 'PS2X_VU1_VECTOR_RETIRE' if vector else 'PS2X_VU1_PIPELINE_INDEX'):mode},capture_output=True,text=True,timeout=120)
   (out/f'{pair}-{mode}.stdout.txt').write_text(p.stdout);(out/f'{pair}-{mode}.stderr.txt').write_text(p.stderr)
   assert p.returncode==0,(pair,mode,p.returncode)
   text=p.stdout
  row=json.loads(text.splitlines()[-1]);assert row['gif_verified_passes']>0 and row['repeats']==75
  rows.append({**row,'pair':pair,'pipeline_index':mode})
 print('Alternating isolated pair completed',pair+1,flush=True)
changes=[]
for pair in range(7):
 a=next(r for r in rows if r['pair']==pair and r['pipeline_index']=='0')['ns_per_cycle'];b=next(r for r in rows if r['pair']==pair and r['pipeline_index']=='1')['ns_per_cycle']
 changes.append((a-b)/a*100)
result={'rows':rows,'paired_cost_reduction_percent':changes,'median_cost_reduction_percent':statistics.median(changes),'reference_median_ns_per_cycle':statistics.median(r['ns_per_cycle'] for r in rows if r['pipeline_index']=='0'),'indexed_median_ns_per_cycle':statistics.median(r['ns_per_cycle'] for r in rows if r['pipeline_index']=='1'),'analysis_seconds':time.monotonic()-start,'recovered_all14_original_logs':recover,'binary_sha256':identity[binary.name],'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'all_pairs_improved':all(c>0 for c in changes),'scope':'Phase4 unchanged reference versus new indexed core, alternating' if against_phase4 else 'Same binary, off/on alternating. Recorded VU command cost only, not gameplay speed.'}
(out/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)

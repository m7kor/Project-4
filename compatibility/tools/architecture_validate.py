"""Reuse existing VU full-state observer and captured fixtures for the AOT candidate."""
from pathlib import Path
import hashlib,json,os,re,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture'/('equivalence-01' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'artifacts/architecture';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
build=ROOT/'lab'/('architecture-aot-01' if len(sys.argv)<3 else sys.argv[2]);probe=ROOT/'lab'/('architecture-aot-state-01' if len(sys.argv)<4 else sys.argv[3])/'state_probe.exe'
assert build.parent==ROOT/'lab' and probe.parent.parent==ROOT/'lab'
for p,h in json.loads((probe.parent/'identity.json').read_text()).items():assert sha(p)==h,p
for p,h in json.loads((build/'engineering-inputs.json').read_text())['files'].items():assert sha(p)==h,p
identity=json.loads((build/'identity.json').read_text())
for name,h in identity.items():assert sha(build/name)==h,name
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1',TEMP=str(out),TMP=str(out));env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
report={'passed':False,'rows':[],'first_divergence':None,'source_manifest_sha256':sha(build/'engineering-inputs.json'),'probe_sha256':sha(probe),'unit_sha256':identity['ps2x_tests.exe'],'scope':'Runtime differential equivalence, recorded RE4 golden commands, synthetic queues; not independent hardware evidence'};start=time.monotonic()
def run(label,args,mode,exe=probe):
 log=out/(label+'-'+mode+'.states.txt');cwd=ROOT/'engines/project4' if exe.name=='ps2x_tests.exe' else out
 p=subprocess.run([str(exe),*map(str,args)],cwd=cwd,env={**env,'PS2X_VU1_AOT_COVERAGE':mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=240)
 (out/(label+'-'+mode+'.stdout.txt')).write_text(p.stdout);(out/(label+'-'+mode+'.stderr.txt')).write_text(p.stderr)
 row={'label':label,'mode':mode,'exit':p.returncode,'log_sha256':sha(log) if log.exists() else None,'checkpoints':len(log.read_text().splitlines()) if log.exists() else None}
 report['rows'].append(row)
 if p.returncode:report['first_divergence']={'label':label,'mode':mode,'kind':'process-or-golden-failure','stderr':p.stderr[-1800:]};raise RuntimeError(str(report['first_divergence']))
 return p.stdout,log
def compare(label,args):
 results=[run(label,args,m) for m in ('0','1')];a,b=[x[1].read_text().splitlines() for x in results]
 if a!=b:
  n=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
  report['first_divergence']={'label':label,'checkpoint':n,'reference':a[n] if n<len(a) else 'missing','candidate':b[n] if n<len(b) else 'missing','kind':'full-state-hash; field-level minimization required'};raise RuntimeError(str(report['first_divergence']))
 # Hash logs include full pipelines/VU data; separately preserve cycle and GIF result outputs.
 patterns=[r' result=([a-f0-9]{16})',r'vu1_cycles=(\d+)',r'gif_packets=(\d+)',r'gif_result=([a-f0-9]{16})']
 for pattern in patterns:
  assert re.findall(pattern,results[0][0])==re.findall(pattern,results[1][0]),(label,pattern)
 print('Matched',label,len(a),'full checkpoints',flush=True)
try:
 for mode in ('0','1'):
  text,_=run('cpp',[],mode,build/'ps2x_tests.exe')
  clean=re.sub(r'\x1b\[[0-9;]*m','',text);passed=re.search(r'Passed:\s*(\d+)',clean);failed=re.search(r'Failed:\s*(\d+)',clean)
  prior=json.loads((ROOT/'artifacts/regression/20261026T101932.882359Z/report.json').read_text());expected=next(x['case_counts']['passed'] for x in prior['tests'] if x['name']=='cpp-unit')
  assert passed and failed and int(passed[1])>=expected and int(failed[1])==0,text[-600:]
  report['rows'][-1]['case_counts']={'passed':int(passed[1]),'failed':int(failed[1])}
 trace=Path('C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands')
 compare('commands964',['--commands',trace,'--repeat','1'])
 for n in [1,2,4,31,256,4096,65536]:
  folder=Path('C:/Project/PS2redmption/artifacts/verification/vu-clean-blocks-v41/edge-replay-v2')/f'budget-{n}'/'commands';compare('budget'+str(n),['--commands',folder,'--repeat','1'])
 fixtures=ROOT/'artifacts/phase5/fixtures/image-53c46ebcaf7db574';catalog=json.loads((ROOT/'artifacts/phase4/vu-fixture-inventory.json').read_text())
 for i,row in enumerate(r for r in catalog['valid'] if r['image']=='53c46ebcaf7db574'):assert sha(fixtures/f'vu1snap_{i:05}.bin')==row['sha256']
 for budget,resumes in [(65536,0),(1,16),(4,16),(31,16),(4096,4)]:compare('snap800-'+str(budget),[fixtures,'--budget',budget,'--resumes',resumes,'--repeat','1','--gif-hash'])
 allfixtures=ROOT/'artifacts/phase5/catalog-01/fixtures'
 assert len(catalog['valid'])==3200
 for i,row in enumerate(catalog['valid']):assert sha(allfixtures/f'vu1snap_{i:05}.bin')==row['sha256']
 compare('catalog3200',[allfixtures,'--budget','65536','--resumes','0','--repeat','1','--gif-hash'])
 compare('random512',['--phase5-random'])
 report['passed']=True
finally:
 report['seconds']=time.monotonic()-start;(out/'report.json').write_text(json.dumps(report,indent=2));print('AOT correctness',report['passed'],flush=True)

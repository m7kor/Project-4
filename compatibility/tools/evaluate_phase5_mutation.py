"""Bounded confirmation of the already-compiled deliberate enqueue-index defect."""
from pathlib import Path
import hashlib,json,os,subprocess
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'lab/phase5-mutation-01'
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
needle='    noteRetirement(this, 0, entry->readyCycle);'
expected=source.read_text(encoding='utf-8').replace(needle,'    // Mutation: omit FMAC enqueue notification.')
assert (folder/'mutant_core.cpp').read_text(encoding='utf-8')==expected
out=ROOT/'artifacts/phase5/mutation-confirm-01';out.mkdir(exist_ok=False)
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
rows=[]
for mode in ('0','1'):
 log=out/(mode+'.state.txt');args=[str(folder/'mutant_probe.exe'),'--commands','C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands','--repeat','1']
 try:
  p=subprocess.run(args,cwd=out,env={**env,'PS2X_VU1_PIPELINE_INDEX':mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=5)
  (out/(mode+'.stdout.txt')).write_text(p.stdout+p.stderr);row={'mode':mode,'returncode':p.returncode,'timeout':False}
 except subprocess.TimeoutExpired as error:
  row={'mode':mode,'timeout':True,'deadline_seconds':5};(out/(mode+'.timeout.txt')).write_text(str(error))
 row['checkpoints']=len(log.read_text().splitlines()) if log.exists() else 0;rows.append(row)
assert rows[0]['returncode']==0 and rows[0]['checkpoints']==964
assert rows[1]['timeout'] or rows[1].get('returncode',0)!=0
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
report={'mutation_detected':True,'runs':rows,'first_failure':'First command does not retire with omitted FMAC index notification; bounded timeout, no checkpoint completed','source_sha256':sha(source),'mutant_source_sha256':sha(folder/'mutant_core.cpp'),'mutant_binary_sha256':sha(folder/'mutant_probe.exe'),'scope':'Actual compiled one-line mutation. No production source changed. Earlier120s timeout preserved; confirmation deadline5s.'}
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

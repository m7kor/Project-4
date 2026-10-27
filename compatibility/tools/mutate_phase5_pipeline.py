"""Remove one enqueue-index update in a private source copy and prove detection."""
from pathlib import Path
import hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/phase5-mutation-01';out.mkdir(exist_ok=False)
original=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp';data=original.read_text(encoding='utf-8')
needle='    noteRetirement(this, 0, entry->readyCycle);';assert data.count(needle)==1
source=out/'mutant_core.cpp';source.write_text(data.replace(needle,'    // Mutation: omit FMAC enqueue notification.'),encoding='utf-8')
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text());row=next(r for r in db if Path(r['file']).name==original.name);obj=out/'mutant.obj'
cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',row['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/'compiler.pdb')+'"',cmd)
cmd=cmd[:cmd.rindex(' -c -- ')]+' -I"'+str(original.parent)+'" -c -- "'+str(source)+'"'
subprocess.run(cmd,cwd=out,check=True)
rsp=(ROOT/'lab/phase5-state-probe-04/link.rsp').read_text();rsp=rsp.replace(str(ROOT/'lab/phase5-pipeline-01/ps2_vu1_core.cpp.obj'),str(obj))
for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/('mutant_probe.exe'+suffix))+'"',rsp)
(out/'link.rsp').write_text(rsp);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(out/'link.rsp')],cwd=out,check=True)
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
trace='C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands'
rows=[]
for mode in ('0','1'):
 log=out/(mode+'.state.txt');p=subprocess.run([str(out/'mutant_probe.exe'),'--commands',trace,'--repeat','1'],cwd=out,env={**env,'PS2X_VU1_PIPELINE_INDEX':mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=120)
 (out/(mode+'.stdout.txt')).write_text(p.stdout);(out/(mode+'.stderr.txt')).write_text(p.stderr)
 rows.append({'mode':mode,'returncode':p.returncode,'log':log.read_text().splitlines() if log.exists() else [],'stderr_tail':p.stderr[-1200:]})
assert rows[0]['returncode']==0
divergence=next(({'checkpoint':i,'reference':a,'mutant':b} for i,(a,b) in enumerate(zip(rows[0]['log'],rows[1]['log'])) if a!=b),None)
detected=bool(rows[1]['returncode'] or divergence or len(rows[0]['log'])!=len(rows[1]['log']));assert detected,'Mutation not detected'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
report={'mutation_detected':detected,'first_divergence':divergence,'runs':[{k:v for k,v in r.items() if k!='log'} for r in rows],'source_before_sha256':sha(original),'mutant_sha256':sha(source),'mutant_executable_sha256':sha(out/'mutant_probe.exe'),'scope':'Actual compiled mutation; production source unchanged. Omitted FMAC enqueue-index maintenance.'}
(ROOT/'artifacts/phase5/mutation-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)

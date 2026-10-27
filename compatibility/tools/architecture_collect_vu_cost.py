"""Actual issued-pair coverage and stall counts from the current real capture."""
from pathlib import Path
import hashlib,json,os,re,subprocess
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture/vu-native-coverage-01';out.mkdir(exist_ok=False)
build=ROOT/'lab/architecture-vu-cost-01';binary=build/'ps2x_vu1_bench.exe';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
identity=json.loads((build/'identity.json').read_text());assert sha(binary)==identity[binary.name]
for path,h in json.loads((build/'generation.json').read_text())['input_files'].items():assert sha(Path(path))==h,path
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1',PS2X_ARCH_VU_COST='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
trace=ROOT/'artifacts/runs/architecture-input-clock-01/diagnostics/vu-commands';rows=[]
for mode in ('0','1'):
 p=subprocess.run([str(binary),'--commands',str(trace),'--repeat','1'],cwd=out,env={**env,'PS2X_VU1_AOT_COVERAGE':mode},capture_output=True,text=True,timeout=90)
 (out/(mode+'.stdout.txt')).write_text(p.stdout);(out/(mode+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,p.stderr
 replay=json.loads(p.stdout.strip().splitlines()[-1]);records=[json.loads(x) for x in re.findall(r'\[architecture-vu-cost\] (\{[^\n]+\})',p.stderr)];assert records
 count={key:sum(x[key] for x in records) for key in records[0]};assert count['native_pairs']<=count['pairs']
 total=count['native_envelope_cycles']+count['generic_envelope_cycles']+count['flush_cycles'];assert total==replay['cycles'],(total,replay['cycles'])
 rows.append({'aot_mode':mode,'counts':count,'specialized_native_pair_percent':100*count['native_pairs']/count['pairs'],'native_envelope_cycle_percent':100*count['native_envelope_cycles']/total,'stall_cycle_percent':100*count['stall_cycles']/total,'replay_result':{k:v for k,v in replay.items() if k not in ('best_seconds','ns_per_cycle')},'timings_discarded':True})
report={'passed':True,'binary_sha256':sha(binary),'rows':rows,'scope':'Exact counters in a private instrumented replay of1024 current RE4 commands. Pairs count actual issue; native envelope includes waits within compiled blocks. NOT whole-game coverage, hardware evidence or performance. Diagnostic timings discarded.'}
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

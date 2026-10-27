"""Run the existing full suite with explicit AOT mode and generator freshness."""
from pathlib import Path
import hashlib,json,subprocess,sys,time,re
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture'/('full-gate-01' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'artifacts/architecture';out.mkdir(exist_ok=False)
build=ROOT/'lab/architecture-aot-02';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
generation=json.loads((build/'generation.json').read_text());engineering=json.loads((build/'engineering-inputs.json').read_text())
inputs={**generation['input_files'],**engineering['files'],str(build/'generation.json'):sha(build/'generation.json'),str(build/'engineering-inputs.json'):sha(build/'engineering-inputs.json')}
for p,h in inputs.items():assert sha(Path(p))==h,p
(out/'source-witness.json').write_text(json.dumps(inputs,indent=2))
command=[sys.executable,str(ROOT/'tools/lab_regression.py'),'full','--candidate-dir',str(build),'--baseline-dir',str(ROOT/'lab/phase4-suite-02'),'--project4-recompiler',str(ROOT/'lab/phase4-fixed-01/ps2_recomp.exe'),'--vu-aot-coverage','1','--changed','lab/architecture-aot-02/src/ps2_vu1_core.cpp']
print('Running existing full suite against actual AOT candidate mode1',flush=True);start=time.monotonic()
p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=600)
(out/'stdout.txt').write_text(p.stdout);(out/'stderr.txt').write_text(p.stderr)
for path,h in inputs.items():assert sha(Path(path))==h,'Inputs changed during validation: '+path
match=re.search(r'REPORT (.+report\.json)',p.stdout);report_path=Path(match[1].strip()) if match else None
suite=json.loads(report_path.read_text()) if report_path else None
result={'passed':p.returncode==0 and bool(suite and suite['passed'] and suite.get('vu_aot_coverage')=='1'),'returncode':p.returncode,'seconds':time.monotonic()-start,'suite_report':str(report_path),'counts':suite.get('counts') if suite else None,'source_witness_sha256':sha(out/'source-witness.json'),'scope':'Actual new AOT binary with mode1, existing complete regression command; hardware reference results remain separate'}
(out/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));sys.exit(0 if result['passed'] else 1)

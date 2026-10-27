"""Bind completed engine checks plus a corrected Python rerun, without hiding failures."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/host-boundary'/('gate-01' if len(sys.argv)<2 else sys.argv[1]);assert out.parent==ROOT/'artifacts/host-boundary';out.mkdir(parents=True,exist_ok=False);(out/'temp').mkdir()
expected_tests=102 if len(sys.argv)<3 else int(sys.argv[2])
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
full=ROOT/'artifacts/regression/20261027T052041.727387Z/report.json';report=json.loads(full.read_text())
assert report['counts']=={'passed':116,'failed':1,'known-mismatch':8}
assert [r['name'] for r in report['tests'] if r['status']=='failed']==['lab-python']
assert any(r['name']=='synthetic-pipeline' and r['status']=='passed' for r in report['tests'])
build=ROOT/'lab/host-boundary-inline-01';witness={}
for name in ('generation.json','engineering-inputs.json'):
    path=build/name;data=json.loads(path.read_text());witness[str(path)]=sha(path)
    for key in ('input_files','generated_files','files'):
        for p,h in data.get(key,{}).items():assert sha(p)==h,p;witness[p]=h
env=dict(os.environ,TMP=str(out/'temp'),TEMP=str(out/'temp'),PYTHONDONTWRITEBYTECODE='1')
p=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
(out/'lab-python.stdout.txt').write_text(p.stdout);(out/'lab-python.stderr.txt').write_text(p.stderr);assert p.returncode==0,p.stderr
count=re.search(r'Ran (\d+) tests',p.stderr);assert count and int(count[1])==expected_tests,p.stderr
for path,h in witness.items():assert sha(path)==h,path
candidate=build/'ps2x_vu1_bench.exe';identity=json.loads((build/'identity.json').read_text());assert sha(candidate)==identity[candidate.name]
result={'passed':True,'candidate_sha256':sha(candidate),'unit_sha256':identity['ps2x_tests.exe'],'full_report':str(full),'full_report_sha256':sha(full),'original_full_counts':report['counts'],'supplemental_lab_python':{'passed':expected_tests,'failed':0},'source_witness':witness,'orchestrator_sha256':sha(ROOT/'tools/lab_regression.py'),
        'scope':f'Aggregate gate: all engine/full jobs passed except an initially malformed new Python fixture; that fixture was corrected and the entire{expected_tests}-test Python suite rerun. The full invocation itself remains failed and is preserved. No candidate engine sources/binaries changed between checks. Hardware known mismatches remain separate.',
        'optimization_accepted':False,'game_acceptance_required':True}
(out/'report.json').write_text(json.dumps(result,indent=2));print(f'Aggregate engine gate passed;{expected_tests} corrected Python tests, original failed full report retained')

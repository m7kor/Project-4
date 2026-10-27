"""Verify existing pad clock implementation on a fresh Phase4-based game link."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];build=ROOT/'lab/architecture-input-01';out=ROOT/'artifacts/architecture/input-clock-01';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();identity=json.loads((build/'identity.json').read_text())
for name,h in identity['binaries'].items():assert sha(build/name)==h,name
for path,h in identity['files'].items():assert sha(path)==h,path
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
p=subprocess.run([str(build/'ps2x_tests.exe')],cwd=ROOT/'engines/project4',env=env,capture_output=True,text=True,timeout=120);(out/'unit.stdout.txt').write_text(p.stdout);(out/'unit.stderr.txt').write_text(p.stderr)
clean=re.sub(r'\x1b\[[0-9;]*m','',p.stdout);passed=re.search(r'Passed:\s*(\d+)',clean);failed=re.search(r'Failed:\s*(\d+)',clean);assert p.returncode==0 and passed and failed and int(failed[1])==0,p.stdout[-800:]
(out/'unit.json').write_text(json.dumps({'passed':int(passed[1]),'failed':int(failed[1]),'runner_sha256':identity['binaries']['ps2x_tests.exe'],'scope':'Fresh trace TUs on Phase4 reference; NOT AOT performance candidate'},indent=2));print('Trace runner C++ passed',passed[1],flush=True)
command=[sys.executable,ROOT/'tools/run_lab.py','architecture-input-clock-01','300',build/'ps2EntryRunner.exe',ROOT/'artifacts/phase4/game-acceptance/input.csv','replay','--fixture='+str(ROOT/'artifacts/runs/manual-20261024-112541-942897/guest/saves'),'--trace-pad','--audio-record','--vif-witness','--capture-every=60','--vu-capture']
p=subprocess.run(list(map(str,command)),cwd=ROOT,env=env,capture_output=True,text=True,timeout=330);(out/'driver.stdout.txt').write_text(p.stdout);(out/'driver.stderr.txt').write_text(p.stderr);assert p.returncode==0,p.stderr
run=ROOT/'artifacts/runs/architecture-input-clock-01';r=json.loads((run/'report.json').read_text());assert r['test_saves_unchanged'] and r['process_exit_observed']
pattern=r'\[pad trace\] stage=(replay|live|guest)\b.*?buttons=(\d+) lx=(\d+) ly=(\d+) rx=(\d+) ry=(\d+).*?host_ms=(\d+) ee_tick=(\d+)'
events=[{'stage':s,'state':list(map(int,[b,lx,ly,rx,ry])),'host_ms':int(host),'ee':int(tick)} for s,b,lx,ly,rx,ry,host,tick in re.findall(pattern,(run/'stderr.txt').read_text(errors='replace'))]
assert events and max(x['ee'] for x in events)>=5000 and all(a['ee']<=b['ee'] for a,b in zip(events,events[1:]))
(out/'native-events.json').write_text(json.dumps(events,indent=2))
result={'passed':True,'runner_sha256':r['runner_sha256'],'events':len(events),'first_ee':events[0]['ee'],'last_ee':events[-1]['ee'],'private_card_unchanged':True,'scope':'Actual native provider sampling clock, not just command-file acknowledgement; no room-transition claim','run':str(run)}
(out/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)

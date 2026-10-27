"""One quiet A/B pair, then ordinary scripted movement/aim/fire/menu input.

No RAM writes. The shared speed interval precedes all new gameplay inputs.
"""
from pathlib import Path
import csv,hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    out=ROOT/'artifacts/phase4/game-acceptance';out.mkdir(exist_ok=False)
    candidate=ROOT/'lab/phase4-game-03/ps2EntryRunner.exe';metadata=candidate.parent/'identity.json'
    start=time.monotonic()
    while not metadata.exists():
        if time.monotonic()-start>1800:raise TimeoutError('Final native-linked candidate not ready; no game launched')
        time.sleep(2)
    identity=json.loads(metadata.read_text());assert identity['native_modules']==135 and sha(candidate)==identity['binaries'][candidate.name]
    reference=ROOT/'lab/shared-link/ps2EntryRunner.exe';assert sha(reference)=='e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a'
    original=ROOT/'artifacts/navigation-inputs/load-private-save-v3.csv';tape=out/'input.csv'
    with original.open() as f:rows=list(csv.reader(f))
    # Masks also observed in the previous human-play trace. Navigation timing
    # is a new controlled scenario, not an exact replay of that human session.
    rows += [[4800,4890,65535,128,255,128,128],[4900,4990,65535,128,0,128,128],
             [5030,5100,63487,128,128,128,128],[5100,5130,47103,128,128,128,128],
             [5130,5170,63487,128,128,128,128],[5300,5310,65527,128,128,128,128],
             [5450,5460,65527,128,128,128,128]]
    with tape.open('w',newline='') as f:csv.writer(f).writerows(rows)
    fixture=ROOT/'artifacts/runs/manual-20261024-112541-942897/guest/saves';card=fixture/'cards/native-card-0.ps2';source_card_sha=sha(card)
    report={'runs':[],'input_sha256':sha(tape),'comparison_ee_interval':[3300,3900],'new_inputs_start_ee':4800,'scope':'One controlled cold A/B pair; no reproducible optimization gain claim. Candidate-only later controller scenario; no direct game-state writes.'}
    try:
        for label,binary,seconds in [('phase4-clean-base-01',reference,180),('phase4-candidate-01',candidate,300)]:
            run=ROOT/'artifacts/runs'/label;assert not run.exists()
            command=[sys.executable,ROOT/'tools/run_lab.py',label,str(seconds),binary,tape,'replay','--fixture='+str(fixture),'--capture-every=60','--audio-record','--vif-witness','--trace-pad']
            print('Controlled game run',label,flush=True);p=subprocess.run(command,cwd=ROOT,timeout=seconds+40)
            if p.returncode:raise RuntimeError('Owned run driver failed: '+label)
            result=json.loads((run/'report.json').read_text());report['runs'].append({'label':label,'runner_sha256':sha(binary),'report':str(run/'report.json'),'planned_timeout':result['terminated_at_planned_timeout'],'private_card_unchanged':result['test_saves_unchanged']})
            if not result['terminated_at_planned_timeout']:raise RuntimeError('Unexpected process termination: '+label)
            if not result['test_saves_unchanged']:raise RuntimeError('Controller scenario unexpectedly changed private card: '+label)
            if sha(card)!=source_card_sha:raise RuntimeError('Source private card changed')
            witness=run/'diagnostics/vif-fast-witness.json'
            if not witness.exists() or not json.loads(witness.read_text())['entered']:raise RuntimeError('Live VIF fast-path witness missing')
        report['completed']=True
    except Exception as exc:report['error']=str(exc);report['completed']=False
    finally:(out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True);return 0 if report['completed'] else 1
if __name__=='__main__':raise SystemExit(main())

"""Actual private fault injections at replay, identity and acceptance boundaries."""
from pathlib import Path
import argparse,copy,importlib.util,json,os,shutil,struct,subprocess,sys,time,types
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lab_regression as lab
import lab_game_acceptance as game
import vif_replay as vif

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();assert out.is_relative_to((ROOT/'artifacts').resolve());out.mkdir(parents=True,exist_ok=False)
    begin=time.monotonic();rows=[];env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
    env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env.get('PATH','')
    def record(name,detected,detail,scope):
        rows.append({'name':name,'detected':bool(detected),'detail':str(detail),'scope':scope});print(name,'detected' if detected else 'MISSED',flush=True)
    def rejects(name,callback,scope):
        try:callback()
        except Exception as exc:record(name,True,exc,scope)
        else:record(name,False,'No error was raised',scope)
    def run(label,command,timeout=20):
        p=subprocess.run(list(map(str,command)),cwd=out,env=env,capture_output=True,text=True,errors='replace',timeout=timeout)
        (out/(label+'.stdout.txt')).write_text(p.stdout);(out/(label+'.stderr.txt')).write_text(p.stderr)
        return p
    # A valid one-command prefix, sealed using the existing production format.
    trace=Path('C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands')
    meta=json.loads((trace/'manifest.jsonl').read_text().splitlines()[0]);meta['max_commands']=1
    command={'kind':'command','file':'command-00000000.bin','index':0,'sequence':0,'command':0}
    footer={'kind':'complete','commands':1,'sequences':1,'reason':'command-prefix-limit'}
    raw=(trace/'command-00000000.bin').read_bytes();header=struct.unpack_from('<16Q',raw)
    bench=ROOT/'lab/shared-link/ps2x_vu1_bench.exe'
    for label,mutate in [('vu-control',False),('vu-wrong-result',True)]:
        folder=out/label;folder.mkdir();data=bytearray(raw)
        if mutate:
            after=128+header[11]+header[14]+header[15];data[after+16]^=1
        (folder/'command-00000000.bin').write_bytes(data)
        (folder/'manifest.jsonl').write_text('\n'.join(json.dumps(x,separators=(',',':')) for x in (meta,command,footer))+'\n')
        p=run(label,[bench,'--commands',folder,'--repeat','1'])
        if not mutate:record(label,p.returncode==0,p.stdout[-300:],'Positive control: actual native golden replay')
        else:record(label,p.returncode!=0 and 'recorded result differs at command 0' in p.stderr,p.stderr,'One expected VF bit flipped in a PRIVATE copy; production VU comparison executed')
    # Executable bytes differ, but its declared identity is deliberately unchanged.
    candidate=ROOT/'lab/normal-link';capsule=out/'bad-executable';capsule.mkdir()
    shutil.copy2(candidate/'ps2x_tests.exe',capsule/'ps2x_tests.exe');data=bytearray((candidate/'ps2x_vu1_bench.exe').read_bytes());data[0]^=1;(capsule/'ps2x_vu1_bench.exe').write_bytes(data)
    shutil.copy2(candidate/'identity.json',capsule/'identity.json')
    def suite():
        s=lab.Suite.__new__(lab.Suite);s.args=types.SimpleNamespace(vu_source=ROOT/'artifacts/experiments/vu-normal-flags/candidate-core.cpp',benchmark=False,changed=[]);s.report={'hashes':{},'selected_groups':['vu']};return s
    rejects('executable-byte-mismatch',lambda:suite().bind(capsule),'Actual executable copy mutated; rejected before execution')
    # Mutate an isolated header copy, not any real engine header or build tree.
    copyroot=out/'dependency-root';vu=copyroot/'engines/project4/ps2xRuntime/src/lib/vu';vu.mkdir(parents=True)
    original=ROOT/'engines/project4/ps2xRuntime/src/lib/vu'
    for name in ('ps2_vu1_command_trace.inl','ps2_vu1_detail.h'):shutil.copy2(original/name,vu/name)
    with (vu/'ps2_vu1_detail.h').open('ab') as stream:stream.write(b'\n// controlled dependency mutation\n')
    oldroot=lab.ROOT
    try:
        lab.ROOT=copyroot
        rejects('source-header-dependency',lambda:suite().bind(candidate),'Actual isolated header changed; normal build metadata must become stale')
    finally:lab.ROOT=oldroot
    # Exercise the real hardware-output comparator with one altered output line.
    module=ROOT/'lab/zmbor-phase2/src/tools/hwtest/hwtest.py'
    spec=importlib.util.spec_from_file_location('phase2_hw',module);hw=importlib.util.module_from_spec(spec);spec.loader.exec_module(hw)
    expected=ROOT/'artifacts/phase2/hardware-inputs/cpu_ee_alu.expected';lines=expected.read_text().splitlines();lines[1]+=' MUTATED'
    payload=out/'mutated-tty.txt';payload.write_text('\n'.join(lines)+'\n');stub=out/'fault-output.py';stub.write_text('from pathlib import Path\nimport os\ntext=Path('+repr(str(payload))+').read_text()\nPath(os.environ["PS2X_TTY_LOG"]).write_text(text)\nprint(text,end="")\n')
    target=out/'hardware-output';target.mkdir()
    p=run('unexpected-hardware-output',[sys.executable,module,'run','--runner',sys.executable,'--elf',stub,'--expected',expected,'--result',target/'result.json','--timeout','5'])
    result=json.loads((target/'result.json').read_text());record('unexpected-hardware-output',p.returncode!=0 and result['status']=='MISMATCH',result.get('diff_head'),'Output-boundary injection into the actual hardware comparator; .expected untouched')
    # Valid native VIF state compared with a corrupted oracle field.
    golden=json.loads((ROOT/'artifacts/phase2/vif-direct/golden.json').read_text());wrong=copy.deepcopy(golden['normal']);wrong[2]['vram']='0'*16
    difference=vif.first_divergence(golden['normal'],wrong);record('vif-memory-effect',difference and difference['field']=='vram',difference,'Recorded VRAM effect altered at one event')
    truncated=out/'incomplete-vif.bin';truncated.write_bytes((ROOT/'artifacts/phase2/vif-direct/fixture.bin').read_bytes()[:-4])
    rejects('incomplete-subsystem-capture',lambda:vif.read_events(truncated),'Actual VIF fixture truncated before its last event completed')
    # Check real captured PNGs against their diagnostics without launching RE4.
    source=ROOT/'artifacts/runs/acceptance-20261024-173321-636541'
    states=[json.loads(s) for s in (source/'diagnostics/state.jsonl').read_text().splitlines() if json.loads(s).get('host_frame')][:4]
    for label,mutation in [('capture-control',None),('missing-frame','missing'),('incomplete-png','truncated')]:
        folder=out/label/'diagnostics';folder.mkdir(parents=True)
        for s in states:
            name=f"frame-{s['tick']}.png";data=(source/'diagnostics'/name).read_bytes()
            if mutation=='missing' and s is states[1]:continue
            if mutation=='truncated' and s is states[1]:data=data[:40]
            (folder/name).write_bytes(data)
        (folder/'state.jsonl').write_text('\n'.join(json.dumps(s) for s in states)+'\n')
        if mutation:rejects(label,lambda f=folder:game.validate_capture_files(f.parent),'Actual captured image set mutated; no game launch')
        else:
            try:game.validate_capture_files(folder.parent);record(label,True,'Complete positive capture control','Real captured image control')
            except Exception as exc:record(label,False,exc,'Real captured image control')
    metrics=json.loads((ROOT/'artifacts/regression/20261024T093812.072198Z/report.json').read_text())['performance']['rows'];metrics=copy.deepcopy(metrics)
    for pair in range(7):
        a=next(r for r in metrics if r['pair']==pair and r['label']=='reference');b=next(r for r in metrics if r['pair']==pair and r['label']=='candidate');b['ns_per_cycle']=a['ns_per_cycle']*1.25
    changes=lab.analyze_pairs(metrics,7);decision=lab.performance_decision(changes)
    record('performance-regression',lab.gate_exit(True,True,decision)==2 and decision=='reject-consistently-slower',changes,'Measured-result boundary mutation: seven candidate costs increased25%; no claim of a new runtime benchmark')
    rejects('invalid-integration-configuration',lambda:game.validate_spec({'reason':'release-smoke','hypothesis':'A controlled invalid integration configuration','seconds':901,'success':{'minimum_ee_vsync':3300}}),'Configuration rejected without launching any process')
    invalid=json.loads((ROOT/'tests/specs/typewriter-smoke.example.json').read_text());invalid['runner_sha256']='0'*64
    specfile=out/'invalid-runner-spec.json';specfile.write_text(json.dumps(invalid))
    p=run('live-identity-refusal',[sys.executable,ROOT/'tools/lab_game_acceptance.py','--spec',specfile,'--out',out/'live-identity-refusal','--allow-game'])
    refusal=json.loads((out/'live-identity-refusal/report.json').read_text())
    record('live-prelaunch-error-report',p.returncode!=0 and not refusal['real_re4_launched'] and 'Identity mismatch' in refusal['first_divergence'],refusal['first_divergence'],'Actual acceptance CLI rejected bad identity and produced a complete error report without a game launch')
    # Real timeout handling in the orchestrator, with a harmless owned child.
    args2=types.SimpleNamespace(changed=[],benchmark=False);s=lab.Suite(args2)
    row,_,_=s.run('controlled-timeout',[sys.executable,'-c','import time;time.sleep(2)'],timeout=.05,scope='Owned synthetic child timeout, no game')
    record('timeout-handling',row['status']=='failed' and row['exit_code']==124,row,'Actual timed-out child; report saved')
    report={'passed':all(r['detected'] for r in rows),'checks':rows,'seconds':time.monotonic()-begin,'real_re4_launched':False,'scope':'Private mutation copies or declared result-boundary injections. No original sources, expected outputs, accepted executables or saves altered.'}
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':report['passed'],'detected':sum(r['detected'] for r in rows),'total':len(rows)}))
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

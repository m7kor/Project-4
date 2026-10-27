"""Explicit, bounded RE4 acceptance. Not imported by offline tests to launch games."""
import argparse,csv,datetime,hashlib,json,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REASONS={'shared-subsystem','optimization-after-offline-gates','new-gameplay','release-smoke','rendering-audio-save-load'}
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def validate_spec(spec):
    if spec.get('reason') not in REASONS:raise ValueError('An allowed acceptance reason is required')
    if len(spec.get('hypothesis',''))<16:raise ValueError('Write a concrete hypothesis')
    seconds=spec.get('seconds')
    if type(seconds) is not int or not 30<=seconds<=900:raise ValueError('Use30..900 bounded seconds')
    success=spec.get('success',{})
    if type(success.get('minimum_ee_vsync')) is not int or success['minimum_ee_vsync']<1:raise ValueError('Require measured EE progress')
    if 'room' in success and (type(success['room']) is not int or not 0<=success['room']<=65535):raise ValueError('Invalid room id')
    if spec['reason']=='optimization-after-offline-gates' and not spec.get('offline_gate_report'):raise ValueError('Optimization requires an offline correctness/performance gate report')
    return spec
def consumption(log,events):
    pattern=r'\[pad trace\] stage=replay .*?buttons=(\d+) lx=(\d+) ly=(\d+) rx=(\d+) ry=(\d+).*?ee_tick=(\d+)'
    count=active=0
    for m in re.finditer(pattern,log):
        values=tuple(map(int,m.groups()[:5]));tick=int(m[6]);expected=(65535,128,128,128,128)
        for event in events:
            if event[0]<=tick<event[1]:expected=tuple(event[2:]);break
        if values!=expected:raise ValueError(f'First native input divergence at EE{tick}: {values} vs {expected}')
        count+=1;active+=values!= (65535,128,128,128,128)
    if not active:raise ValueError('No observed non-neutral native input consumption')
    return {'matched_state_changes':count,'non_neutral_changes':active,'scope':'Native consumption, not by itself proof of game action'}
def validate_capture_files(run):
    from PIL import Image
    run=Path(run);statefile=run/'diagnostics/state.jsonl'
    states=[json.loads(s) for s in statefile.read_text().splitlines()]
    if not states:raise ValueError('Missing runtime diagnostics')
    for a,b in zip(states,states[1:]):
        if b['tick']<=a['tick'] or b['elapsed_seconds']<a['elapsed_seconds'] or b['ee_vsync_tick']<a['ee_vsync_tick']:
            raise ValueError('Runtime diagnostics regress or duplicate capture identity')
    expected={f"frame-{s['tick']}.png" for s in states if s.get('host_frame')}
    frames=sorted((run/'diagnostics').glob('frame-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
    actual={p.name for p in frames}
    if len(frames)<3 or not expected:raise ValueError('Insufficient visual evidence')
    if expected!=actual:raise ValueError('Missing or unexpected frame capture: '+str(sorted(expected^actual)[:4]))
    for frame in frames:
        with Image.open(frame) as im:im.verify()
    with Image.open(frames[-1]) as im:
        if all(hi==0 for lo,hi in im.convert('RGB').getextrema()):raise ValueError('Final frame entirely black')
    return states,{p.name:digest(p) for p in frames}
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--allow-game',action='store_true');args=parser.parse_args()
    if not args.allow_game:parser.error('Explicit --allow-game is required')
    out=args.out.resolve();assert out.is_relative_to((ROOT/'artifacts').resolve());out.mkdir(parents=True,exist_ok=False)
    result={'passed':False,'real_re4_launched':False,'unverified':['No full campaign or subjective AV acceptance from this scoped run']};game=None;run=None
    try:
        spec=validate_spec(json.loads(args.spec.read_text()));result['spec']=spec
        def owned(key):
            p=(ROOT/spec[key]).resolve(strict=True)
            if not p.is_relative_to(ROOT.resolve()):raise ValueError('Acceptance inputs must be owned by the lab: '+key)
            return p
        runner=owned('runner');tape=owned('input');fixture=owned('fixture');card=fixture/'cards/native-card-0.ps2'
        for name,p in [('runner',runner),('input',tape),('card',card)]:
            actual=digest(p);result.setdefault('hashes',{})[str(p)]=actual
            if actual!=spec[name+'_sha256']:raise ValueError('Identity mismatch: '+name)
        if spec['reason']=='optimization-after-offline-gates':
            gate=json.loads(owned('offline_gate_report').read_text())
            if not gate.get('passed') or (gate.get('performance') or {}).get('median_cost_reduction_percent',0)<=0:raise ValueError('Offline optimization gates did not pass')
        import psutil
        if any((p.info['name'] or '').lower()=='ps2entryrunner.exe' for p in psutil.process_iter(['name'])):raise ValueError('Preserve existing game session; acceptance refuses concurrent RE4')
        label='acceptance-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f');run=ROOT/'artifacts/runs'/label
        command=[sys.executable,str(ROOT/'tools/run_lab.py'),label,str(spec['seconds']),str(runner),str(tape),'replay','--fixture='+str(fixture),'--capture-every=60','--trace-pad','--stream-trace','--audio-record']
        with (out/'driver.log').open('x') as log:game=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+spec['seconds']+30;observed=False
        while time.monotonic()<deadline and game.poll() is None:
            if (run/'identity.json').exists():
                try:result['real_re4_launched']=bool(json.loads((run/'identity.json').read_text()).get('pid'))
                except (OSError,ValueError):pass  # identity is populated just after launch
            try:state=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1])
            except (OSError,ValueError,IndexError):time.sleep(.25);continue
            if 'room' in spec['success'] and not observed and state['ee_vsync_tick']>=spec['success']['minimum_ee_vsync']:
                identity=json.loads((run/'identity.json').read_text());inp=ROOT/'artifacts/navigation-inputs'
                cmd=[sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py'),'--pid',str(identity['pid']),'--run',str(run),'--identity',str(run/'identity.json'),'--exe',str(run/'guest/ps2EntryRunner.exe'),'--elf',str(run/'guest/SLUS_211.34'),'--exports',str(inp/'player-exports.json'),'--room-exports',str(inp/'room-exports.json'),'--samples','3','--interval','1','--out',str(out/'room.json')]
                p=subprocess.run(cmd,capture_output=True,text=True,timeout=30);(out/'room-observer.log').write_text(p.stdout+p.stderr);observed=True
                if p.returncode:raise ValueError('Room observer failed with exit '+str(p.returncode)+': '+p.stderr[-500:])
            time.sleep(.25)
        if game.poll() is None:
            (run/'stop-request.json').write_text(json.dumps({'reason':'Acceptance time bound'}));game.wait(timeout=15)
        result['run']=str(run);report=json.loads((run/'report.json').read_text());result['runtime_report']=report
        result['real_re4_launched']=bool(report.get('pid'))
        if report['exit_code']!=0 and not report['terminated_at_planned_timeout']:raise ValueError('Unexpected game process failure')
        if report['runner_sha256']!=spec['runner_sha256'] or report['input_sha256']!=spec['input_sha256']:raise ValueError('Runtime identity differs')
        if report['elf_sha256']!='465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad':raise ValueError('Wrong RE4 ELF revision')
        if not report['test_saves_unchanged']:raise ValueError('Acceptance fixture changed; explicit save-progress test needs separate evidence')
        if digest(card)!=spec['card_sha256']:raise ValueError('Source private fixture changed during acceptance')
        states,frames=validate_capture_files(run)
        if states[-1]['ee_vsync_tick']<spec['success']['minimum_ee_vsync']:raise ValueError('Required game progress not reached')
        log=(run/'stderr.txt').read_text(errors='replace')
        faults=re.findall(r'guest-branch:missing-target|runtime exception|access violation|\[terminate\]|VK_ERROR',log,re.I)
        if faults:raise ValueError('Runtime failure signatures: '+str(faults[:3]))
        with tape.open() as stream:events=[list(map(int,r)) for r in list(csv.reader(stream))[1:]]
        result['input_consumption']=consumption(log,events)
        result['frames']=frames
        if 'room' in spec['success']:
            memory=json.loads((out/'room.json').read_text());rooms=[s['room_state']['room_dispatch_argument_u16'] for s in memory['observations']]
            if not memory['completed'] or rooms!=[spec['success']['room']]*3:raise ValueError('Room criterion not met')
            if not all(s['room_state'].get('game_pointer_stable') for s in memory['observations']):raise ValueError('Unstable RoomData observation')
            result['room_observations']=rooms
        result['passed']=True
    except Exception as exc:result['first_divergence']=str(exc);print(str(exc),file=sys.stderr)
    finally:
        if game and game.poll() is None:
            if run and run.exists():(run/'stop-request.json').write_text(json.dumps({'reason':'Acceptance driver failed; preserve evidence'}))
            try:game.wait(timeout=15)
            except subprocess.TimeoutExpired:result['unverified'].append('Owned driver still pending bounded runtime shutdown')
        if run is not None:
            result['run']=str(run)
            if (run/'report.json').exists() and 'runtime_report' not in result:
                try:
                    result['runtime_report']=json.loads((run/'report.json').read_text())
                    result['real_re4_launched']=bool(result['runtime_report'].get('pid'))
                except (OSError,ValueError):pass
        (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

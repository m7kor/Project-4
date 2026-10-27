"""Bounded owned RE4 run with private ELF, binaries and test saves."""
from pathlib import Path
import sys, os, shutil, json, time, subprocess, hashlib
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('C:/Project/PS2redmption')
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def binary_mode_option(arguments,option):
    values=[a.split('=',1)[1] for a in arguments if a.startswith(option+'=')]
    if len(values)>1 or (values and values[0] not in ('0','1')):
        raise ValueError('Use one explicit '+option+'=0 or1')
    return values[0] if values else None

def pipeline_index_option(arguments):return binary_mode_option(arguments,'--vu-pipeline-index')
def main():
    pipeline_index=pipeline_index_option(sys.argv[6:])
    vector_retire=binary_mode_option(sys.argv[6:],'--vu-vector-retire')
    fmac_classify=binary_mode_option(sys.argv[6:],'--vu-fmac-classify')
    aot_coverage=binary_mode_option(sys.argv[6:],'--vu-aot-coverage')
    label=sys.argv[1] if len(sys.argv)>1 else 'baseline'
    seconds=float(sys.argv[2]) if len(sys.argv)>2 else 180
    mode=sys.argv[5] if len(sys.argv)>5 else 'replay'
    assert mode in ('replay','live','manual')
    assert label.replace('-','').isalnum() and 0<seconds<=(3600 if mode=='manual' else 900)
    run=ROOT/'artifacts/runs'/label;run.mkdir(parents=True,exist_ok=False)
    guest=run/'guest';guest.mkdir();binary=guest/'ps2EntryRunner.exe'
    original=Path(sys.argv[3]).resolve() if len(sys.argv)>3 else SOURCE/'core/out/build/ps2xRuntime/ps2EntryRunner.exe'
    shutil.copy2(original,binary)
    for p in (SOURCE/'Resident Evil 4').glob('*.dll'):shutil.copy2(p,guest/p.name)
    game=SOURCE/'game/Resident Evil 4 (USA)'
    for name in ('SLUS_211.34','SYSTEM.CNF','ioprp.img','modules.dat'):shutil.copy2(game/name,guest/name)
    # cdvd opens these assets read-only; junction avoids copying 4.4 GB.
    subprocess.run(['powershell','-NoProfile','-Command',
                    f"New-Item -ItemType Junction -Path '{guest/'data'}' -Target '{game/'data'}' | Out-Null"],check=True)
    fixture_arg=next((a.split('=',1)[1] for a in sys.argv[6:] if a.startswith('--fixture=')),None)
    fixture=Path(fixture_arg).resolve() if fixture_arg else SOURCE/'artifacts/runs/pad-movement-20261018/guest/saves'
    if fixture_arg:
        assert fixture.is_relative_to((ROOT/'artifacts').resolve())
        assert all(p.resolve().is_relative_to((ROOT/'artifacts').resolve()) for p in fixture.rglob('*'))
    assert fixture.is_dir() and 'artifacts' in fixture.parts
    shutil.copytree(fixture,guest/'saves')
    saves=lambda:{str(p.relative_to(guest/'saves')):digest(p) for p in (guest/'saves').rglob('*') if p.is_file()}
    tape=run/'input.csv'
    if mode!='manual':
        tape_source=Path(sys.argv[4]).resolve() if len(sys.argv)>4 else SOURCE/'artifacts/verification/review-20261018-feedback-startup-v13.csv'
        shutil.copy2(tape_source,tape)
    env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
    settings=dict(PS2X_IOP_SIO2_NATIVE='1',PS2X_IOP_SPU2_NATIVE='1',PS2X_SIF_RPC_ASYNC='0x80000400',
                  PS2X_GS_BACKEND='parallel',PS2X_GS_THREAD='1',PS2X_PAD_FRESH_GLFW='0',
                  PS2X_NATIVE_PAD_REPLAY=str(tape),PS2X_CAPTURE_EVERY='300',PS2X_CAPTURE_DIR=str(run/'diagnostics'),
                  PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VIF1_FAST_UNPACK='1')
    if mode=='manual':
        settings.pop('PS2X_NATIVE_PAD_REPLAY')
        settings['PS2X_TRACE_PAD']='1'
    capture_every=int(next((a.split('=',1)[1] for a in sys.argv[6:] if a.startswith('--capture-every=')),'300'))
    assert capture_every in (60,300)
    settings['PS2X_CAPTURE_EVERY']=str(capture_every)
    if pipeline_index is not None:
        settings['PS2X_VU1_PIPELINE_INDEX']=pipeline_index
    if vector_retire is not None:
        settings['PS2X_VU1_VECTOR_RETIRE']=vector_retire
    if fmac_classify is not None:
        settings['PS2X_VU1_FMAC_CLASSIFY']=fmac_classify
    if aot_coverage is not None:
        settings['PS2X_VU1_AOT_COVERAGE']=aot_coverage
    if '--stream-trace' in sys.argv[6:]:
        settings['PS2X_TRACE_CDVD']='1'
    if '--trace-pad' in sys.argv[6:]:
        settings['PS2X_TRACE_PAD']='1'
    if '--physical-handoff' in sys.argv[6:]:
        assert mode=='replay', 'Physical handoff requires replay without live ownership'
        settings['PS2X_NATIVE_PAD_REPLAY_HANDOFF']='1'
    if '--audio-record' in sys.argv[6:]:
        (run/'diagnostics').mkdir(exist_ok=True)
        settings['PS2X_AUDIO_WAV']=str(run/'diagnostics/audio')
    if '--vif-witness' in sys.argv[6:]:
        (run/'diagnostics').mkdir(exist_ok=True)
        settings['PS2X_VIF1_FAST_WITNESS']=str(run/'diagnostics/vif-fast-witness.json')
    if '--vu-profile' in sys.argv[6:]:
        (run/'diagnostics').mkdir(exist_ok=True)
        settings.update(PS2X_PROFILE_VU1_DIR=str(run/'diagnostics/vu-profile'),
                        PS2X_PROFILE_VU1_FROM='3300',PS2X_PROFILE_VU1_INTERVAL='60')
    if '--vu-capture' in sys.argv[6:]:
        (run/'diagnostics').mkdir(exist_ok=True)
        settings.update(PS2X_VU1_COMMANDS_DIR=str(run/'diagnostics/vu-commands'),
                        PS2X_VU1_COMMANDS_FROM='3300',PS2X_VU1_COMMANDS_SEQUENCES='128',
                        PS2X_VU1_COMMANDS_LIMIT='1024')
    env.update(settings)
    if mode=='live':
        settings['PS2X_NATIVE_PAD_LIVE']=str(run/'live-pad.csv')
        env['PS2X_NATIVE_PAD_LIVE']=settings['PS2X_NATIVE_PAD_LIVE']
    identity=dict(scope='Bounded real game diagnostic; no gameplay claim from process liveness',input_mode=mode,runner_sha256=digest(binary),
                  elf_sha256=digest(guest/'SLUS_211.34'),input_sha256=digest(tape) if mode!='manual' else None,settings=settings,
                  test_save_source=str(fixture),saves_before=saves(),asset_access='CDVD read-only through local data junction',
                  command=[str(binary),str(guest/'SLUS_211.34')])
    (run/'identity.json').write_text(json.dumps(identity,indent=2))
    begin=time.monotonic();peak=0;last_cpu=None
    try:import psutil
    except ImportError:psutil=None
    with (run/'stdout.txt').open('xb') as out,(run/'stderr.txt').open('xb') as err:
        p=subprocess.Popen(identity['command'],cwd=guest,env=env,stdout=out,stderr=err,creationflags=0x08000000)
        print('Owned run',label,'PID',p.pid,flush=True)
        identity['pid']=p.pid
        (run/'identity.json').write_text(json.dumps(identity,indent=2))
        while p.poll() is None and time.monotonic()-begin<seconds and not (run/'stop-request.json').exists():
            if psutil:
                try:
                    process=psutil.Process(p.pid);peak=max(peak,process.memory_info().rss)
                    cpu=process.cpu_times();last_cpu={'user_seconds':cpu.user,'system_seconds':cpu.system,'sampled_at_seconds':time.monotonic()-begin}
                except psutil.Error:pass
            time.sleep(.5)
        alive=p.poll() is None
        requested_stop=(run/'stop-request.json').exists()
        timeout=alive and not requested_stop
        if alive:p.terminate()
        try:code=p.wait(timeout=10)
        except subprocess.TimeoutExpired:p.kill();code=p.wait()
    identity.update(exit_code=code,terminated_at_planned_timeout=timeout,seconds=time.monotonic()-begin,
                    peak_rss_bytes=peak,saves_after=saves(),process_exit_observed=True,terminated_at_requested_stop=requested_stop)
    identity['test_saves_unchanged']=identity['saves_before']==identity['saves_after']
    identity['host_cpu_last_sample']=last_cpu
    (run/'report.json').write_text(json.dumps(identity,indent=2))
    print(json.dumps({k:identity[k] for k in ('exit_code','seconds','peak_rss_bytes','test_saves_unchanged','terminated_at_planned_timeout')}),flush=True)
if __name__=='__main__':main()

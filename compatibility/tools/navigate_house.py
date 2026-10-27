"""Reproduce known gameplay then use the existing bounded native-input controller.

All writes are host-side input commands in an owned lab run. RAM observers remain
read-only; this does not edit game state or assert encounter/campaign acceptance.
"""
from pathlib import Path
import subprocess,sys,json,time
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/house-navigation'
inputs=ROOT/'artifacts/navigation-inputs'
exe=ROOT/'lab/fusion-link/ps2EntryRunner.exe'
cmd=[sys.executable,str(ROOT/'tools/run_lab.py'),'house-navigation','900',str(exe),
     'C:/Project/PS2redmption/artifacts/verification/review-20261018-house-right-room-controls-v9.csv','live']
log=ROOT/'artifacts/house-navigation-driver.log'
with log.open('x') as output:
    game=subprocess.Popen(cmd,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    print('Owned navigation driver',game.pid,flush=True)
    deadline=time.monotonic()+740
    while game.poll() is None and time.monotonic()<deadline:
        try:
            states=(run/'diagnostics/state.jsonl').read_text().splitlines()
            state=json.loads(states[-1])
            if state['ee_vsync_tick']>=10450:break
        except (OSError,ValueError,IndexError):pass
        time.sleep(.5)
    else:raise RuntimeError('Known startup did not reach navigation gate; no live input issued')
    identity=json.loads((run/'identity.json').read_text())
    pid=identity['pid'];reader=ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py'
    observe=[sys.executable,str(reader),'--pid',str(pid),'--run',str(run),'--identity',str(run/'identity.json'),
             '--exe',str(run/'guest/ps2EntryRunner.exe'),'--elf',str(run/'guest/SLUS_211.34'),
             '--exports',str(inputs/'player-exports.json'),'--room-exports',str(inputs/'room-exports.json'),
             '--movie-witness',str(inputs/'movie-witness.json'),'--out',str(run/'navigation-start.json')]
    subprocess.run(observe,cwd=ROOT,check=True)
    initial=json.loads((run/'navigation-start.json').read_text());assert initial['completed'] and initial['pid']==pid
    activity=dict(scope='Bounded native-controller navigation using read-only poses; not a performance run or campaign proof',pid=pid,
                  start_ee=initial['observations'][-1]['last_capture_state']['ee_vsync_tick'],maximum_commands=24,
                  maximum_controller_seconds=300,experimental_geometry=True)
    (run/'external-activity.json').write_text(json.dumps(activity,indent=2))
    print('Startup gate reached. Starting bounded four-waypoint controller.',flush=True)
    control=[sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_feedback_route.py'),
             '--run',str(run),'--lab-owner',str(run),'--pid',str(pid),'--rdram-base',initial['rdram_base'],
             '--exe',str(run/'guest/ps2EntryRunner.exe'),'--elf',str(run/'guest/SLUS_211.34'),
             '--exports',str(inputs/'player-exports.json'),'--room-exports',str(inputs/'room-exports.json'),
             '--movie-witness',str(inputs/'movie-witness.json'),'--route',str(inputs/'house-route.json'),
             '--timeout','300','--max-commands','24','--label','house-feedback']
    with (run/'controller.log').open('x') as f:
        result=subprocess.run(control,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=330)
    print('Controller ended',result.returncode,'; inspect house-feedback/summary.json and images.',flush=True)
    (run/'controller-result.json').write_text(json.dumps(dict(exit_code=result.returncode),indent=2))
    game.wait()
print('Owned navigation runner ended; final review required.',flush=True)

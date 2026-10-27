"""Bounded native-input route from the user's private save; never writes guest RAM."""
from pathlib import Path
import json,sys,subprocess,time,struct,math
ROOT=Path(__file__).resolve().parents[1]
assert (ROOT/'artifacts/experiments/vu-shared-regions/game-comparison-frames.json').exists(), 'Finish timing comparisons before navigation'
run=ROOT/'artifacts/runs/regions-route'
inputs=ROOT/'artifacts/navigation-inputs'
source=ROOT/'artifacts/runs/manual-play-02/ram-route-04.json'
points=[];last=None
for sample in json.loads(source.read_text())['observations']:
    pos=struct.unpack_from('<3f',bytes.fromhex(sample['player_bytes_hex']),192)
    if last is None or math.hypot(pos[0]-last[0],pos[2]-last[2])>=2400:
        points.append({'name':'observed-'+str(len(points)),'x':pos[0],'z':pos[2],
            'evidence':'Observed user pose in ram-route-04; straight-line connector remains experimental'})
        last=pos
points.append({'name':'observed-dog-area','x':-29346,'z':-13411,
    'evidence':'Observed first pose in ram-route-05; connector from prior samples unverified'})
route=inputs/'post-save-observed-route.json'
assert not route.exists()
route.write_text(json.dumps({'schema':1,'expected_room':256,'tolerance':500,
    'scope':'Observed user path with experimental connectors; stop on room change or two stalled moves','waypoints':points},indent=2))
command=[sys.executable,str(ROOT/'tools/run_lab.py'),'regions-route','900',str(ROOT/'lab/shared-link/ps2EntryRunner.exe'),
    str(inputs/'load-private-save-v3.csv'),'live','--fixture='+str(ROOT/'artifacts/runs/manual-play-02/guest/saves'),'--capture-every=60']
with (ROOT/'artifacts/regions-route-driver.log').open('x') as log:
    game=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    deadline=time.monotonic()+300
    while time.monotonic()<deadline and game.poll() is None:
        try:
            row=json.loads((run/'diagnostics/state.jsonl').read_text().splitlines()[-1])
            if row['ee_vsync_tick']>=3400:break
        except (OSError,ValueError,IndexError):pass
        time.sleep(.5)
    else:raise RuntimeError('Save startup gate not reached; no live input issued')
    identity=json.loads((run/'identity.json').read_text());pid=identity['pid']
    read=[sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py'),'--pid',str(pid),
        '--run',str(run),'--identity',str(run/'identity.json'),'--exe',str(run/'guest/ps2EntryRunner.exe'),
        '--elf',str(run/'guest/SLUS_211.34'),'--exports',str(inputs/'player-exports.json'),
        '--room-exports',str(inputs/'room-exports.json'),'--movie-witness',str(inputs/'movie-witness.json'),'--out',str(run/'route-start.json')]
    subprocess.run(read,cwd=ROOT,check=True)
    observation=json.loads((run/'route-start.json').read_text());assert observation['completed']
    (run/'external-activity.json').write_text(json.dumps({'scope':'Native input navigation with read-only RAM, not a timing run','maximum_commands':48,'maximum_seconds':600},indent=2))
    controller=[sys.executable,str(ROOT/'reference-tools/tools/diagnostics/re4_feedback_route.py'),
        '--run',str(run),'--lab-owner',str(run),'--pid',str(pid),'--rdram-base',observation['rdram_base'],
        '--exe',str(run/'guest/ps2EntryRunner.exe'),'--elf',str(run/'guest/SLUS_211.34'),
        '--exports',str(inputs/'player-exports.json'),'--room-exports',str(inputs/'room-exports.json'),
        '--movie-witness',str(inputs/'movie-witness.json'),'--route',str(route),
        '--timeout','600','--max-commands','48','--label','post-save-feedback']
    print('Loaded private save; bounded observed route starting',flush=True)
    with (run/'controller.log').open('x') as output:
        result=subprocess.run(controller,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=630)
    print('Route controller ended',result.returncode,'; inspect pose and images before further input',flush=True)
    game.wait()

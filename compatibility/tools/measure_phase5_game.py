"""Seven bounded alternating RE4 pairs, only after net offline benefit and gates."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time,statistics
import psutil
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reference-tools/tools/diagnostics'))
from game_speed_compare import endpoint,HZ
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def last_state(path):
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-16384));rows=stream.read().splitlines()
    if not rows:
        raise ValueError('Diagnostics file has no complete sample yet')
    return json.loads(rows[-1])
def main():
    timing=json.loads((ROOT/'artifacts/phase5/timing-04/report.json').read_text())
    if not timing['all_pairs_improved'] or timing['median_cost_reduction_percent']<=0:
        raise RuntimeError('No reliable net VU gain; do not launch a game benchmark')
    gate_path=Path(sys.argv[1]);gate=json.loads(gate_path.read_text());assert gate['passed'] and gate['vu_fmac_classify']=='1'
    baseline=ROOT/'lab/phase4-game-03/ps2EntryRunner.exe';candidate=ROOT/'lab/phase5-game-02/ps2EntryRunner.exe'
    identity=json.loads((candidate.parent/'identity.json').read_text());assert sha(candidate)==identity['runner_sha256']
    assert sha(baseline)=='fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53'
    out=ROOT/'artifacts/phase5/game-performance-01';out.mkdir(exist_ok=False)
    tape=ROOT/'artifacts/phase4/game-acceptance/input.csv';fixture=ROOT/'artifacts/runs/manual-20261024-112541-942897/guest/saves'
    result={'runs':[],'input_sha256':sha(tape),'from_ee':3300,'to_ee':3900,'scope':'Seven alternating pairs. Monotonic sampled guest progress. Last pair extends to ordinary controls; observer activity must start after the measurement interval.'}
    try:
        for pair in range(7):
            for mode in (('0','1') if pair%2==0 else ('1','0')):
                assert sha(candidate)==identity['runner_sha256']
                for process in psutil.process_iter(['name']):
                    if (process.info['name'] or '').lower() in ('clang-cl.exe','lld-link.exe','cl.exe','link.exe','ps2entryrunner.exe'):
                        raise RuntimeError('Competing build or game process; controlled test refused')
                label=f'phase5-perf-{pair}-{mode}';run=ROOT/'artifacts/runs'/label
                seconds=360 if pair==6 else 180
                command=[sys.executable,ROOT/'tools/run_lab.py',label,str(seconds),candidate if mode=='1' else baseline,tape,'replay','--fixture='+str(fixture),'--capture-every=60','--audio-record','--vif-witness','--trace-pad','--vu-fmac-classify='+mode]
                with (out/(label+'.driver.log')).open('x') as log:
                    driver=subprocess.Popen(list(map(str,command)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                    meters=[];stop_sent=False;observer=None;profiler=None;start=time.monotonic();last_meter=-1
                    while driver.poll() is None and time.monotonic()-start<seconds+40:
                        try:
                            state=last_state(run/'diagnostics/state.jsonl')
                            if pair==6 and state['ee_vsync_tick']>=4100 and profiler is None:
                                profile_log=(out/(label+'.profile.txt')).open('x')
                                pid=json.loads((run/'identity.json').read_text())['pid']
                                (out/(label+'.profile-start.json')).write_text(json.dumps({'ee':state['ee_vsync_tick'],'elapsed':state['elapsed_seconds'],'scope':'After the3300..3900 performance window, both modes sampled identically'}))
                                profiler=subprocess.Popen([sys.executable,str(ROOT/'reference-tools/tools/diagnostics/hot_thread_sampler.py'),'--pid',str(pid),'--expected-exe',str(run/'guest/ps2EntryRunner.exe'),'--seconds','10','--rate','100','--depth','12','--top','40'],cwd=ROOT,stdout=profile_log,stderr=subprocess.STDOUT)
                            if pair==6 and state['ee_vsync_tick']>=4500 and observer is None:
                                observer_log=(out/(label+'.observer.log')).open('x')
                                observer=subprocess.Popen([sys.executable,str(ROOT/'tools/observe_phase5_ammo.py'),str(run)],cwd=ROOT,stdout=observer_log,stderr=subprocess.STDOUT)
                            if state['ee_vsync_tick']>=3920 and pair!=6 and not stop_sent:
                                (run/'stop-request.json').write_text(json.dumps({'reason':'Shared guest interval captured','ee_vsync_tick':state['ee_vsync_tick']}));stop_sent=True
                            if time.monotonic()-start>=last_meter+1:
                                pid=json.loads((run/'identity.json').read_text())['pid'];proc=psutil.Process(pid)
                                cpu=proc.cpu_times();meters.append({'host_elapsed':time.monotonic()-start,'ee':state['ee_vsync_tick'],'user':cpu.user,'system':cpu.system,'rss':proc.memory_info().rss,'host_total_cpu_percent':psutil.cpu_percent()});last_meter=time.monotonic()-start
                        except (OSError,ValueError,KeyError,psutil.Error):pass
                        time.sleep(.25)
                    driver.wait(timeout=10)
                    if profiler is not None:
                        profiler.wait(timeout=10);profile_log.close()
                    if observer is not None:
                        observer.wait(timeout=10);observer_log.close()
                assert driver.returncode==0
                report=json.loads((run/'report.json').read_text());assert report['test_saves_unchanged']
                assert report['terminated_at_requested_stop'] if pair!=6 else report['terminated_at_planned_timeout']
                assert report['input_sha256']==result['input_sha256'] and report['runner_sha256']==sha(candidate if mode=='1' else baseline)
                rows=[json.loads(line) for line in (run/'diagnostics/state.jsonl').read_text().splitlines()]
                a,ab=endpoint(rows,3300);b,bb=endpoint(rows,3900);guest=600/HZ
                row={'pair':pair,'mode':mode,'run':str(run),'runner_sha256':report['runner_sha256'],'speed':guest/(b-a),'wall_seconds':b-a,'bounds':[guest/(bb[1]-ab[0]),guest/(bb[0]-ab[1])],'peak_rss_bytes':report['peak_rss_bytes'],'private_card_unchanged':True}
                (out/(label+'.meters.json')).write_text(json.dumps(meters,indent=2));result['runs'].append(row)
                (out/'progress.json').write_text(json.dumps(result,indent=2));print('Controlled RE4 run completed',label,row['speed'],flush=True)
        changes=[]
        for pair in range(7):
            a=next(r['speed'] for r in result['runs'] if r['pair']==pair and r['mode']=='0');b=next(r['speed'] for r in result['runs'] if r['pair']==pair and r['mode']=='1');changes.append((b/a-1)*100)
        result.update(completed=True,paired_speed_gain_percent=changes,median_paired_gain_percent=statistics.median(changes),all_pairs_improved=all(x>0 for x in changes),baseline_median_speed=statistics.median(r['speed'] for r in result['runs'] if r['mode']=='0'),candidate_median_speed=statistics.median(r['speed'] for r in result['runs'] if r['mode']=='1'))
    except Exception as error:result.update(completed=False,error=str(error));raise
    finally:(out/'report.json').write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()

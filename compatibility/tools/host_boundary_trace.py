"""Bounded ETW attempt and raw-IP samples of the identity-checked owned session."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];run=ROOT/'artifacts/runs/host-boundary-manual-01'
out=ROOT/'artifacts/host-boundary'/('live-profile-02' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'artifacts/host-boundary';out.mkdir(parents=True,exist_ok=False)
identity=json.loads((run/'identity.json').read_text());exe=run/'guest/ps2EntryRunner.exe'
assert hashlib.sha256(exe.read_bytes()).hexdigest()==identity['runner_sha256']
xperf='C:/Program Files (x86)/Windows Kits/10/Windows Performance Toolkit/xperf.exe';logger='NT Kernel Logger'
p=subprocess.run([xperf,'-loggers'],capture_output=True,text=True,timeout=15);(out/'loggers-before.txt').write_text(p.stdout+p.stderr);assert logger not in p.stdout
command=[xperf,'-on','SysProf','-f',str(out/'kernel.etl')]
p=subprocess.run(command,capture_output=True,text=True,timeout=15);(out/'etw-start.txt').write_text(p.stdout+p.stderr)
record={'pid':identity['pid'],'runner_sha256':identity['runner_sha256'],'etw_start':{'command':command,'exit':p.returncode},'host_qpc_begin':time.perf_counter(),'scope':'Perturbing diagnostic of human gameplay, not a performance acceptance window'}
try:
    source=ROOT/'reference-tools/tools/diagnostics/hot_thread_sampler.py';text=source.read_text();marker='    leaf = collections.Counter()';assert text.count(marker)==1
    addition='''    import json
    raw=[]
    for pcs,count in stacks.items():
        if not pcs:continue
        info=SYMBOL_INFO(SizeOfStruct=88,MaxNameLen=500)
        delta=ctypes.c_uint64()
        known=dbghelp.SymFromAddr(process,pcs[0],ctypes.byref(delta),ctypes.byref(info))
        raw.append({'leaf':hex(pcs[0]),'count':count,'function':name_of(pcs[0]),'displacement':int(delta.value) if known else None,'source':line_of(pcs[0]),'stack':[name_of(pc) for pc in pcs]})
    Path(__file__).with_suffix('.samples.json').write_text(json.dumps({'pid':pid,'tid':tid,'taken':taken,'rows':raw},indent=2))
'''
    script=out/'sampler.py';script.write_text(text.replace(marker,addition+marker))
    args=[sys.executable,str(script),'--pid',str(identity['pid']),'--expected-exe',str(exe),'--seconds','12','--rate','100','--depth','14','--top','45','--lines','--callers-of','fused_770ea85198e8e87f_12b8']
    sample=subprocess.run(args,capture_output=True,text=True,timeout=50);(out/'sampler.stdout.txt').write_text(sample.stdout);(out/'sampler.stderr.txt').write_text(sample.stderr);record['sampler_exit']=sample.returncode
finally:
    if p.returncode==0:
        stop=subprocess.run([xperf,'-stop'],capture_output=True,text=True,timeout=20);(out/'etw-stop.txt').write_text(stop.stdout+stop.stderr);record['etw_stop_exit']=stop.returncode
    record['host_qpc_end']=time.perf_counter();(out/'report.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2))

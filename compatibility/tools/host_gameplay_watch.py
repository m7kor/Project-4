"""Observe only the owned manual session: room, item counter and guest clock.

No thread suspension and no WriteProcessMemory; all reads are non-atomic.
"""
from pathlib import Path
import ctypes,hashlib,importlib.util,json,struct,subprocess,sys,time
from ctypes import wintypes as wt
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/host-boundary-manual-01';out=run/'host-watch';out.mkdir(exist_ok=False)
identity=json.loads((run/'identity.json').read_text());pid=identity['pid'];exe=run/'guest/ps2EntryRunner.exe';elf=run/'guest/SLUS_211.34'
assert hashlib.sha256(exe.read_bytes()).hexdigest()==identity['runner_sha256']=='f8eb7e8e608a8f38f306f15e93fee7027b3d3f797ee9628cc31b7eca7cca727c'
tool=ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py'
command=[sys.executable,str(tool),'--pid',str(pid),'--run',str(run),'--identity',str(run/'identity.json'),'--exe',str(exe),'--elf',str(elf),'--exports',str(ROOT/'artifacts/navigation-inputs/player-exports.json'),'--room-exports',str(ROOT/'artifacts/navigation-inputs/room-exports.json'),'--samples','1','--out',str(out/'discovery.json')]
p=subprocess.run(command,capture_output=True,text=True,timeout=60);(out/'discovery.log').write_text(p.stdout+p.stderr);assert p.returncode==0,p.stderr
discovery=json.loads((out/'discovery.json').read_text());base=int(discovery['rdram_base'],16)
spec=importlib.util.spec_from_file_location('existing_live_memory',tool);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
addresses=discovery['room_export_evidence']['addresses']
k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD];k.OpenProcess.restype=wt.HANDLE;k.CloseHandle.argtypes=[wt.HANDLE]
k.ReadProcessMemory.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)];k.QueryFullProcessImageNameW.argtypes=[wt.HANDLE,wt.DWORD,wt.LPWSTR,ctypes.POINTER(wt.DWORD)]
h=k.OpenProcess(0x410,False,pid);assert h
name=ctypes.create_unicode_buffer(32768);n=wt.DWORD(len(name));assert k.QueryFullProcessImageNameW(h,0,name,ctypes.byref(n)) and Path(name.value).resolve()==exe.resolve()
def guest(address,size):
    assert 0<=address<=0x2000000-size
    b=ctypes.create_string_buffer(size);got=ctypes.c_size_t()
    if not k.ReadProcessMemory(h,base+address,b,size,ctypes.byref(got)) or got.value!=size:raise ctypes.WinError(ctypes.get_last_error())
    return b.raw
start=time.perf_counter();count=0
try:
    with (out/'observations.jsonl').open('x') as stream:
        while not (run/'report.json').exists() and time.perf_counter()-start<1800:
            row={'host_qpc':time.perf_counter(),'room':module.capture_room_guest(guest,addresses)}
            slot=struct.unpack('<I',guest(0x3ce154,4))[0]
            if slot and slot%2==0 and slot<0x1fffff0:
                item=guest(slot,10);item_id=struct.unpack_from('<H',item)[0]
                row['item']={'address':slot,'id':item_id,'counter':struct.unpack_from('<H',item,8)[0]>>3 if item_id==0x23 else None}
            path=run/'diagnostics/state.jsonl'
            if path.exists():
                with path.open('rb') as f:f.seek(max(0,path.stat().st_size-16384));lines=f.read().splitlines()
                try:
                    s=json.loads(lines[-1]);row['diagnostic']={key:s.get(key) for key in ('ee_vsync_tick','cycle','elapsed_seconds','tick')}
                except (ValueError,IndexError):pass
            stream.write(json.dumps(row)+'\n');stream.flush();count+=1
            time.sleep(1)
except (OSError,ValueError) as error:
    (out/'end-error.txt').write_text(str(error))
finally:
    k.CloseHandle(h);(out/'report.json').write_text(json.dumps({'observations':count,'seconds':time.perf_counter()-start,'pid':pid,'scope':'Read-only non-atomic live evidence; snapshots are not savestates'},indent=2))

"""Bounded read-only search for already-known VU code images in one owned process.

Writes identities and addresses only. It excludes >=32MiB regions, including EE RAM,
and does not claim that every remaining match is the active VU buffer.
"""
from pathlib import Path
import ctypes,ctypes.wintypes as w,re,struct,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
run=ROOT/'artifacts/runs/fusion-play'
identity=json.loads((run/'identity.json').read_text())
assert not (run/'report.json').exists()
exe=run/'guest/ps2EntryRunner.exe'
assert hashlib.sha256(exe.read_bytes()).hexdigest()==identity['runner_sha256']
t=(ROOT/'engines/project4/ps2xRuntime/src/lib/vu/generated/vu1_compiled_programs.inc').read_text()
constants={k:struct.pack('<II',int(lo,16),int(hi,16)) for k,lo,hi in re.findall(r'static constexpr P (k\d+) = \{\.lower = (0x[0-9A-Fa-f]+)u, \.upper = (0x[0-9A-Fa-f]+)u',t)}
images=[]
for key,table in re.findall(r'CompiledPairFn t_([0-9a-f]{16})\[2048\] = \{(.*?)\n    \};',t,re.S):
    data=b''.join(constants[k] for k in re.findall(r'&step<(k\d+)>',table));assert len(data)==16384
    h=0xcbf29ce484222325
    for b in data:h=((h^b)*0x100000001b3)&0xffffffffffffffff
    assert f'{h:016x}'==key
    anchor=max(range(0,len(data)-64,64),key=lambda n:len(set(data[n:n+64])))
    images.append((key,data,anchor,data[anchor:anchor+64]))
class Info(ctypes.Structure):
    _fields_=[('base',ctypes.c_void_p),('allocation',ctypes.c_void_p),('ap',w.DWORD),('partition',w.WORD),('size',ctypes.c_size_t),('state',w.DWORD),('protect',w.DWORD),('kind',w.DWORD)]
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
k.VirtualQueryEx.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.POINTER(Info),ctypes.c_size_t];k.VirtualQueryEx.restype=ctypes.c_size_t
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
k.CloseHandle.argtypes=[w.HANDLE]
handle=k.OpenProcess(0x410,False,identity['pid']);assert handle
matches=[];scanned=0
try:
    name=ctypes.create_unicode_buffer(32768);length=w.DWORD(len(name));assert k.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(length))
    assert Path(name.value).resolve()==exe.resolve()
    regions=[];cursor=0
    for _ in range(100000):
        info=Info()
        if not k.VirtualQueryEx(handle,cursor,ctypes.byref(info),ctypes.sizeof(info)):break
        start=int(info.base or 0);end=start+info.size
        assert end>cursor;cursor=end
        if info.state==0x1000 and info.kind==0x20000 and not info.protect&0x101 and 16384<=info.size<32*1024*1024:
            regions.append((info.size,start))
    for size,start in sorted(regions):
        if scanned+size>512*1024*1024:break
        buffer=ctypes.create_string_buffer(size);got=ctypes.c_size_t()
        if not k.ReadProcessMemory(handle,start,buffer,size,ctypes.byref(got)):continue
        data=buffer.raw;scanned+=size
        for key,image,offset,anchor in images:
            at=data.find(anchor)
            while at>=0:
                begin=at-offset
                if begin>=0 and data[begin:begin+len(image)]==image:matches.append(dict(code_hash=key,address=hex(start+begin),region_base=hex(start),region_size=size))
                at=data.find(anchor,at+1)
finally:k.CloseHandle(handle)
result=dict(scope=__doc__,pid=identity['pid'],scanned_bytes=scanned,matches=matches)
(run/'known-vu-image-observation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))

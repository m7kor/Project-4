"""Read-only bounded RAM snapshots around the existing shoot/inventory scenario.

Private dumps are correlation evidence, not identification of an ammo field.
No WriteProcessMemory, thread suspension, coordinates or flag manipulation.
"""
from pathlib import Path
import ctypes,hashlib,json,struct,subprocess,sys,time
from ctypes import wintypes as wt
ROOT=Path(__file__).resolve().parents[1];run=Path(sys.argv[1]).resolve()
assert run.is_relative_to((ROOT/'artifacts/runs').resolve())
out=run/'phase5-ammo';out.mkdir(exist_ok=False)
def state():
 with (run/'diagnostics/state.jsonl').open('rb') as stream:
  stream.seek(max(0,(run/'diagnostics/state.jsonl').stat().st_size-16384));return json.loads(stream.read().splitlines()[-1])
def wait(field):
 start=time.monotonic()
 while time.monotonic()-start<180:
  if (run/'report.json').exists():raise RuntimeError('Owned run ended before observation')
  try:
   row=state()
   if row['ee_vsync_tick']>=field:return row
  except (OSError,ValueError,IndexError):pass
  time.sleep(.1)
 raise TimeoutError('Read-only observation guest-field gate')
report={'scope':'Read-only RAM correlation only; snapshots are not atomic and candidate addresses are not identified ammunition fields','snapshots':[],'completed':False}
handle=None
try:
 wait(4600);identity=json.loads((run/'identity.json').read_text());pid=identity['pid'];exe=run/'guest/ps2EntryRunner.exe';elf=run/'guest/SLUS_211.34'
 assert hashlib.sha256(exe.read_bytes()).hexdigest()==identity['runner_sha256']
 assert hashlib.sha256(elf.read_bytes()).hexdigest()==identity['elf_sha256']=='465d144f526603d0dcc35ad1fdb4e82cc3a1481c22289f321482cc910fb9f1ad'
 args=[sys.executable,ROOT/'reference-tools/tools/diagnostics/re4_live_memory.py','--pid',str(pid),'--run',run,'--identity',run/'identity.json','--exe',exe,'--elf',elf,'--exports',ROOT/'artifacts/navigation-inputs/player-exports.json','--room-exports',ROOT/'artifacts/navigation-inputs/room-exports.json','--samples','1','--out',out/'discovery.json']
 p=subprocess.run(list(map(str,args)),cwd=ROOT,capture_output=True,text=True,timeout=60);(out/'discovery.log').write_text(p.stdout+p.stderr);assert p.returncode==0
 discovery=json.loads((out/'discovery.json').read_text());assert discovery['completed'] and discovery['pid']==pid
 base=int(discovery['rdram_base'],16)
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD];kernel.OpenProcess.restype=wt.HANDLE
 kernel.CloseHandle.argtypes=[wt.HANDLE]
 kernel.QueryFullProcessImageNameW.argtypes=[wt.HANDLE,wt.DWORD,wt.LPWSTR,ctypes.POINTER(wt.DWORD)]
 kernel.ReadProcessMemory.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
 handle=kernel.OpenProcess(0x410,False,pid)
 if not handle:raise ctypes.WinError(ctypes.get_last_error())
 name=ctypes.create_unicode_buffer(32768);size=wt.DWORD(len(name))
 assert kernel.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(size)) and Path(name.value).resolve()==exe.resolve()
 def read(address,size):
  buffer=ctypes.create_string_buffer(size);got=ctypes.c_size_t()
  if not kernel.ReadProcessMemory(handle,address,buffer,size,ctypes.byref(got)) or got.value!=size:raise ctypes.WinError(ctypes.get_last_error())
  return buffer.raw
 data=elf.read_bytes();ph=struct.unpack_from('<I',data,28)[0];segment=struct.unpack_from('<8I',data,ph)
 for address in (0x100000,0x105910,0x109430):
  signature=data[segment[1]+address-segment[2]:segment[1]+address-segment[2]+64];assert read(base+address,64)==signature
 report.update(pid=pid,runner_sha256=identity['runner_sha256'],rdram_base=hex(base))
 for label,field in [('before-fire',5080),('during-fire',5110),('after-fire',5200),('inventory',5350)]:
  before=wait(field);begin=time.perf_counter();payload=read(base,32*1024*1024);end=time.perf_counter();after=state()
  path=out/(label+'.bin');path.write_bytes(payload)
  report['snapshots'].append({'label':label,'requested_ee':field,'before':{'ee':before['ee_vsync_tick'],'elapsed':before['elapsed_seconds']},'after':{'ee':after['ee_vsync_tick'],'elapsed':after['elapsed_seconds']},'read_seconds':end-begin,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
 report['completed']=True
except Exception as error:report['error']=str(error)
finally:
 if handle:kernel.CloseHandle(handle)
 (out/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='snapshots'}));raise SystemExit(0 if report['completed'] else 1)

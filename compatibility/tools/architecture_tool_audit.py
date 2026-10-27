"""Check installed tools without installing duplicates or enabling tracing globally."""
from pathlib import Path
import importlib.util,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture/tool-audit-01.json';assert not out.exists()
commands=[['C:/Program Files/LLVM/bin/clang-cl.exe','--version'],['C:/Program Files/CMake/bin/cmake.exe','--version'],['C:/Users/KH/AppData/Local/Microsoft/WinGet/Links/ninja.exe','--version'],['C:/Users/KH/AppData/Local/Microsoft/WinGet/Links/sccache.exe','--version'],['C:/Windows/System32/wpr.exe','-profiles']]
rows=[]
for command in commands:
 try:
  p=subprocess.run(command,capture_output=True,text=True,timeout=15);rows.append({'command':command,'exit':p.returncode,'output':(p.stdout+p.stderr)[:4000],'scope':'Version/profile enumeration, not an integrated performance capture'})
 except Exception as error:rows.append({'command':command,'error':str(error)})
sys.path.insert(0,str(ROOT/'lab/phase4-python'))
try:
 import z3
 s=z3.Solver();x=z3.BitVec('architecture_tool_smoke',32);s.add(x+1!=1+x);assert s.check()==z3.unsat
 rows.append({'tool':'Z3','version':z3.get_version_string(),'source':'Existing lab/phase4-python; not on default Python312 path','smoke':'32-bit commutativity UNSAT','scope':'Tool functionality, not an additional PS2 proof'})
except Exception as error:rows.append({'tool':'Z3','error':str(error)})
rows.append({'optional_python_packages':{n:importlib.util.find_spec(n) is not None for n in ['capstone','tracy','psutil']},'not_integrated':['Tracy','Profile Explorer','RenderDoc','GFXReconstruct','Google Benchmark','AFL++','SIMDe'],'decision':'No installations. Existing sampler/VU replay answer the current question; GPU/ETW integration remains unmeasured.'})
out.write_text(json.dumps(rows,indent=2));print('Tool inventory saved; existing Z3 reused')

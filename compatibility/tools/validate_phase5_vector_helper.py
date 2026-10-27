"""Compile actual production helper under SIMD, fallback and a real mask mutation."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/phase5-vector-witness-01';out.mkdir(exist_ok=False)
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp';text=source.read_text(encoding='utf-8')
helper=text[text.index('void ps2Vu1RetireVectorWrite('):text.index('static const bool vectorRetirementEnabled')]
prefix='#include <cstdint>\n#include <cstring>\n#include <smmintrin.h>\n'
reports=[]
for mode in ('simd','scalar','mutant'):
 body=helper
 if mode=='mutant':
  line=next(line for line in body.splitlines() if 'const __m128 mask = ' in line);body=body.replace(line,'    const __m128 mask = equal; // Deliberately omit lane mask')
 code=out/(mode+'.cpp');code.write_text(prefix+('#define PS2X_VECTOR_RETIRE_SSE41 1\n' if mode!='scalar' else '')+body,encoding='utf-8')
 exe=out/(mode+'.exe')
 command=['C:/Program Files/LLVM/bin/clang-cl.exe','/nologo','/std:c++20','/O2','/EHsc','-msse4.1',str(code),str(ROOT/'tests/phase5_vector_retire_witness.cpp'),'/Fo'+str(out)+'\\','/Fe'+str(exe)]
 subprocess.run(command,cwd=out,check=True)
 p=subprocess.run([str(exe)],cwd=out,capture_output=True,text=True,timeout=30);(out/(mode+'.stdout.txt')).write_text(p.stdout+p.stderr)
 assert (p.returncode==0)==(mode!='mutant'),(mode,p.returncode,p.stdout)
 reports.append({'mode':mode,'returncode':p.returncode,'output':p.stdout,'binary_sha256':hashlib.sha256(exe.read_bytes()).hexdigest()})
report={'passed':True,'rows':reports,'helper_sha256':hashlib.sha256(helper.encode()).hexdigest(),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'scope':'Actual helper with independent bitwise oracle; SIMD and forced scalar fallback pass; compiled mask mutation must fail'}
(ROOT/'artifacts/phase5/vector-helper-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)

"""Actual FMAC classifier versus independent exponent oracle and Z3 algebra."""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/phase5-fmac-witness-01';out.mkdir(exist_ok=False)
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp';text=source.read_text(encoding='utf-8')
helper=text[text.index('bool ps2Vu1ClassifyNormalFmac('):text.index('static const bool fmacClassifyEnabled')]
prefix='#include <cstdint>\n#include <cstring>\n#include <emmintrin.h>\n'
rows=[]
for mode in ('simd','scalar','mutant'):
 body=helper
 if mode=='mutant':
  line=next(line for line in body.splitlines() if 'const uint32_t packed = ' in line);body=body.replace(line,line[:-1]+' ^ 2u; // Wrong sign byte')
 code=out/(mode+'.cpp');code.write_text(prefix+('#define PS2X_FMAC_CLASSIFY_SSE2 1\n' if mode!='scalar' else '')+body,encoding='utf-8')
 exe=out/(mode+'.exe')
 subprocess.run(['C:/Program Files/LLVM/bin/clang-cl.exe','/nologo','/std:c++20','/O2','/EHsc',str(code),str(ROOT/'tests/phase5_fmac_classify_witness.cpp'),'/Fo'+str(out)+'\\','/Fe'+str(exe)],cwd=out,check=True)
 p=subprocess.run([str(exe)],cwd=out,capture_output=True,text=True,timeout=30);(out/(mode+'.stdout.txt')).write_text(p.stdout+p.stderr)
 assert (p.returncode==0)==(mode!='mutant'),(mode,p.returncode,p.stdout)
 rows.append({'mode':mode,'returncode':p.returncode,'output':p.stdout,'sha256':hashlib.sha256(exe.read_bytes()).hexdigest()})
sys.path.insert(0,str(ROOT/'lab/phase4-python'))
from z3 import BitVec,And,Extract,UGE,ULE,UGT,ULT,Solver,unsat
bits=BitVec('bits',32);magnitude=bits&0x7fffffff;exponent=Extract(30,23,bits)
solver=Solver();solver.add(And(UGT(magnitude,0x00ffffff),ULT(magnitude,0x7f000000))!=And(UGE(exponent,2),ULE(exponent,253)))
assert solver.check()==unsat
report={'passed':True,'rows':rows,'z3_all32bit_predicate_equivalence':'UNSAT counterexample','helper_sha256':hashlib.sha256(helper.encode()).hexdigest(),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'scope':'Only the already-safe normal exponent shortcut; not a proof of guest FP arithmetic or exceptional normalization'}
(ROOT/'artifacts/phase5/fmac-helper-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)

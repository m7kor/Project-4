"""Proof of the actual classifier constants and exhaustive lane/sign tables."""
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lab/phase4-python'))
from z3 import BitVec,And,Extract,UGE,ULE,Solver,unsat,sat
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
text=source.read_text(encoding='utf-8')
helper=text[text.index('bool ps2Vu1ClassifyNormalFmac('):text.index('static const bool fmacClassifyEnabled')]
record=json.loads((ROOT/'artifacts/phase5/fmac-helper-report.json').read_text())
assert hashlib.sha256(source.read_bytes()).hexdigest()==record['source_sha256']
assert hashlib.sha256(helper.encode()).hexdigest()==record['helper_sha256']
lower=int(re.search(r'const __m128i lower = _mm_cmpgt_epi32\(magnitude, _mm_set1_epi32\((0x[0-9a-f]+)\)',helper)[1],16)
upper=int(re.search(r'const __m128i upper = _mm_cmpgt_epi32\(_mm_set1_epi32\((0x[0-9a-f]+)\), magnitude',helper)[1],16)
bits=BitVec('actual_bits',32);mag=bits&0x7fffffff;exp=Extract(30,23,bits)
oracle=And(UGE(exp,2),ULE(exp,253))
solver=Solver();solver.add(And(mag>lower,mag<upper)!=oracle);assert solver.check()==unsat
negative=Solver();negative.add(And(mag>lower,mag<0x7fffffff)!=oracle);assert negative.check()==sat
def array(name):
 value=re.search(r'\b'+name+r'\[16\] = \{([^}]+)\}',helper)[1]
 return [int(token.strip().rstrip('u'),0) for token in value.split(',')]
reverse=array('reversed');flags=array('signFlags');checks=0
assert len(reverse)==len(flags)==16
for dest in range(16):
 for normal in range(16):
  for sign in range(16):
   selected=reverse[dest];actual=(normal&selected)==selected
   expected=all(not(dest&(8>>c)) or normal&(1<<c) for c in range(4));assert actual==expected
   if actual:
    packed=flags[sign&selected]
    expected_flags=sum((2 if sign&(1<<c) and dest&(8>>c) else 0)<<(8*c) for c in range(4))
    assert packed==expected_flags
   checks+=1
print(json.dumps({'passed':True,'all32bit_predicate_counterexample':'UNSAT','altered_upper_bound_negative_control':'SAT','lane_normal_sign_combinations':checks,'scope':'Actual source constants/table proof only; not a proof of complete guest floating-point hardware'}))

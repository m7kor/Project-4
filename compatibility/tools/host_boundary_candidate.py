"""One structural prototype: inline shared helper ABI boundaries, not their math.

Every original operation, queue insertion and retirement point is unchanged.
No generated block table, flag liveness, normalization or scheduling change.
The separate executable is experimental; the accepted runner is never replaced.
"""
from pathlib import Path
import hashlib,json,re,shutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/host-boundary-inline-01';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=out/'src';shutil.copytree(ROOT/'lab/architecture-aot-02/src',source)
reference=ROOT/'artifacts/architecture/freeze-01/vu1_compiled_programs.inc';shutil.copyfile(reference,source/'generated/vu1_compiled_programs.inc')
core=source/'ps2_vu1_core.cpp';assert sha(core)=='48077ba02c66e8d0dc0efe6182db011ca2d7575db19e6b4f1e03412dfd207f98'
text=core.read_text();names=['applyFmacDest','applyFmacDestAcc','queueVfWrite','queueViWrite','queueAccWrite']
for name in names:
    pattern=r'\nvoid VU1Interpreter::'+name+r'\('
    text,count=re.subn(pattern,'\n__attribute__((always_inline)) void VU1Interpreter::'+name+'(',text);assert count==1,name
core.write_text(text,encoding='utf-8',newline='\n')
data={'input_files':{str(p):sha(p) for p in [Path(__file__),reference,ROOT/'lab/architecture-aot-02/src/ps2_vu1_core.cpp']},'generated_files':{str(p):sha(p) for p in source.rglob('*') if p.is_file()},
      'hypothesis':'Reduce call-boundary materialization in already specialized blocks by compiler inlining of unchanged shared helpers',
      'changed_methods':names,'shipping_enabled':False,
      'side_exit_contract':'No deferred state. Source bodies and every original guard/queue insertion/write/readyCycle/sequence remain unchanged. Original small-budget, MSCNT, interrupts, XGKICK, flush and code identity checks remain at the exact source positions. Original interpreter and independent Phase4 executable retained.'}
(out/'generation.json').write_text(json.dumps(data,indent=2));print('Prepared prototype1: helper ABI boundaries only; unchanged semantics and original generated blocks')

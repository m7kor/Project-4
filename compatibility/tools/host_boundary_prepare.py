"""Generate a diagnostic-only clone of the accepted Phase4 VU implementation."""
from pathlib import Path
import hashlib,json,re,shutil
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
out=ROOT/'lab/host-boundary-probe-01';out.mkdir(exist_ok=False)
source=out/'src';shutil.copytree(ROOT/'lab/architecture-aot-02/src',source)
reference=ROOT/'artifacts/architecture/freeze-01/vu1_compiled_programs.inc'
core=source/'ps2_vu1_core.cpp'
assert sha(core)=='48077ba02c66e8d0dc0efe6182db011ca2d7575db19e6b4f1e03412dfd207f98'
text=core.read_text();include=ROOT/'tests/host_boundary_probe.inl'
text=text.replace('#include <ps2_log.h>','#include <ps2_log.h>\n#include "'+include.as_posix()+'"',1)
helpers={'commitReadyPipelines':(1,'m_cycle < m_nextCommitCycle && !vu1ScanAll()'),
         'progressXgkick':(2,'!m_xgkick.active || !m_activeVuData || m_activeVuDataSize == 0u'),
         'updateFmacFlags':(3,'false'),'normalizeFmacResult':(4,'false'),
         'normalizeFmacExactResult':(4,'false'),'applyFmacDest':(5,'false'),
         'applyFmacDestAcc':(5,'false'),'queueVfWrite':(6,'false'),
         'queueViWrite':(6,'false'),'queueAccWrite':(6,'false'),
         'queueClip':(6,'false'),'queueStore':(6,'false'),
         'advanceTo':(7,'false'),'flushPipelines':(8,'false')}
for name,(kind,empty) in helpers.items():
    pattern=r'(\bVU1Interpreter::'+name+r'\([^;{}]*\)\s*(?:const\s*)?\{)'
    text,count=re.subn(pattern,lambda m:m[0]+f'\n    HostBoundaryScope hostScope({kind}, {empty});',text)
    assert count==1,(name,count)
core.write_text(text,encoding='utf-8',newline='\n')
text=reference.read_text();name='fused_770ea85198e8e87f_12b8'
pattern=r'(static int '+name+r'\([^;{}]+\)\s*\{)'
text,count=re.subn(pattern,lambda m:m[0]+'\n        HostBoundaryScope hostRoot(0);',text);assert count==1
(source/'generated/vu1_compiled_programs.inc').write_text(text,encoding='utf-8',newline='\n')
data={'input_files':{str(p):sha(p) for p in [Path(__file__),include,reference,ROOT/'lab/architecture-aot-02/src/ps2_vu1_core.cpp']},'generated_files':{str(p):sha(p) for p in source.rglob('*') if p.is_file()},'hypothesis':'Measure selected hot function and nested helper boundaries without altering guest state; mode0 off, mode1 counts, mode2 sampled TSC ticks', 'category_names':['hot-function','retirement','xgkick','flags','normalization','fmac-destination','queue-writes','advance','flush']}
(out/'generation.json').write_text(json.dumps(data,indent=2));print('Generated reference-only diagnostic clone; no AOT02 table or semantic change')

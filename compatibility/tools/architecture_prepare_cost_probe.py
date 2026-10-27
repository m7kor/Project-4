"""Count real issued pairs and idle cycles on captured work, not wall-time samples."""
from pathlib import Path
import hashlib,json,re,shutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/architecture-vu-cost-01';out.mkdir(exist_ok=False)
parent=ROOT/'lab/architecture-aot-02';manifest=json.loads((parent/'generation.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for path,h in manifest['generated_files'].items():assert sha(Path(path))==h,path
shutil.copytree(parent/'src',out/'src');source=out/'src'
def change(path,old,new):
 text=path.read_text();assert text.count(old)==1,(path,old);path.write_text(text.replace(old,new),encoding='utf-8',newline='\n')
core=source/'ps2_vu1_core.cpp'
change(core,'#include <ps2_log.h>','#include <ps2_log.h>\n#include "'+str(ROOT/'tests/architecture_vu_cost.inl').replace('\\','/')+'"')
change(core,'void VU1Interpreter::advanceTo(uint64_t targetCycle)\n{','void VU1Interpreter::advanceTo(uint64_t targetCycle)\n{\n    if(architectureCostEnabled && m_unit==Unit::VU1 && targetCycle>m_cycle) architectureVuCounts.stallCycles+=targetCycle-m_cycle;')
change(core,'void VU1Interpreter::flushPipelines()\n{','void VU1Interpreter::flushPipelines()\n{\n    ArchitectureVuScope cost(&m_cycle,m_unit==Unit::VU1,2);')
change(core,'    ++m_xgkick.cycleCredit;','    if(architectureCostEnabled && m_unit==Unit::VU1) ++architectureVuCounts.xgCalls;\n    ++m_xgkick.cycleCredit;')
change(core,'        m_xgkick.copiedBytes += 16u;','        m_xgkick.copiedBytes += 16u;\n        if(architectureCostEnabled && m_unit==Unit::VU1) ++architectureVuCounts.xgQwords;')
change(source/'ps2_vu1_step_issue.inl','    uint8_t writtenVi = 0u;','    if(architectureCostEnabled && vu.m_unit==VU1Interpreter::Unit::VU1) ++architectureVuCounts.pairs;\n    uint8_t writtenVi = 0u;')
change(source/'ps2_vu1_step.inl','    auto &vu = *this;','    ArchitectureVuScope cost(&m_cycle,m_unit==Unit::VU1,0);\n    auto &vu = *this;')
inc=source/'generated/vu1_compiled_programs.inc';text=inc.read_text()
needle='static PS2X_VU1_STEP_INLINE void upperClean(VU1Interpreter &vu, uint32_t instr)\n    {';assert text.count(needle)==1;text=text.replace(needle,needle+'\n        if(architectureCostEnabled && vu.m_unit==VU1Interpreter::Unit::VU1) ++architectureVuCounts.nativePairs;')
pattern=r'(    static (?:PS2X_VU1_COLD )?int (?:clean|fused|from)_[0-9a-f_]+\([^\n]+\)\n    \{)'
text,count=re.subn(pattern,lambda m:m[1]+'\n        ArchitectureVuScope cost(&vu.m_cycle,vu.m_unit==VU1Interpreter::Unit::VU1,1);',text);assert count>200,count
inc.write_text(text,encoding='utf-8',newline='\n')
record={'input_files':{str(parent/'generation.json'):sha(parent/'generation.json'),str(ROOT/'tests/architecture_vu_cost.inl'):sha(ROOT/'tests/architecture_vu_cost.inl'),str(Path(__file__)):sha(Path(__file__))},'generated_files':{str(p):sha(p) for p in source.rglob('*') if p.is_file()},'scope':'Diagnostic counters only, thread-local, no guest writes. Native envelope cycles include waits; pair counts distinguish specialized upper execution from generic pair execution. Not a performance candidate.'}
(out/'generation.json').write_text(json.dumps(record,indent=2));print('Prepared diagnostic counts for',count,'native functions')

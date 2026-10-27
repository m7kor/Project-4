"""Extend the existing proven free-slot helper to flag, EFU and store queues."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
out=ROOT/'artifacts/experiments/vu-queue-allocation';out.mkdir(exist_ok=True)
assert not (out/'before-core.cpp').exists(), 'Do not overwrite an existing source backup'
before=source.read_bytes();newline='\r\n' if b'\r\n' in before else '\n';text=before.decode().replace('\r\n','\n')
old='''    FlagPipelineEntry *entry = nullptr;
    for (FlagPipelineEntry &candidate : m_flagPipeline)
    {
        if (!candidate.valid)
        {
            entry = &candidate;
            break;
        }
    }'''
assert text.count(old)==1
text=text.replace(old,'    FlagPipelineEntry *entry = firstFreePipelineSlot(m_flagPipeline, m_flagPending);')
for name,kind,array,pending,var in [
    ('queueFsset','FlagPipelineEntry','m_flagPipeline','m_flagPending','entry'),
    ('queueClip','FlagPipelineEntry','m_flagPipeline','m_flagPending','entry'),
    ('queueFcset','FlagPipelineEntry','m_flagPipeline','m_flagPending','entry'),
    ('queueP','ScalarPipelineEntry','m_efu','m_efuPending','entry'),
    ('queueStore','PendingStore','m_storePipeline','m_storePending','store')]:
    start=text.index('void VU1Interpreter::'+name+'(');end=text.index('\nvoid VU1Interpreter::',start+1)
    function=text[start:end]
    loop=f'    for ({kind} &{var} : {array})\n    {{\n        if (!{var}.valid)'
    assert function.count(loop)==1,(name,'ambiguous allocation loop')
    replacement=f'    if ({kind} *available = firstFreePipelineSlot({array}, {pending}))\n    {{\n        {kind} &{var} = *available;\n        if (!{var}.valid)'
    function=function.replace(loop,replacement)
    text=text[:start]+function+text[end:]
(out/'before-core.cpp').write_bytes(before)
after=text.replace('\n',newline).encode()
source.write_bytes(after)
record={'scope':'Reuse existing firstFreePipelineSlot for six remaining allocation sites; same first available index, no timing/order/math change',
        'files':['ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'],'before_sha256':hashlib.sha256(before).hexdigest(),
        'after_sha256':hashlib.sha256(after).hexdigest(),'fallback':'PS2X_VU1_ALLOC_SCAN=1',
        'status':'Experimental; validate pending/valid invariants and measure before acceptance'}
(out/'integration.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))

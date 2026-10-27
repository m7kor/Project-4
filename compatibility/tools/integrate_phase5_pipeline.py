"""Prototype a run-scoped, derived per-pipeline retirement index, default OFF."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
out=ROOT/'artifacts/phase5'/('pipeline-02' if len(sys.argv)==1 else sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
before=path.read_bytes();text=before.decode('utf-8').replace('\r\n','\n')
(out/'before-core.cpp').write_bytes(before)
helper='''    // Derived acceleration metadata lives only for one run/resume. It is
    // rebuilt from pending entries, never serialized or carried across copies.
    static const bool indexedRetirement = [] {
        const char *v = std::getenv("PS2X_VU1_PIPELINE_INDEX");
        return v && *v == '1';
    }();
    struct RetirementIndex
    {
        const void *owner;
        uint64_t ready[7]; // flags, Q, P, stores, VF, VI, ACC
        RetirementIndex *previous;
    };
    thread_local RetirementIndex *activeRetirementIndex = nullptr;
    struct RetirementIndexScope
    {
        RetirementIndex index;
        RetirementIndexScope(const void *owner, bool enabled)
            : index{owner, {}, activeRetirementIndex}
        {
            activeRetirementIndex = enabled ? &index : nullptr;
        }
        ~RetirementIndexScope()
        {
            activeRetirementIndex = index.previous;
            // Nested execution may change the outer unit through callbacks.
            if (index.previous)
                std::fill(std::begin(index.previous->ready), std::end(index.previous->ready), 0u);
        }
    };
    inline RetirementIndex *retirementIndexFor(const void *owner)
    {
        if (!indexedRetirement) return nullptr;
        auto *index = activeRetirementIndex;
        return index && index->owner == owner ? index : nullptr;
    }
    inline void noteRetirement(const void *owner, uint32_t group, uint64_t cycle, bool replace = false)
    {
        if (auto *index = retirementIndexFor(owner))
            index->ready[group] = replace ? cycle : std::min(index->ready[group], cycle);
    }

'''
needle='    const bool scanAllocationSlots = [] {';assert text.count(needle)==1
text=text.replace(needle,helper+needle)
# An explicit reset invalidates derived metadata even if issued reentrantly.
needle='    m_nextCommitCycle = 0u;';assert text.count(needle)==1
text=text.replace(needle,needle+'\n    if (auto *index = retirementIndexFor(this))\n        std::fill(std::begin(index->ready), std::end(index->ready), 0u);')
for name,group in [('updateFmacFlags',0),('queueFsset',0),('queueClip',0),('queueFcset',0),('queueQ',1),('queueP',2),('queueStore',3),('queueVfWrite',4),('queueViWrite',5),('queueAccWrite',6)]:
 start=text.index('void VU1Interpreter::'+name+'(');end=text.index('\n}',start)+2
 body=text[start:end]
 import re
 body,count=re.subn(r'(    +m_nextCommitCycle = std::min\(m_nextCommitCycle, ([^;]+)\);)',lambda m:m[1]+'\n'+m[1][:len(m[1])-len(m[1].lstrip())]+f'noteRetirement(this, {group}, {m[2]}'+(', true' if group==1 else '')+');',body)
 assert count==1,(name,count)
 text=text[:start]+body+text[end:]
start=text.index('void VU1Interpreter::commitReadyPipelines()');end=text.index('\nvoid VU1Interpreter::progressXgkick()',start)
body=text[start:end]
markers=['    {\n        // One pass:', '    if (m_fdiv.valid && m_fdiv.readyCycle > m_cycle)',
 '    for (;;)','    for (;;)','    for (uint32_t pending = m_vfPending;',
 '    for (uint32_t pending = m_viPending;','    for (uint32_t pending = m_accPending;','    m_nextCommitCycle = next;']
positions=[];offset=0
for marker in markers:
 position=body.index(marker,offset);positions.append(position);offset=position+len(marker)
prefix=body[:positions[0]]+'    auto *retirementIndex = vu1ScanAll() ? nullptr : retirementIndexFor(this);\n'
chunks=[]
for group in range(7):
 chunk=body[positions[group]:positions[group+1]].rstrip()
 chunk=chunk.replace('next = std::min(next,','groupNext = std::min(groupNext,')
 chunks.append('    if (!retirementIndex || retirementIndex->ready['+str(group)+'] <= m_cycle)\n    {\n        uint64_t groupNext = UINT64_MAX;\n'+ '\n'.join('    '+line for line in chunk.splitlines())+f'\n        if (retirementIndex) retirementIndex->ready[{group}] = groupNext;\n        else next = std::min(next, groupNext);\n    }}\n')
body=prefix+'\n'.join(chunks)+'''    if (retirementIndex)
        for (const uint64_t cycle : retirementIndex->ready)
            next = std::min(next, cycle);
'''+body[positions[-1]:]
text=text[:start]+body+text[end:]
needle='''    m_activeMemory = memory;

    // Preserve the CRT path'''
seed='''    m_activeMemory = memory;
    RetirementIndexScope retirementScope(this, indexedRetirement && !vu1ScanAll());
    if (indexedRetirement && !vu1ScanAll())
    {
        auto seed = [](const auto &entries, uint32_t pending) {
            uint64_t first = UINT64_MAX;
            for (; pending; pending &= pending - 1u)
            {
                const auto &entry = entries[std::countr_zero(pending)];
                first = std::min(first, entry.valid ? entry.readyCycle : uint64_t(0));
            }
            return first;
        };
        auto &ready = retirementScope.index.ready;
        ready[0] = seed(m_flagPipeline, m_flagPending);
        ready[1] = m_fdiv.valid ? m_fdiv.readyCycle : UINT64_MAX;
        ready[2] = seed(m_efu, m_efuPending);
        ready[3] = seed(m_storePipeline, m_storePending);
        ready[4] = seed(m_vfWritePipeline, m_vfPending);
        ready[5] = seed(m_viWritePipeline, m_viPending);
        ready[6] = seed(m_accWritePipeline, m_accPending);
    }

    // Preserve the CRT path'''
assert text.count(needle)==1;text=text.replace(needle,seed)
after=text.replace('\n','\r\n' if b'\r\n' in before else '\n').encode('utf-8');path.write_bytes(after)
(out/'source.json').write_text(json.dumps({'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),'mode':'PS2X_VU1_PIPELINE_INDEX=1','default':False,'scope':'Derived run-scoped minima; original retirement bodies/order preserved; no headers changed'},indent=2))
print('Run-scoped pipeline prototype installed; OFF by default')

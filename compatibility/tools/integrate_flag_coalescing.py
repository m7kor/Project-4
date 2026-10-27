"""Coalesce already-superseded flag entries while preserving their last drain cycle."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-flag-coalescing';out.mkdir(exist_ok=False)
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
before=source.read_bytes();assert hashlib.sha256(before).hexdigest()=='48077ba02c66e8d0dc0efe6182db011ca2d7575db19e6b4f1e03412dfd207f98'
newline='\r\n' if b'\r\n' in before else '\n';text=before.decode().replace('\r\n','\n')
helper='''    // Superseded MAC/status entries have no remaining effect unless they also
    // carry CLIP or FSSET. Keep the latest no-op deadline as a real queue entry:
    // flushPipelines must still drain to the same cycle at E/budget boundaries.
    const bool coalesceSupersededFlags = [] {
        const char *value = std::getenv("PS2X_VU1_COALESCE_FLAGS");
        return !(value && *value == '0');
    }();

    template <bool Coalesce, typename Entries>
    uint32_t supersedeFmacEntries(Entries &entries, uint32_t &pendingMask)
    {
        uint32_t inheritedSticky = 0u;
        uint32_t noOpMask = 0u, keepMask = 0u;
        uint64_t latestReady = 0u;
        for (uint32_t pending = pendingMask; pending != 0u; pending &= pending - 1u)
        {
            const uint32_t index = static_cast<uint32_t>(std::countr_zero(pending));
            auto &older = entries[index];
            if (!older.valid)
                continue;
            if (older.writesStatus)
                inheritedSticky |= ((older.status & 0xFu) | older.extraSticky) << 6;
            older.writesStatus = false;
            older.writesMac = false;
            if constexpr (Coalesce)
            {
                if (!older.writesSticky && !older.writesClip)
                {
                    const uint32_t bit = 1u << index;
                    noOpMask |= bit;
                    if (keepMask == 0u || older.readyCycle > latestReady)
                    {
                        keepMask = bit;
                        latestReady = older.readyCycle;
                    }
                }
            }
        }
        if constexpr (Coalesce)
        {
            const uint32_t discarded = noOpMask & ~keepMask;
            for (uint32_t pending = discarded; pending != 0u; pending &= pending - 1u)
                entries[std::countr_zero(pending)].valid = false;
            pendingMask &= ~discarded;
        }
        return inheritedSticky;
    }

'''
anchor='    constexpr uint8_t laneForComponent(uint32_t component)'
assert text.count(anchor)==1;text=text.replace(anchor,helper+anchor)
old='''            uint32_t inheritedSticky = 0u;
            for (uint32_t pending = m_flagPending; pending != 0u; pending &= pending - 1u)
            {
                FlagPipelineEntry &older = m_flagPipeline[static_cast<uint32_t>(std::countr_zero(pending))];
                if (!older.valid)
                    continue;
                if (older.writesStatus)
                    inheritedSticky |= ((older.status & 0xFu) | older.extraSticky) << 6;
                older.writesStatus = false;
                older.writesMac = false;
            }'''
new='''            // A stale lower bound in m_nextCommitCycle is safe: it can only
            // cause one redundant commit scan, never postpone a visible result.
            const uint32_t inheritedSticky = coalesceSupersededFlags &&
                                                (m_flagPending & (m_flagPending - 1u)) != 0u
                ? supersedeFmacEntries<true>(m_flagPipeline, m_flagPending)
                : supersedeFmacEntries<false>(m_flagPipeline, m_flagPending);'''
assert text.count(old)==1;text=text.replace(old,new)
after=text.replace('\n',newline).encode()
(out/'before-core.cpp').write_bytes(before);source.write_bytes(after)
record={'scope':'Coalesce only already-superseded MAC/status no-ops, retaining the latest queue entry/deadline; CLIP/FSSET and all real results remain',
    'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),
    'fallback':'PS2X_VU1_COALESCE_FLAGS=0','status':'Experimental; exact E/Continue cycles and flags must match'}
(out/'integration.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))

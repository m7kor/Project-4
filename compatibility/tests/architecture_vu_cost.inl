// Diagnostic-only, thread-local counters. Never included in a user runner.
#include <cstdio>
#include <cstdlib>
#include <cstdint>
static const bool architectureCostEnabled=[] {const char *p=std::getenv("PS2X_ARCH_VU_COST");return p&&*p=='1';}();
struct ArchitectureVuCounts
{
    uint64_t pairs=0,nativePairs=0,nativeCycles=0,genericCycles=0,flushCycles=0,stallCycles=0,xgCalls=0,xgQwords=0;
    unsigned depth=0;
    ~ArchitectureVuCounts()
    {
        if(!architectureCostEnabled||!pairs)return;
        std::fprintf(stderr,"[architecture-vu-cost] {\"pairs\":%llu,\"native_pairs\":%llu,\"native_envelope_cycles\":%llu,\"generic_envelope_cycles\":%llu,\"flush_cycles\":%llu,\"stall_cycles\":%llu,\"xgkick_progress_calls\":%llu,\"xgkick_qwords\":%llu}\n",
            (unsigned long long)pairs,(unsigned long long)nativePairs,(unsigned long long)nativeCycles,
            (unsigned long long)genericCycles,(unsigned long long)flushCycles,(unsigned long long)stallCycles,
            (unsigned long long)xgCalls,(unsigned long long)xgQwords);
    }
};
static thread_local ArchitectureVuCounts architectureVuCounts;
struct ArchitectureVuScope
{
    const uint64_t *clock;uint64_t begin=0;unsigned kind;bool enabled;
    ArchitectureVuScope(const uint64_t *value,bool active,unsigned category):clock(value),kind(category),enabled(architectureCostEnabled&&active)
    {if(enabled){begin=*clock;++architectureVuCounts.depth;}}
    ~ArchitectureVuScope()
    {
        if(!enabled)return;
        if(--architectureVuCounts.depth==0)
        {
            const uint64_t delta=*clock>=begin?*clock-begin:0;
            if(kind==1)architectureVuCounts.nativeCycles+=delta;
            else if(kind==2)architectureVuCounts.flushCycles+=delta;
            else architectureVuCounts.genericCycles+=delta;
        }
    }
};

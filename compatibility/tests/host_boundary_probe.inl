// Private diagnostic build only. TSC ticks are host elapsed ticks, not guest cycles.
#include <intrin.h>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
static const unsigned hostProbeMode=[] {const char *p=std::getenv("PS2X_HOST_BOUNDARY_PROBE");return p?unsigned(std::atoi(p)):0u;}();
static const unsigned hostProbePeriod=[] {const char *p=std::getenv("PS2X_HOST_BOUNDARY_PERIOD");return p?unsigned(std::strtoul(p,nullptr,10)):64u;}();
static uint64_t hostProbeClock() {unsigned aux;_mm_lfence();const auto t=__rdtscp(&aux);_mm_lfence();return t;}
struct HostBoundaryCounts
{
    uint64_t entries=0,selected=0,calls[9]{},inclusive[9]{},exclusive[9]{},empty[9]{};
    unsigned depth=0;bool active=false;
    uint64_t children[64]{};
    ~HostBoundaryCounts()
    {
        if(!hostProbeMode||!entries)return;
        std::fprintf(stderr,"[host-boundary] {\"entries\":%llu,\"selected\":%llu,\"mode\":%u,\"period\":%u,\"buckets\":[",(unsigned long long)entries,(unsigned long long)selected,hostProbeMode,hostProbePeriod);
        for(unsigned i=0;i<9;++i)std::fprintf(stderr,"%s{\"kind\":%u,\"calls\":%llu,\"inclusive_tsc\":%llu,\"exclusive_tsc\":%llu,\"empty\":%llu}",i?",":"",i,(unsigned long long)calls[i],(unsigned long long)inclusive[i],(unsigned long long)exclusive[i],(unsigned long long)empty[i]);
        std::fprintf(stderr,"]}\n");
    }
};
static thread_local HostBoundaryCounts hostBoundary;
struct HostBoundaryScope
{
    unsigned kind=0,level=0;uint64_t begin=0;bool enabled=false,root=false;
    HostBoundaryScope(unsigned category,bool empty=false):kind(category),root(category==0)
    {
        if(!hostProbeMode)return;
        if(root){++hostBoundary.entries;hostBoundary.active=hostProbeMode==1||(hostProbePeriod&&hostBoundary.entries%hostProbePeriod==0);if(hostBoundary.active)++hostBoundary.selected;}
        if(!hostBoundary.active)return;
        enabled=true;level=hostBoundary.depth++;
        if(level>=64)std::abort();
        hostBoundary.children[level]=0;++hostBoundary.calls[kind];hostBoundary.empty[kind]+=empty;
        if(hostProbeMode==2)begin=hostProbeClock();
    }
    ~HostBoundaryScope()
    {
        if(!enabled)return;
        if(hostProbeMode==2){const uint64_t elapsed=hostProbeClock()-begin;hostBoundary.inclusive[kind]+=elapsed;hostBoundary.exclusive[kind]+=elapsed-hostBoundary.children[level];if(level)hostBoundary.children[level-1]+=elapsed;}
        --hostBoundary.depth;if(root)hostBoundary.active=false;
    }
};

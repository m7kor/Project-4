// Add decode-derived execution context to the original complete pipeline observer.
// Original observer remains unchanged so earlier binary/source manifests stay valid.
#define phase5StateHash phase5BaseStateHash
#define phase5Checkpoint phase5BaseCheckpoint
#include "phase5_pipeline_state.inl"
#undef phase5StateHash
#undef phase5Checkpoint
uint64_t phase5StateHash(const VU1Interpreter &v,const uint8_t *memory)
{
    uint64_t hash=phase5BaseStateHash(v,memory);
    const auto add=[&](const auto &value){hash=fnv(hash,&value,sizeof(value));};
    add(v.m_unit);add(v.m_flagsObservable);add(v.m_currentUpperInstruction);add(v.m_activeVuDataSize);
    return hash;
}
void architectureBaseCheckpoint(const VU1Interpreter &v,const uint8_t *data)
{
    static std::FILE *log=[] {
        const char *path=std::getenv("PS2X_VU1_PIPELINE_STATE_LOG");
        auto *file=path?std::fopen(path,"wb"):nullptr;
        if(!file)throw std::runtime_error("Phase5 requires an owned checkpoint log");
        return file;
    }();
    static uint64_t checkpoint=0;
    std::fprintf(log,"%llu %016llx\n",static_cast<unsigned long long>(checkpoint++),
        static_cast<unsigned long long>(phase5StateHash(v,data)));
    std::fflush(log);
}

// Test-only field-wise full retirement observer. No production serialization API.
// Host pointers/decoded-code caches and struct padding are not architectural state.
// Inactive pipeline payloads ARE included; no MAC/STATUS/CLIP field is omitted.
uint64_t architectureDetailHash(const VU1Interpreter &v, const uint8_t *memory)
{
    uint64_t hash = 0xCBF29CE484222325ull;
    size_t field=0;
    const char *path=std::getenv("PS2X_VU1_DETAIL_LOG");
    auto *file=path?std::fopen(path,"wb"):nullptr;
    if(!file)throw std::runtime_error("Missing private detail log");
    const auto add = [&](const char *name,const auto &value) {
        hash=fnv(hash,&value,sizeof(value));
        std::fprintf(file,"%zu %s ",field++,name);
        const auto *bytes=reinterpret_cast<const uint8_t *>(&value);
        for(size_t i=0;i<sizeof(value);++i)std::fprintf(file,"%02x",bytes[i]);
        std::fprintf(file,"\n");
    };
    const auto &s = v.m_state;
    add("s.vf",s.vf);add("s.vi",s.vi);add("s.acc",s.acc);add("s.q",s.q);add("s.p",s.p);add("s.i",s.i);add("s.r",s.r);add("s.pc",s.pc);
    add("s.mac",s.mac);add("s.status",s.status);add("s.clip",s.clip);add("s.cycles",s.cycles);add("s.ebit",s.ebit);add("s.haltAfterDelaySlot",s.haltAfterDelaySlot);
    add("s.dBitEnabled",s.dBitEnabled);add("s.tBitEnabled",s.tBitEnabled);add("s.stoppedByD",s.stoppedByD);add("s.stoppedByT",s.stoppedByT);
    add("s.top",s.top);add("s.itop",s.itop);add("s.branchPending",s.branchPending);add("s.branchTarget",s.branchTarget);add("s.branchDelay",s.branchDelay);
    for (const auto &e : v.m_flagPipeline)
    { add("e.readyCycle",e.readyCycle);add("e.issueCycle",e.issueCycle);add("e.mac",e.mac);add("e.status",e.status);add("e.extraSticky",e.extraSticky);add("e.clip",e.clip);
      add("e.valid",e.valid);add("e.writesMac",e.writesMac);add("e.writesStatus",e.writesStatus);add("e.writesSticky",e.writesSticky);add("e.writesClip",e.writesClip); }
    const auto scalar = [&](const auto &e) {add("e.readyCycle",e.readyCycle);add("e.value",e.value);add("e.statusDi",e.statusDi);add("e.valid",e.valid);};
    scalar(v.m_fdiv);for (const auto &e : v.m_efu) scalar(e);
    for (const auto &e : v.m_storePipeline)
    {add("e.readyCycle",e.readyCycle);add("e.address",e.address);add("e.words",e.words);add("e.laneMask",e.laneMask);add("e.valid",e.valid);}
    for (const auto &e : v.m_vfWritePipeline)
    {add("e.readyCycle",e.readyCycle);add("e.sequence",e.sequence);add("e.value",e.value);add("e.reg",e.reg);add("e.laneMask",e.laneMask);add("e.valid",e.valid);}
    for (const auto &e : v.m_viWritePipeline)
    {add("e.readyCycle",e.readyCycle);add("e.sequence",e.sequence);add("e.value",e.value);add("e.reg",e.reg);add("e.valid",e.valid);}
    for (const auto &e : v.m_accWritePipeline)
    {add("e.readyCycle",e.readyCycle);add("e.sequence",e.sequence);add("e.value",e.value);add("e.laneMask",e.laneMask);add("e.valid",e.valid);}
    add("v.m_flagPending",v.m_flagPending);add("v.m_efuPending",v.m_efuPending);add("v.m_storePending",v.m_storePending);add("v.m_vfPending",v.m_vfPending);add("v.m_viPending",v.m_viPending);add("v.m_accPending",v.m_accPending);
    add("v.m_nextCommitCycle",v.m_nextCommitCycle);add("v.m_maxPendingReady",v.m_maxPendingReady);add("v.m_vfReady",v.m_vfReady);add("v.m_viReady",v.m_viReady);add("v.m_accReady",v.m_accReady);
    add("v.m_vfLatestWrite",v.m_vfLatestWrite);add("v.m_viLatestWrite",v.m_viLatestWrite);add("v.m_accLatestWrite",v.m_accLatestWrite);
    add("v.m_cycle",v.m_cycle);add("v.m_nextWriteSequence",v.m_nextWriteSequence);add("v.m_efuResourceReady",v.m_efuResourceReady);add("v.m_workingClip",v.m_workingClip);
    add("v.m_viBranchBackupValue",v.m_viBranchBackupValue);add("v.m_viBranchBackupReg",v.m_viBranchBackupReg);add("v.m_viBranchBackupValid",v.m_viBranchBackupValid);
    add("v.m_stopRequested",v.m_stopRequested);add("v.m_pendingHaltD",v.m_pendingHaltD);add("v.m_pendingHaltT",v.m_pendingHaltT);
    add("v.m_pairFlagsDirect",v.m_pairFlagsDirect);add("v.m_pairProductSum",v.m_pairProductSum);add("v.m_pairStoreDirect",v.m_pairStoreDirect);add("v.m_pairFlagsLive",v.m_pairFlagsLive);add("v.m_statusObservable",v.m_statusObservable);
    const auto &x=v.m_xgkick;
    add("x.packet",x.packet);add("x.sourceAddress",x.sourceAddress);add("x.totalBytes",x.totalBytes);add("x.copiedBytes",x.copiedBytes);add("x.currentTagEnd",x.currentTagEnd);
    add("x.cycleCredit",x.cycleCredit);add("x.issueCycle",x.issueCycle);add("x.active",x.active);add("x.currentTagEop",x.currentTagEop);
    hash=fnv(hash,memory,PS2_VU1_DATA_SIZE);
    add("v.m_unit",v.m_unit);add("v.m_flagsObservable",v.m_flagsObservable);
    add("v.m_currentUpperInstruction",v.m_currentUpperInstruction);add("v.m_activeVuDataSize",v.m_activeVuDataSize);
    std::fprintf(file,"%zu VU-memory-hash %016llx\n",field,static_cast<unsigned long long>(fnv(0xcbf29ce484222325ull,memory,PS2_VU1_DATA_SIZE)));
    std::fclose(file);return hash;
}

void phase5Checkpoint(const VU1Interpreter &v,const uint8_t *data)
{
    static bool once=false;
    if(!once){once=true;architectureDetailHash(v,data);}
    architectureBaseCheckpoint(v,data);
}

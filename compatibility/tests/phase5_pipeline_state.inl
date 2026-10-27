// Test-only field-wise full retirement observer. No production serialization API.
// Host pointers/decoded-code caches and struct padding are not architectural state.
// Inactive pipeline payloads ARE included; no MAC/STATUS/CLIP field is omitted.
uint64_t phase5StateHash(const VU1Interpreter &v, const uint8_t *memory)
{
    uint64_t hash = 0xCBF29CE484222325ull;
    const auto add = [&](const auto &value) { hash = fnv(hash, &value, sizeof(value)); };
    const auto &s = v.m_state;
    add(s.vf);add(s.vi);add(s.acc);add(s.q);add(s.p);add(s.i);add(s.r);add(s.pc);
    add(s.mac);add(s.status);add(s.clip);add(s.cycles);add(s.ebit);add(s.haltAfterDelaySlot);
    add(s.dBitEnabled);add(s.tBitEnabled);add(s.stoppedByD);add(s.stoppedByT);
    add(s.top);add(s.itop);add(s.branchPending);add(s.branchTarget);add(s.branchDelay);
    for (const auto &e : v.m_flagPipeline)
    { add(e.readyCycle);add(e.issueCycle);add(e.mac);add(e.status);add(e.extraSticky);add(e.clip);
      add(e.valid);add(e.writesMac);add(e.writesStatus);add(e.writesSticky);add(e.writesClip); }
    const auto scalar = [&](const auto &e) {add(e.readyCycle);add(e.value);add(e.statusDi);add(e.valid);};
    scalar(v.m_fdiv);for (const auto &e : v.m_efu) scalar(e);
    for (const auto &e : v.m_storePipeline)
    {add(e.readyCycle);add(e.address);add(e.words);add(e.laneMask);add(e.valid);}
    for (const auto &e : v.m_vfWritePipeline)
    {add(e.readyCycle);add(e.sequence);add(e.value);add(e.reg);add(e.laneMask);add(e.valid);}
    for (const auto &e : v.m_viWritePipeline)
    {add(e.readyCycle);add(e.sequence);add(e.value);add(e.reg);add(e.valid);}
    for (const auto &e : v.m_accWritePipeline)
    {add(e.readyCycle);add(e.sequence);add(e.value);add(e.laneMask);add(e.valid);}
    add(v.m_flagPending);add(v.m_efuPending);add(v.m_storePending);add(v.m_vfPending);add(v.m_viPending);add(v.m_accPending);
    add(v.m_nextCommitCycle);add(v.m_maxPendingReady);add(v.m_vfReady);add(v.m_viReady);add(v.m_accReady);
    add(v.m_vfLatestWrite);add(v.m_viLatestWrite);add(v.m_accLatestWrite);
    add(v.m_cycle);add(v.m_nextWriteSequence);add(v.m_efuResourceReady);add(v.m_workingClip);
    add(v.m_viBranchBackupValue);add(v.m_viBranchBackupReg);add(v.m_viBranchBackupValid);
    add(v.m_stopRequested);add(v.m_pendingHaltD);add(v.m_pendingHaltT);
    add(v.m_pairFlagsDirect);add(v.m_pairProductSum);add(v.m_pairStoreDirect);add(v.m_pairFlagsLive);add(v.m_statusObservable);
    const auto &x=v.m_xgkick;
    add(x.packet);add(x.sourceAddress);add(x.totalBytes);add(x.copiedBytes);add(x.currentTagEnd);
    add(x.cycleCredit);add(x.issueCycle);add(x.active);add(x.currentTagEop);
    hash=fnv(hash,memory,PS2_VU1_DATA_SIZE);
    return hash;
}
void phase5Checkpoint(const VU1Interpreter &v, const uint8_t *data)
{
    static std::FILE *log=[] {
        const char *path=std::getenv("PS2X_VU1_PIPELINE_STATE_LOG");
        auto *file=path?std::fopen(path,"wb"):nullptr;
        if(!file) throw std::runtime_error("Phase5 requires a private checkpoint log");
        return file;
    }();
    static uint64_t checkpoint=0;
    std::fprintf(log,"%llu %016llx\n",static_cast<unsigned long long>(checkpoint++),
                 static_cast<unsigned long long>(phase5StateHash(v,data)));
    std::fflush(log);
}

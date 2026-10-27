// Synthetic pending queues, not modifications to any running guest or game save.
int phase5RandomRetirement()
{
    PS2Memory memory;if(!memory.initialize())return 2;
    GS gs;gs.init(memory.getGSVRAM(),static_cast<uint32_t>(PS2_GS_VRAM_SIZE),&memory.gs());
    uint32_t seed=0x51F15EEDu;
    const auto random=[&]() {seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;};
    for(uint32_t test=0;test<512;++test)
    {
        auto unit=std::make_unique<VU1Interpreter>();auto &v=*unit;
        for(uint32_t b=0;b<PS2_VU1_DATA_SIZE;++b)memory.getVU1Data()[b]=static_cast<uint8_t>(random());
        v.m_cycle=16;v.m_state.status=random()&0xfffu;v.m_state.mac=random()&0xffffu;v.m_state.clip=random()&0xffffffu;
        for(uint32_t i=0;i<v.m_flagPipeline.size();++i)
        {
            auto &e=v.m_flagPipeline[i];e.issueCycle=random()%17;e.readyCycle=e.issueCycle+4;
            e.mac=random()&0xffffu;e.status=random()&0xfffu;e.extraSticky=random()&15u;e.clip=random()&0xffffffu;
            e.valid=(random()&3u)!=0;e.writesMac=random()&1;e.writesStatus=random()&1;e.writesSticky=random()&1;e.writesClip=random()&1;
            if(e.valid||(random()&7u)==0)v.m_flagPending|=1u<<i;
        }
        v.m_fdiv={uint64_t(random()%71),float(random()%1000)/8.0f,random()&0x30u,(random()&1u)!=0};
        for(uint32_t i=0;i<v.m_efu.size();++i)
        {auto &e=v.m_efu[i];e.readyCycle=random()%71;e.value=float(random()%1000)/8.0f;e.valid=random()&1;if(e.valid)v.m_efuPending|=1u<<i;}
        for(uint32_t i=0;i<v.m_storePipeline.size();++i)
        {
            auto &e=v.m_storePipeline[i];e.readyCycle=random()%18;e.address=(random()%8u)*16;e.laneMask=random()&15u;e.valid=random()&1;
            for(auto &word:e.words)word=random();if(e.valid)v.m_storePending|=1u<<i;
        }
        for(uint32_t i=0;i<v.m_vfWritePipeline.size();++i)
        {
            auto &e=v.m_vfWritePipeline[i];e.readyCycle=random()%21;e.sequence=++v.m_nextWriteSequence;e.reg=1+random()%3;e.laneMask=random()&15u;e.valid=random()&1;
            for(auto &f:e.value)f=float(random()%1000)/8.0f;
            if(e.valid){v.m_vfPending|=1u<<i;for(uint32_t c=0;c<4;++c)if(e.laneMask&(8u>>c))v.m_vfLatestWrite[e.reg][c]=e.sequence;}
        }
        for(uint32_t i=0;i<v.m_viWritePipeline.size();++i)
        {
            auto &e=v.m_viWritePipeline[i];e.readyCycle=random()%21;e.sequence=++v.m_nextWriteSequence;e.reg=1+random()%3;e.value=int32_t(random());e.valid=random()&1;
            if(e.valid){v.m_viPending|=1u<<i;v.m_viLatestWrite[e.reg]=e.sequence;}
        }
        for(uint32_t i=0;i<v.m_accWritePipeline.size();++i)
        {
            auto &e=v.m_accWritePipeline[i];e.readyCycle=random()%21;e.sequence=++v.m_nextWriteSequence;e.laneMask=random()&15u;e.valid=random()&1;
            for(auto &f:e.value)f=float(random()%1000)/8.0f;
            if(e.valid){v.m_accPending|=1u<<i;for(uint32_t c=0;c<4;++c)if(e.laneMask&(8u>>c))v.m_accLatestWrite[c]=e.sequence;}
        }
        for(uint32_t step=0;step<12;++step)
        {
            unit->m_cycle+=step?1+random()%8u:0u;
            // Empty code retires only pending events, with no synthetic opcode assumptions.
            unit->resume(memory.getVU1Code(),0,memory.getVU1Data(),PS2_VU1_DATA_SIZE,gs,&memory,0,0,1);
            phase5Checkpoint(*unit,memory.getVU1Data());
            if(step==3||step==8)unit=std::make_unique<VU1Interpreter>(*unit);
            if(step==10&&test%4==0)unit->controlReset();
        }
    }
    std::puts("PASS deterministic seed0x51f15eed:512 queues x12 checkpoints, copies and controlReset");
    return 0;
}

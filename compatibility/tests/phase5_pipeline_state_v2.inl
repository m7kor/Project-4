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
void phase5Checkpoint(const VU1Interpreter &v,const uint8_t *data)
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

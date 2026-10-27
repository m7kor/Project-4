"""Build a field-labelled observer for one minimized failing captured state."""
from pathlib import Path
import re,sys
ROOT=Path(__file__).resolve().parents[1]
v1=(ROOT/'tests/phase5_pipeline_state.inl').read_text();v2=(ROOT/'tests/phase5_pipeline_state_v2.inl').read_text()
body=v1[:v1.index('void phase5Checkpoint(')].replace('uint64_t phase5StateHash(', 'uint64_t architectureDetailHash(')
needle='const auto add = [&](const auto &value) { hash = fnv(hash, &value, sizeof(value)); };';assert body.count(needle)==1
body=body.replace(needle,'''size_t field=0;
    const char *path=std::getenv("PS2X_VU1_DETAIL_LOG");
    auto *file=path?std::fopen(path,"wb"):nullptr;
    if(!file)throw std::runtime_error("Missing private detail log");
    const auto add = [&](const char *name,const auto &value) {
        hash=fnv(hash,&value,sizeof(value));
        std::fprintf(file,"%zu %s ",field++,name);
        const auto *bytes=reinterpret_cast<const uint8_t *>(&value);
        for(size_t i=0;i<sizeof(value);++i)std::fprintf(file,"%02x",bytes[i]);
        std::fprintf(file,"\\n");
    };''')
body=re.sub(r'\badd\(([^();]+)\);',lambda m:'add("'+m[1]+'",'+m[1]+');',body)
body=body.replace('    return hash;', '''    add("v.m_unit",v.m_unit);add("v.m_flagsObservable",v.m_flagsObservable);
    add("v.m_currentUpperInstruction",v.m_currentUpperInstruction);add("v.m_activeVuDataSize",v.m_activeVuDataSize);
    std::fprintf(file,"%zu VU-memory-hash %016llx\\n",field,static_cast<unsigned long long>(fnv(0xcbf29ce484222325ull,memory,PS2_VU1_DATA_SIZE)));
    std::fclose(file);return hash;''')
content=v2.replace('void phase5Checkpoint(', 'void architectureBaseCheckpoint(')+'\n'+body+'''
void phase5Checkpoint(const VU1Interpreter &v,const uint8_t *data)
{
    static bool once=false;
    if(!once){once=true;architectureDetailHash(v,data);}
    architectureBaseCheckpoint(v,data);
}
'''
target=ROOT/'tests/architecture_detail_state.inl';assert not target.exists();target.write_text(content,encoding='utf-8')
builder=ROOT/'tools/build_phase5_state_probe.py';script=builder.read_text();needle="observer=ROOT/'tests'/('phase5_pipeline_state_v2.inl' if len(sys.argv)>3 and sys.argv[3]=='v2' else 'phase5_pipeline_state.inl')";assert script.count(needle)==1
script=script.replace(needle,"observer=ROOT/'tests/architecture_detail_state.inl'")
sys.argv=[str(builder),'architecture-aot-detail-01','architecture-aot-01','v2']
exec(compile(script,str(builder),'exec'),{'__file__':str(builder),'__name__':'__main__'})

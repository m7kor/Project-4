#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cfenv>
extern void ps2Vu1RetireVectorWrite(float *,const float *,const uint64_t *,uint64_t,uint8_t);
int main()
{
    uint64_t seed=0xF15E5A1FEED12345ull,checks=0;
    const auto random=[&]() {seed^=seed<<13;seed^=seed>>7;seed^=seed<<17;return seed;};
    constexpr uint32_t edges[]={0u,0x80000000u,0x7f800000u,0xff800000u,0x7f800001u,0xffc12345u,1u,0x007fffffu,0x7f7fffffu,0xffffffffu};
    for(uint32_t lanes=0;lanes<16;++lanes)
    for(uint32_t equals=0;equals<16;++equals)
    for(uint32_t pass=0;pass<4096;++pass)
    {
        const uint64_t sequence=random();uint64_t latest[4];uint32_t old[4],value[4],expected[4];
        for(uint32_t component=0;component<4;++component)
        {
            old[component]=pass<10?edges[pass]:uint32_t(random());value[component]=uint32_t(random());
            latest[component]=(equals&(1u<<component))?sequence:(sequence^(1ull<<(random()%64)));
            expected[component]=((lanes&(8u>>component))&&latest[component]==sequence)?value[component]:old[component];
        }
        float destination[4],source[4];std::memcpy(destination,old,sizeof(old));std::memcpy(source,value,sizeof(value));
        if(pass%64==0)std::feclearexcept(FE_ALL_EXCEPT);
        ps2Vu1RetireVectorWrite(destination,source,latest,sequence,uint8_t(lanes));
        if(std::memcmp(destination,expected,sizeof(expected))!=0)
        {std::printf("FAIL lane=%u match=%u pass=%u\n",lanes,equals,pass);return 2;}
        if(pass%64==0&&std::fetestexcept(FE_ALL_EXCEPT))
        {std::puts("FAIL unexpected floating-point exception from bit selection");return 3;}
        ++checks;
    }
    std::printf("PASS %llu bit-exact independent-oracle cases, all lane/sequence masks, arbitrary payload bits and exception probes\n",(unsigned long long)checks);
}

#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cfenv>
extern bool ps2Vu1ClassifyNormalFmac(const float *,uint8_t,uint8_t[4]);
int main()
{
    uint64_t seed=0xF15E5A1F09876543ull,checks=0;
    const auto random=[&]() {seed^=seed<<13;seed^=seed>>7;seed^=seed<<17;return uint32_t(seed);};
    constexpr uint32_t edges[]={0u,1u,0x007fffffu,0x00800000u,0x00ffffffu,0x01000000u,0x7e800000u,0x7effffffu,0x7f000000u,0x7f7fffffu,0x7f800000u,0x7f800001u,0xffffffffu};
    for(uint32_t dest=0;dest<16;++dest)
    for(uint32_t pass=0;pass<65536;++pass)
    {
        uint32_t input[4];uint8_t expected[4]{};bool normal=true;
        for(uint32_t c=0;c<4;++c)
        {
            input[c]=pass<52?edges[(pass+c)%13]^((pass&1u)<<31):random();
            if(!(dest&(8u>>c)))continue;
            const uint32_t exp=(input[c]>>23)&255u;
            normal=normal&&(exp>=2&&exp<=253);
            expected[c]=(input[c]>>31)?2:0;
        }
        float values[4];std::memcpy(values,input,sizeof(input));uint8_t flags[4]={0xa5,0xa5,0xa5,0xa5};
        if(pass%64==0)std::feclearexcept(FE_ALL_EXCEPT);
        const bool result=ps2Vu1ClassifyNormalFmac(values,uint8_t(dest),flags);
        const uint8_t untouched[4]={0xa5,0xa5,0xa5,0xa5};
        if(result!=normal||std::memcmp(flags,normal?expected:untouched,4)||std::memcmp(values,input,sizeof(input)))
        {std::printf("FAIL mask=%u pass=%u normal=%d result=%d\n",dest,pass,int(normal),int(result));return 2;}
        if(pass%64==0&&std::fetestexcept(FE_ALL_EXCEPT)){std::puts("FAIL FP exception from classification");return 3;}
        ++checks;
    }
    uint8_t flags[4]={1,2,3,4};if(!ps2Vu1ClassifyNormalFmac(nullptr,0,flags)||flags[0]||flags[1]||flags[2]||flags[3])return 4;
    std::printf("PASS %llu independent predicate/flag/payload checks plus null zero-mask, boundary exponents and FP exception probes\n",(unsigned long long)checks);
}

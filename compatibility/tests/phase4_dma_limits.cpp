// Public synthetic data only. Exact boundary and control-state cycle regressions.
#include "runtime/ps2_memory.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
static void require(bool value,const char *message){if(!value)throw std::runtime_error(message);}
static void tag(PS2Memory &m,uint32_t at,uint32_t qwc,uint32_t id,uint32_t addr=0){
    uint64_t words[2]={qwc|(uint64_t(id)<<28)|(uint64_t(addr)<<32),0};std::memcpy(m.getRDRAM()+at,words,16);
}
static void kick(PS2Memory &m){m.writeIORegister(0x1000a030,0x10000);m.writeIORegister(0x1000a020,0);m.writeIORegister(0x1000a000,0x105);}
int main(){try{
    PS2Memory m;require(m.initialize(),"memory init failed");uint64_t bytes=0;uint32_t packets=0;
    m.setGifPacketCallback([&](const uint8_t *,uint32_t n){bytes+=n;++packets;});
    tag(m,0x10000,0,5,0x11000);tag(m,0x10010,0,5,0x11000);tag(m,0x10020,0,7);
    tag(m,0x11000,1,3,0x200000);tag(m,0x11010,0,6);kick(m);
    require(bytes==32&&packets==1,"legitimate repeated CALL/REF/RET lost data");
    require(m.consumeCompletedDmacCauses()==std::vector<uint32_t>{2},"finite chain completion missing");
    bytes=0;packets=0;tag(m,0x10000,0,2,0x10000);bool cycle=false;
    try{kick(m);}catch(const std::runtime_error &e){cycle=std::strstr(e.what(),"chain-cycle")!=nullptr;}
    require(cycle&&bytes==0&&packets==0,"cyclic NEXT chain must fail without publishing");
    for(unsigned i=0;i<256;++i)tag(m,0x10000+i*16,65535,3,0x200000);
    tag(m,0x11000,256,0,0x200000);kick(m);
    require(bytes==(uint64_t{1}<<28)&&packets==1,"exact 256MiB boundary must complete");
    require(m.consumeCompletedDmacCauses()==std::vector<uint32_t>{2},"boundary chain completion missing");
    bytes=0;packets=0;
    for(unsigned i=0;i<257;++i)tag(m,0x10000+i*16,65535,3,0x200000);
    tag(m,0x11010,0,7);bool limit=false;
    try{kick(m);}catch(const std::runtime_error &e){limit=std::strstr(e.what(),"payload-limit")!=nullptr;}
    require(limit&&bytes==0&&packets==0,"oversized chain must not publish partial bytes");
    require(m.consumeCompletedDmacCauses().empty(),"oversized chain must not signal success");
    std::cout<<"PASS repeated-CALL/RET, cycle, exact256MiB, above-limit-no-publication\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}

#include "runtime/gs/gs_frontend.h"
#include <vector>
#include <array>
#include <cstring>
#include <iostream>

int main() {
    std::vector<uint8_t> expected;
    for (unsigned fmt: {2u,3u}) {
        std::vector<uint8_t> vram(4*1024*1024);
        GS gs;
        gs.init(vram.data(),static_cast<uint32_t>(vram.size()),nullptr);
        gs.writeRegister(GS_REG_BITBLTBUF, (1ull<<16)|(1ull<<48));
        gs.writeRegister(GS_REG_TRXPOS,0);
        gs.writeRegister(GS_REG_TRXREG,2ull|(2ull<<32));
        gs.writeRegister(GS_REG_TRXDIR,0);
        std::array<uint8_t,32> packet{};
        uint64_t tag=1ull|(1ull<<15)|(uint64_t(fmt)<<58);
        std::memcpy(packet.data(),&tag,8);
        for(unsigned i=0;i<16;++i)packet[16+i]=static_cast<uint8_t>(i+17);
        gs.processGIFPacket(packet.data(),32);
        if(fmt==2)expected=vram;
        else if(vram!=expected){std::cerr<<"IMAGE2 VRAM differs from IMAGE\n";return 1;}
    }
    unsigned changed=0;for(auto b:expected)changed+=b!=0;
    if(changed!=16){std::cerr<<"IMAGE reference upload failed\n";return 2;}
    std::cout<<"PASS IMAGE2 upload equals IMAGE across entire 4 MiB VRAM\n";
}

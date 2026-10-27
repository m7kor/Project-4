#include "runtime/gs/ps2_gif_arbiter.h"
#include <array>
#include <vector>
#include <cstring>
#include <iostream>

// ps2tek GIFtag FLG=2 and FLG=3 are IMAGE. DIRECTHL cannot preempt PATH3 IMAGE.
int main() {
    for (unsigned format=0;format<4;++format) {
        std::vector<int> observed;
        GifArbiter arbiter;
        arbiter.setProcessPathPacketFn([&](GifPathId path,const uint8_t*,uint32_t){observed.push_back(int(path));});
        std::array<uint8_t,32> path3{},direct{};
        uint64_t tag=1ull | (uint64_t(format)<<58);
        std::memcpy(path3.data(),&tag,8);
        arbiter.submit(GifPathId::Path2,direct.data(),32,true);
        arbiter.submit(GifPathId::Path3,path3.data(),32);
        arbiter.drain();
        std::vector<int> expected=format>=2?std::vector<int>{3,2}:std::vector<int>{2,3};
        if(observed!=expected){std::cerr<<"FAIL FLG="<<format<<" DIRECTHL IMAGE barrier\n";return 1;}
    }
    std::cout<<"PASS PACKED/REGLIST/IMAGE/IMAGE2 arbitration\n";
}

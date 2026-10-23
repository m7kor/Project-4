// Procedural operation benchmarks: timings do not certify game FPS.
#include "runtime/ps2_memory.h"
#include "runtime/ps2_vu1.h"
#include "runtime/gs/gs_frontend.h"
#include "runtime/gs/gs_cpu_backend.h"
#include <chrono>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string mode = argv[1];
    auto memory = std::make_unique<PS2Memory>();
    if (!memory->initialize()) return 3;
    uint64_t checksum = 0, operations = 0;
    double milliseconds = 0;
    using Clock = std::chrono::steady_clock;
    if (mode == "present-static" || mode == "present-changing") {
        GSCpuBackend backend;
        backend.Initialize(memory->getGSVRAM(), PS2_GS_VRAM_SIZE);
        GSPresentationRequest request{};
        request.pmode = 1u;
        request.dispfb1 = 8ull << 9;
        request.display1 = (511ull << 32) | (447ull << 44);
        backend.WriteVram(GS_PSM_CT32, 0u, 8u, 0u, 0u, 201u);
        backend.Present(request); // warm conversion cache, outside measured work
        operations = 200;
        const auto start = Clock::now();
        for (uint64_t i = 0; i < operations; ++i) {
            const uint8_t expected = mode == "present-changing" && !(i & 1u) ? 101u : 201u;
            if (mode == "present-changing")
                backend.WriteVram(GS_PSM_CT32, 0u, 8u, 0u, 0u, expected);
            request.vsyncTick = i;
            const auto frame = backend.Present(request);
            if (!frame || frame.width != 512u || frame.height != 448u || frame.pixels[0] != expected) return 7;
            checksum += frame.pixels[0];
        }
        milliseconds = std::chrono::duration<double,std::milli>(Clock::now()-start).count();
        if (checksum != (mode == "present-static" ? 40200u : 30200u)) return 8;
    } else if (mode == "xgkick") {
        auto vu = std::make_unique<VU1Interpreter>();
        GS gs;
        gs.init(memory->getGSVRAM(),PS2_GS_VRAM_SIZE,&memory->gs());
        const uint32_t lower = (0x40u<<25) | (1u<<11) | ((0x6Cu & 0x7Cu)<<4) | 0x3Cu;
        const uint32_t upper = 0x2FF;
        std::memcpy(memory->getVU1Code(),&lower,4);
        std::memcpy(memory->getVU1Code()+4,&upper,4);
        const uint64_t tag = 1u | (1u<<15) | (uint64_t(2)<<58);
        std::memcpy(memory->getVU1Data(),&tag,8);
        for (unsigned i=0;i<16;++i) memory->getVU1Data()[16+i]=uint8_t(i+1);
        uint64_t packets = 0;
        bool invalid = false;
        memory->setGifPacketCallback([&](const uint8_t* data,uint32_t bytes) {
            ++packets;
            if (bytes!=32 || std::memcmp(data,memory->getVU1Data(),32)!=0) invalid=true;
            checksum+=bytes+data[16]+data[31];
        });
        operations=100000;
        const auto start=Clock::now();
        for (uint64_t i=0;i<operations;++i) {
            vu->state().vi[1]=0;
            vu->execute(memory->getVU1Code(),PS2_VU1_CODE_SIZE,memory->getVU1Data(),
                PS2_VU1_DATA_SIZE,gs,memory.get(),0,0,0,3);
        }
        milliseconds=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
        if (invalid || packets!=operations || checksum!=operations*49u) return 4;
    } else if (mode == "vif1") {
        const uint32_t packet[] = {0x6C010000,0x12345678,0x87654321,0x01020304,0xAABBCCDD};
        operations=1000000;
        const auto start=Clock::now();
        for (uint64_t i=0;i<operations;++i) memory->processVIF1Data(reinterpret_cast<const uint8_t*>(packet),sizeof(packet));
        milliseconds=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
        if (std::memcmp(memory->getVU1Data(),packet+1,16)!=0) return 5;
        checksum=packet[1]+uint64_t(packet[2])+packet[3]+packet[4];
    } else if (mode == "timers") {
        memory->writeIORegister(0x10003020,0x1F123456);
        operations=10000000;
        const auto start=Clock::now();
        for (uint64_t i=0;i<operations;++i) checksum+=memory->advanceEeTimers(4);
        milliseconds=std::chrono::duration<double,std::milli>(Clock::now()-start).count();
        checksum+=memory->readIORegister(0x10003020);
        // GIF_STAT low bits mirror GIF_MODE/GIF_CTRL, both zero in this fixture.
        if (checksum!=0x123450) return 6;
    } else return 2;
    std::cout<<"{\"mode\":\""<<mode<<"\",\"operations\":"<<operations
        <<",\"milliseconds\":"<<milliseconds<<",\"checksum\":"<<checksum<<"}\n";
    return 0;
}

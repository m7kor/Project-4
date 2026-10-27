// Narrow production-VIF replay: complete captured DIRECT transactions, not a
// universal game checkpoint or cycle-accurate DMAC replay.
#include "runtime/ps2_memory.h"
#include "runtime/gs/gs_frontend.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <vector>

uint64_t hashBytes(uint64_t h,const void *p,size_t n){
    auto bytes=static_cast<const uint8_t *>(p);
    for(size_t i=0;i<n;++i){h^=bytes[i];h*=0x100000001b3ull;}return h;
}
std::string hex64(uint64_t value){std::ostringstream out;out<<std::hex<<std::setfill('0')<<std::setw(16)<<value;return out.str();}
struct Observation { VIFRegisters regs{}; uint32_t image=0,remaining=0,assembled=0; } observed;
void ps2xVifReplayObserve(const VIFRegisters &regs,uint32_t image,uint32_t remaining,uint32_t assembled){
    observed.regs=regs;observed.image=image;observed.remaining=remaining;observed.assembled=assembled;
}
int main(int argc,char **argv){
 try{
    if(argc<3||argc>4)throw std::runtime_error("fixture.bin chunk-bytes [irq-probe]");
    const uint32_t chunk=static_cast<uint32_t>(std::stoul(argv[2]));
    if(chunk<4||chunk>1048576||chunk%4)throw std::runtime_error("word-aligned chunk4..1048576 required");
    const bool irq=argc==4&&std::string(argv[3])=="irq-probe";
    std::ifstream in(argv[1],std::ios::binary);std::array<uint64_t,4> header{};
    if(!in.read(reinterpret_cast<char *>(header.data()),sizeof(header))||header[0]!=0x31594c5052464956ull||header[1]!=1||header[2]!=4||header[3]!=0)
        throw std::runtime_error("invalid or incomplete VIF replay header");
    PS2Memory memory;if(!memory.initialize())throw std::runtime_error("memory init failed");
    GS gs;gs.init(memory.getGSVRAM(),PS2_GS_VRAM_SIZE,&memory.gs());
    memory.processVIF1Data(nullptr,0); // Observe the real initialized relevant state.
    uint64_t packetHash=0xcbf29ce484222325ull;uint32_t packets=0;
    memory.setGifPacketCallback([&](const uint8_t *data,uint32_t bytes){
        packetHash=hashBytes(packetHash,&bytes,sizeof(bytes));packetHash=hashBytes(packetHash,data,bytes);++packets;
        gs.processGIFPacket(data,bytes);
    });
    const auto snapshot=[&](int event,uint64_t ee){
        uint64_t ram=hashBytes(0xcbf29ce484222325ull,memory.getRDRAM(),PS2_RAM_SIZE);
        uint64_t vu=hashBytes(0xcbf29ce484222325ull,memory.getVU1Data(),PS2_VU1_DATA_SIZE);
        uint64_t vram=hashBytes(0xcbf29ce484222325ull,memory.getGSVRAM(),PS2_GS_VRAM_SIZE);
        std::cout<<"{\"event\":"<<event<<",\"recorded_ee\":"<<ee<<",\"vif_code\":"<<observed.regs.code
          <<",\"vif_stat\":"<<observed.regs.stat<<",\"image_qwc\":"<<observed.image<<",\"direct_remaining\":"<<observed.remaining
          <<",\"assembled\":"<<observed.assembled<<",\"register_hash\":\""<<hex64(hashBytes(0xcbf29ce484222325ull,&observed.regs,sizeof(observed.regs)))<<"\",\"packets\":"<<packets
          <<",\"packet_hash\":\""<<hex64(packetHash)<<"\",\"ram\":\""<<hex64(ram)<<"\",\"vu_data\":\""<<hex64(vu)<<"\",\"vram\":\""<<hex64(vram)<<"\"}\n";
    };
    snapshot(-1,0);uint64_t lastEe=0;
    for(uint32_t index=0;index<header[2];++index){
        std::array<uint64_t,6> h{};
        if(!in.read(reinterpret_cast<char *>(h.data()),sizeof(h))||h[0]!=index||h[1]>UINT32_MAX||h[2]>4*1024*1024||h[2]%16||!h[2]||h[3]<lastEe)
            throw std::runtime_error("invalid ordered VIF event");
        const uint32_t opcode=(h[1]>>24)&127,declared=(h[1]&65535)?uint32_t(h[1]&65535):65536u;
        if(opcode!=0x50||declared*16ull!=h[2])throw std::runtime_error("unsupported DIRECT transaction");
        lastEe=h[3];std::vector<uint8_t> payload(static_cast<size_t>(h[2]));
        if(!in.read(reinterpret_cast<char *>(payload.data()),payload.size()))throw std::runtime_error("truncated VIF event payload");
        if(observed.image!=h[5])throw std::runtime_error("cross-command pending IMAGE state differs from capture");
        uint32_t code=static_cast<uint32_t>(h[1])|(irq?0x80000000u:0u);const uint32_t before=packets;
        memory.processVIF1Data(reinterpret_cast<uint8_t *>(&code),4);
        if(packets!=before)throw std::runtime_error("DIRECT emitted before receiving payload");
        if(observed.remaining!=payload.size()||observed.assembled!=0)throw std::runtime_error("DIRECT pending state not retained at header");
        if(irq&&!(observed.regs.stat&(1u<<11)))throw std::runtime_error("VIF IRQ not visible at header decode");
        for(uint32_t pos=0;pos<payload.size();){
            const uint32_t n=std::min<uint32_t>(chunk,static_cast<uint32_t>(payload.size())-pos);
            memory.processVIF1Data(payload.data()+pos,n);pos+=n;
            if(pos<payload.size()&&packets!=before)throw std::runtime_error("DIRECT emitted before completion");
            if(pos<payload.size()&&(observed.remaining!=payload.size()-pos||observed.assembled!=pos))throw std::runtime_error("partial DIRECT state lost across input chunks");
        }
        if(packets!=before+1)throw std::runtime_error("DIRECT completion packet count differs");
        if(observed.remaining||observed.assembled)throw std::runtime_error("completed DIRECT left partial state");
        snapshot(static_cast<int>(index),h[3]);
    }
    if(in.peek()!=std::ifstream::traits_type::eof())throw std::runtime_error("unexpected trailing VIF capture data");
    return 0;
 }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}

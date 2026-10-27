// Offline DMAC and SIF transport consumer. No guest executable is loaded.
#define main phase2VifConsumerMain
#include "vif_direct_replay.cpp"
#undef main
#include "ps2_runtime.h"
#include "ps2_stubs.h"
#include "Stubs/SIF.h"
#include <nlohmann/json.hpp>
using Json=nlohmann::json;
static void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
static std::vector<uint8_t> unhex(const std::string &s){
    require(s.size()%2==0,"incomplete hex payload");std::vector<uint8_t> b;
    for(size_t i=0;i<s.size();i+=2){require(s.find_first_not_of("0123456789abcdef",i)>i+1,"invalid hex payload");b.push_back(static_cast<uint8_t>(std::stoul(s.substr(i,2),nullptr,16)));}return b;
}
int main(int argc,char **argv){try{
    require(argc==2,"fixture.json required");std::ifstream file(argv[1]);Json fixture;file>>fixture;
    require(fixture.at("schema")==1,"invalid fixture schema");const bool sif=fixture.at("kind")=="iop";
    require(sif||fixture.at("kind")=="dma","unsupported replay kind");
    PS2Memory memory;require(memory.initialize(),"memory init failed");GS gs;gs.init(memory.getGSVRAM(),PS2_GS_VRAM_SIZE,&memory.gs());
    std::unique_ptr<PS2Runtime> runtime;if(sif){ps2_stubs::resetSifState();runtime=std::make_unique<PS2Runtime>();}
    std::vector<uint8_t> ram(PS2_RAM_SIZE,0),iop(2*1024*1024);R5900Context ctx{};
    uint8_t *ee=sif?ram.data():memory.getRDRAM();uint64_t packetHash=0xcbf29ce484222325ull;uint32_t packets=0;
    memory.setGifPacketCallback([&](const uint8_t *p,uint32_t n){packetHash=hashBytes(packetHash,&n,4);packetHash=hashBytes(packetHash,p,n);++packets;gs.processGIFPacket(p,n);});
    auto store=[&](uint32_t address,const std::vector<uint8_t> &bytes){
        auto physical=address&0x1fffffffu;bool spr=(address&0xffffc000u)==0x70000000u;
        uint8_t *base=spr?memory.getScratchpad():ee;size_t limit=spr?16384:PS2_RAM_SIZE;
        if(spr)physical=address&16383;require(physical<=limit&&bytes.size()<=limit-physical,"initial/event memory range outside fixture space");
        std::memcpy(base+physical,bytes.data(),bytes.size());
    };
    for(const auto &b:fixture.at("initial"))store(b.at("address"),unhex(b.at("hex")));
    if(sif){ctx.r[4]=_mm_set_epi64x(0,0x80000001u);ctx.r[5]=_mm_set_epi64x(0,0x21000u);ps2_stubs::sceSifSetReg(ee,&ctx,runtime.get());}
    std::vector<uint32_t> causes;int32_t transferId=0,completion=0;
    auto snapshot=[&](int event){
        memory.processVIF1Data(nullptr,0);
        Json j={{"event",event},{"ram",hex64(hashBytes(0xcbf29ce484222325ull,ee,PS2_RAM_SIZE))},
          {"spr",hex64(hashBytes(0xcbf29ce484222325ull,memory.getScratchpad(),16384))},
          {"vram",hex64(hashBytes(0xcbf29ce484222325ull,memory.getGSVRAM(),PS2_GS_VRAM_SIZE))},
          {"vu_data",hex64(hashBytes(0xcbf29ce484222325ull,memory.getVU1Data(),PS2_VU1_DATA_SIZE))},
          {"vif_register_hash",hex64(hashBytes(0xcbf29ce484222325ull,&observed.regs,sizeof(observed.regs)))},
          {"vif_stat",observed.regs.stat},{"vif_code",observed.regs.code},{"image_qwc",observed.image},{"direct_remaining",observed.remaining},{"assembled",observed.assembled},
          {"packets",packets},{"packet_hash",hex64(packetHash)},{"dstat",memory.readIORegister(0x1000e010u)},
          {"vif_chcr",memory.readIORegister(0x10009000u)},{"vif_qwc",memory.readIORegister(0x10009020u)},
          {"vif_tadr",memory.readIORegister(0x10009030u)},{"gif_chcr",memory.readIORegister(0x1000a000u)},
          {"dma_starts",memory.dmaStartCount()},{"pending_interrupt",memory.hasPendingInterruptWork()},{"causes",causes},
          {"spr_roundtrip",std::vector<uint8_t>(ee+0x41000u,ee+0x41020u)},
          {"spr_to_sadr",memory.readIORegister(0x1000d480u)},{"spr_from_sadr",memory.readIORegister(0x1000d080u)},
          {"spr_to_qwc",memory.readIORegister(0x1000d420u)},{"spr_from_qwc",memory.readIORegister(0x1000d020u)}};
        if(sif){require(runtime->readIopMemory(0u,iop.data(),iop.size()),"IOP snapshot unavailable");
            std::vector<uint32_t> reply(16),receive(4);std::memcpy(reply.data(),ee+0x22000u,64);std::memcpy(receive.data(),ee+0x330600u,16);
            j["iop_ram"]=hex64(hashBytes(0xcbf29ce484222325ull,iop.data(),iop.size()));j["reply"]=reply;j["receive"]=receive;
            j["transfer_id"]=transferId;j["completion"]=completion;j["return_register"]=getRegU32(&ctx,2);j["pc"]=ctx.pc;
        }
        std::cout<<j.dump()<<'\n';return j;
    };
    snapshot(-1);size_t index=0;
    for(const auto &event:fixture.at("events")){
        require(event.at("seq")==index,"event ordering differs");const auto op=event.at("op").get<std::string>();causes.clear();
        if(op=="write")store(event.at("address"),unhex(event.at("hex")));
        else if(op=="mmio")require(memory.writeIORegister(event.at("address"),event.at("value")),"unsupported MMIO event");
        else if(op=="drain")memory.processPendingTransfers();
        else if(op=="irq")causes=memory.consumeCompletedDmacCauses();
        else if(op=="sif"){
            require(sif,"SIF operation in DMA fixture");uint32_t desc[4]={event.at("src"),event.at("dst"),event.at("bytes"),event.at("attr")};
            std::memcpy(ee+0x20000u,desc,16);ctx.r[4]=_mm_set_epi64x(0,0x20000u);ctx.r[5]=_mm_set_epi64x(0,1);
            ps2_stubs::sceSifSetDma(ee,&ctx,runtime.get());transferId=static_cast<int32_t>(getRegU32(&ctx,2));require(transferId>0,"SIF transfer rejected");
            ctx.r[4]=_mm_set_epi64x(0,transferId);ps2_stubs::sceSifDmaStat(ee,&ctx,runtime.get());completion=static_cast<int32_t>(getRegU32(&ctx,2));
        }else throw std::runtime_error("unsupported replay operation");
        auto j=snapshot(static_cast<int>(index++));
        for(auto it=event.at("expect").begin();it!=event.at("expect").end();++it)require(j.at(it.key())==it.value(),("independent event expectation: "+it.key()).c_str());
    }
    require(index>0,"empty replay events");return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}

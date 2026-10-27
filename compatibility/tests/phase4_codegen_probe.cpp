// Test-only access to the real emitter, without changing its production API.
#include <cstdint>
#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <unordered_set>
#include <iostream>
#include "ps2recomp/control_flow_analyzer.h"
#define private public
#include "ps2recomp/code_generator.h"
#undef private
#include "ps2recomp/r5900_decoder.h"
#include "ps2recomp/elf_parser.h"
int main(int argc,char **argv){
    if(argc==3&&std::string(argv[1])=="elf"){
        ps2recomp::ElfParser parser(argv[2]);bool ok=parser.parse();
        std::cout<<"parsed="<<ok<<" symbols="<<parser.extractSymbols().size()<<'\n';return ok?0:2;
    }
    std::vector<ps2recomp::Symbol> symbols;std::vector<ps2recomp::Section> sections;
    ps2recomp::CodeGenerator emitter(symbols,sections);ps2recomp::R5900Decoder decoder;
    const uint32_t rs=1u<<21,rt=2u<<16,rd=3u<<11;
    const std::pair<const char *,uint32_t> cases[]={
        {"add",rs|rt|rd|0x20},{"sub",rs|rt|rd|0x22},
        {"dadd",rs|rt|rd|0x2c},{"dsub",rs|rt|rd|0x2e},
        {"addi",(8u<<26)|rs|rt|1},{"daddi",(24u<<26)|rs|rt|1},
        {"daddiu",(25u<<26)|rs|rt|1}};
    for(auto c:cases){auto ins=decoder.decodeInstruction(0x100000,c.second,false);
        std::cout<<c.first<<'\t'<<emitter.translateInstruction(ins)<<'\n';}
}

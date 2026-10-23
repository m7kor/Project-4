#include "ps2recomp/code_generator.h"
#include "ps2recomp/r5900_decoder.h"
#include <toml.hpp>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <regex>
#include <stdexcept>

// Re-emit one explicitly reviewed ordinary EE body; never discovers code in RAM.
int main(int argc,char** argv) {
    if(argc!=3){std::cerr<<"Usage: ps2_ee_body_codegen reviewed-plan.toml output.cpp\n";return 2;}
    try {
        const auto plan=toml::parse(argv[1]);
        if(toml::find<int64_t>(plan,"schema")!=1)throw std::invalid_argument("Unsupported schema");
        const auto imagePath=std::filesystem::absolute(argv[1]).parent_path()/toml::find<std::string>(plan,"image");
        const auto outputPath=std::filesystem::absolute(argv[2]).lexically_normal();
        if(outputPath==std::filesystem::absolute(argv[1]).lexically_normal() || outputPath==imagePath.lexically_normal())
            throw std::invalid_argument("Output cannot replace input");
        std::error_code error;
        if(std::filesystem::equivalent(outputPath,imagePath,error))throw std::invalid_argument("Output aliases image");
        error.clear();
        if(std::filesystem::equivalent(outputPath,argv[1],error))throw std::invalid_argument("Output aliases plan");
        if(std::filesystem::file_size(imagePath)>32u*1024u*1024u)throw std::invalid_argument("Image exceeds EE RAM");
        std::ifstream file(imagePath,std::ios::binary);
        if(!file)throw std::runtime_error("Cannot read image");
        std::vector<uint8_t> image(std::istreambuf_iterator<char>(file),{});
        if(image.size()!=std::filesystem::file_size(imagePath))throw std::runtime_error("Incomplete image read");
        const int64_t start=toml::find<int64_t>(plan,"start"),end=toml::find<int64_t>(plan,"end");
        const auto name=toml::find<std::string>(plan,"name");
        if(start<0 || end<=start || end>int64_t(image.size()) || (start&3) || (end&3)
            || !std::regex_match(name,std::regex("[A-Za-z_][A-Za-z0-9_]*")))
            throw std::invalid_argument("Invalid reviewed body");
        ps2recomp::R5900Decoder decoder;
        std::vector<ps2recomp::Instruction> instructions;
        for(uint32_t at=uint32_t(start);at<uint32_t(end);at+=4){
            uint32_t word=uint32_t(image[at])|uint32_t(image[at+1])<<8|uint32_t(image[at+2])<<16|uint32_t(image[at+3])<<24;
            instructions.push_back(decoder.decodeInstruction(at,word,false));
        }
        if(instructions.back().hasDelaySlot)throw std::invalid_argument("Missing final delay slot");
        ps2recomp::CodeGenerator generator({},{});
        generator.setRenamedFunctions({{uint32_t(start),name}});
        std::vector<uint32_t> entries;
        for(int64_t entry:toml::find_or<std::vector<int64_t>>(plan,"entries",{})){
            if(entry<start || entry>=end || (entry&3))throw std::invalid_argument("Resume outside body");
            if(std::find(entries.begin(),entries.end(),uint32_t(entry))!=entries.end())throw std::invalid_argument("Duplicate resume entry");
            entries.push_back(uint32_t(entry));
        }
        generator.setResumeEntryTargets({{uint32_t(start),entries}});
        ps2recomp::Function function{};function.name=name;function.start=uint32_t(start);function.end=uint32_t(end);
        auto source=generator.generateFunction(function,instructions,false);
        std::ofstream output(outputPath,std::ios::binary);
        output<<"#include <stdexcept>\n#include \"ps2_runtime_macros.h\"\n#include \"ps2_runtime.h\"\n#include \"runtime/ps2_vu_control.h\"\n#include <ps2_recompiled_stubs.h>\n#include \"ps2_syscalls.h\"\n#include \"ps2_stubs.h\"\n#ifdef PS2_FUNCTION_LOG_TRACKER\n#include \"ps2_log.h\"\n#endif\n"<<source;
        if(!output)throw std::runtime_error("Cannot write source");
        std::cout<<"Re-emitted reviewed EE body: "<<name<<" instructions="<<instructions.size()<<'\n';
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}

#include "ps2recomp/native_module_codegen.h"
#include <toml.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>

int main(int argc, char** argv)
{
    if (argc != 3) { std::cerr << "Usage: ps2_native_module_codegen plan.toml output.cpp\n"; return 2; }
    try {
        const auto config = toml::parse(argv[1]);
        if (toml::find<int64_t>(config, "schema") != 1) throw std::invalid_argument("Unsupported plan schema");
        ps2recomp::NativeModuleCodegenInput input;
        input.identifier = toml::find<std::string>(config, "identifier");
        input.identity = toml::find<std::string>(config, "identity");
        const auto imagePath = std::filesystem::absolute(std::filesystem::path(argv[1])).parent_path()
            / toml::find<std::string>(config, "image");
        std::error_code imageError, planError;
        const bool replacesImage = std::filesystem::equivalent(argv[2], imagePath, imageError);
        const bool replacesPlan = std::filesystem::equivalent(argv[2], argv[1], planError);
        if (replacesImage || replacesPlan
            || std::filesystem::absolute(argv[2]).lexically_normal() == imagePath.lexically_normal()
            || std::filesystem::absolute(argv[2]).lexically_normal() == std::filesystem::absolute(argv[1]).lexically_normal())
            throw std::invalid_argument("Output cannot replace original image or plan");
        const auto bytes = std::filesystem::file_size(imagePath);
        if (bytes > 32u*1024u*1024u) throw std::invalid_argument("Module image too large");
        std::ifstream image(imagePath, std::ios::binary);
        if (!image) throw std::runtime_error("Cannot read module image");
        input.image.assign(std::istreambuf_iterator<char>(image), {});
        if (input.image.size() != bytes) throw std::runtime_error("Incomplete module image read");
        auto checked32 = [](int64_t value) {
            if (value < 0 || uint64_t(value) > UINT32_MAX) throw std::invalid_argument("Plan integer outside uint32");
            return uint32_t(value);
        };
        for (const auto& body : toml::find(config, "bodies").as_array()) {
            ps2recomp::NativeModuleBody item;
            item.start = checked32(toml::find<int64_t>(body, "start"));
            item.end = checked32(toml::find<int64_t>(body, "end"));
            for (auto value : toml::find_or<std::vector<int64_t>>(body, "entries", {})) item.entries.push_back(checked32(value));
            input.bodies.push_back(std::move(item));
        }
        for (const auto& reloc : toml::find(config, "instruction_relocations").as_array()) {
            const auto offset = checked32(toml::find<int64_t>(reloc, "offset"));
            const auto type = checked32(toml::find<int64_t>(reloc, "type"));
            if (!input.instructionRelocations.emplace(offset, type).second)
                throw std::invalid_argument("Duplicate instruction relocation");
        }
        const auto source = ps2recomp::generateNativeModule(input);
        std::ofstream output(argv[2], std::ios::binary);
        if (!output || !(output << source)) throw std::runtime_error("Cannot write generated source");
        std::cout << "Generated native module: " << input.bodies.size() << " bodies, "
                  << input.instructionRelocations.size() << " relocated instructions\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}

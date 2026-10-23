#pragma once
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace ps2recomp {
struct NativeModuleBody {
    uint32_t start = 0;
    uint32_t end = 0;
    std::vector<uint32_t> entries;
};
struct NativeModuleCodegenInput {
    std::string identifier;
    std::string identity;
    std::vector<uint8_t> image;
    std::vector<NativeModuleBody> bodies;
    std::unordered_map<uint32_t, uint32_t> instructionRelocations;
};
// Explicit, reviewed code ranges only. This does not infer code from symbol
// type, resolve imports, relocate the image or attach it to a running game.
std::string generateNativeModule(const NativeModuleCodegenInput& input);
}

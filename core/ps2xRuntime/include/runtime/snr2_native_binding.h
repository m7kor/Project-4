#pragma once
#include "runtime/native_module_registry.h"
#include <array>
#include <vector>
class PS2Runtime;
namespace ps2x {
struct Snr2NativeBinding {
    uint32_t loadSource = 0, loadSourceWord = 0;
    uint32_t unloadSource = 0, unloadSourceWord = 0, unloadTarget = 0;
    unsigned loadBaseRegister = 18, unloadBaseRegister = 4;
    std::array<uint32_t, 15> originalHeader{};
    std::string imageName;
    NativeModuleDescriptor descriptor;
};
// One catalogue per original loader call-site pair. Install after main ELF
// load, before EE execution. Original guest relocation/import work is retained.
void installSnr2NativeBindings(PS2Runtime&, std::vector<Snr2NativeBinding>);
}

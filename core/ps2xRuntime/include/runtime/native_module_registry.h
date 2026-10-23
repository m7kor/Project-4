#pragma once
#include <cstdint>
#include <map>
#include <memory>
#include <span>
#include <string>
#include <unordered_map>
#include <vector>

struct R5900Context;
class PS2Runtime;

namespace ps2x {
using NativeModuleFunction = void (*)(uint8_t*, R5900Context*, PS2Runtime*, uint32_t);
struct NativeModuleCodeWord {
    uint32_t offset = 0;
    uint32_t original = 0;
    uint32_t variableBits = 0;
};
struct NativeModuleEntry {
    uint32_t offset = 0;
    uint32_t ownerStart = 0;
    uint32_t ownerEnd = 0;
    NativeModuleFunction function = nullptr;
};
struct NativeModuleDescriptor {
    std::string identity;
    uint32_t imageSize = 0;
    std::vector<NativeModuleCodeWord> codeWords;
    std::vector<NativeModuleEntry> entries;
    // Compact identity for complete modules, used when codeWords is empty:
    // FNV-1a 64 over every word of [textStart, textEnd) with relocated operand
    // bits cleared. relocatedWords lists those words as (offset >> 2) with bit
    // 31 set for a 26-bit jump field and bit 30 for a 16-bit immediate.
    uint32_t textStart = 0;
    uint32_t textEnd = 0;
    uint64_t maskedTextHash = 0;
    std::vector<uint32_t> relocatedWords;
};

// FNV-1a 64 over text words with relocated bits masked (see above).
uint64_t nativeModuleMaskedTextHash(const uint8_t* image, uint32_t textStart, uint32_t textEnd,
                                    const std::vector<uint32_t>& relocatedWords, bool* valid = nullptr);

// Confined to the EE execution thread. Binding verifies every instruction of
// each declared native body. Only explicit relocated operand bits may differ.
// Data/import readiness and full original-file identity belong to the loader.
class NativeModuleRegistry {
    struct Instance {
        bool active = true;
        uint32_t base = 0;
        const uint8_t* ram = nullptr;
        std::shared_ptr<const NativeModuleDescriptor> descriptor;
    };
public:
    class Handle {
        friend class NativeModuleRegistry;
        std::weak_ptr<Instance> instance;
        NativeModuleFunction function = nullptr;
        uint32_t address = 0;
    public:
        bool valid() const;
        bool invoke(uint8_t* ram, R5900Context* ctx, PS2Runtime* runtime) const;
    };
    NativeModuleRegistry() = default;
    ~NativeModuleRegistry() { clear(); }
    NativeModuleRegistry(const NativeModuleRegistry&) = delete;
    NativeModuleRegistry& operator=(const NativeModuleRegistry&) = delete;
    bool bind(uint32_t base, const NativeModuleDescriptor& descriptor,
              std::span<const uint8_t> ram, std::string* reason = nullptr);
    bool unbind(uint32_t base);
    void clear();
    Handle lookup(uint32_t address) const;
    // A membership query does not create/lock a lifetime handle. Unbinding
    // removes all entries before the EE thread can dispatch another call.
    bool hasFunction(uint32_t address) const;
    bool containsAddress(uint32_t address) const;
    size_t moduleCount() const { return instances.size(); }
private:
    std::map<uint32_t, std::shared_ptr<Instance>> instances;
    std::unordered_map<uint32_t, Handle> functions;
};
}

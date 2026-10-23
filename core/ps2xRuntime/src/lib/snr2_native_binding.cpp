#include "runtime/snr2_native_binding.h"
#include "ps2_runtime.h"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <set>

namespace ps2x {
namespace {
uint32_t word(const uint8_t* bytes) {
    return uint32_t(bytes[0]) | uint32_t(bytes[1]) << 8 | uint32_t(bytes[2]) << 16 | uint32_t(bytes[3]) << 24;
}
bool pointerField(unsigned i) {
    return i == 1 || i == 3 || i == 5 || i == 6 || i == 7 || i == 8 || i == 13 || i == 14;
}
bool rejected(const char* reason, uint32_t base) {
    std::cerr << "[native-module:binding-rejected] base=0x" << std::hex << base
              << std::dec << " reason=" << reason << '\n';
    return false;
}
void reportUntranslated(const uint8_t* bytes, size_t ramSize, uint32_t base, uint32_t target)
{
    // Caller has checked the complete header span. Unknown modules remain
    // ordinary missing targets; this bounded observation never binds or skips code.
    const uint32_t imageSize = word(bytes + base + 44);
    const uint32_t nameAt = word(bytes + base + 20);
    std::string name = "<unreadable>";
    if (word(bytes + base) == 0x32524E53u && imageSize >= 60u &&
        imageSize <= ramSize - base && nameAt >= uint64_t(base) + 60u &&
        uint64_t(nameAt) < uint64_t(base) + imageSize)
    {
        const auto limit = std::min<uint64_t>(512u, uint64_t(base) + imageSize - nameAt);
        std::string candidate;
        for (uint64_t i = 0; i < limit; ++i)
        {
            const uint8_t c = bytes[nameAt + i];
            if (c == 0u)
            {
                if (!candidate.empty()) name = std::move(candidate);
                break;
            }
            if (c < 32u || c > 126u) break;
            candidate.push_back(static_cast<char>(c));
        }
    }
    std::cout << "[native-module:untranslated] name=" << name << " base=0x" << std::hex << base
              << " target=0x" << target << " size=0x" << imageSize << " header=";
    for (unsigned i = 0; i < 15u; ++i)
        std::cout << (i ? "," : "") << word(bytes + base + i * 4u);
    std::cout << std::dec << '\n';
}
}
void installSnr2NativeBindings(PS2Runtime& runtime, std::vector<Snr2NativeBinding> bindings)
{
    if (bindings.empty()) throw std::invalid_argument("Empty native SNR2 catalogue");
    const auto& common = bindings.front();
    std::set<std::string> names;
    auto* ram = runtime.memory().getRDRAM();
    const auto ramSize = runtime.memory().rdramSize();
    if (!ram || ramSize < 60 || common.loadSource > ramSize - 4 || common.unloadSource > ramSize - 4
        || (common.loadSource & 3u) || (common.unloadSource & 3u) || common.loadSource == common.unloadSource
        || word(ram + common.loadSource) != common.loadSourceWord
        || word(ram + common.unloadSource) != common.unloadSourceWord)
        throw std::invalid_argument("SNR2 loader call sites do not match main ELF");
    for (const auto& item : bindings) {
        if (item.loadSource != common.loadSource || item.unloadSource != common.unloadSource
            || item.loadSourceWord != common.loadSourceWord || item.unloadSourceWord != common.unloadSourceWord
            || item.unloadTarget != common.unloadTarget || item.loadBaseRegister != common.loadBaseRegister
            || item.unloadBaseRegister != common.unloadBaseRegister || item.loadBaseRegister >= 32
            || item.unloadBaseRegister >= 32 || item.originalHeader[0] != 0x32524E53
            || item.descriptor.imageSize != item.originalHeader[11] || item.descriptor.imageSize < 60
            || item.imageName.empty() || item.imageName.find('\0') != std::string::npos
            || item.originalHeader[5] >= item.descriptor.imageSize
            || item.imageName.size()+1 > item.descriptor.imageSize - item.originalHeader[5]
            || !names.insert(item.imageName + '\n' + item.descriptor.identity).second)
            throw std::invalid_argument("Invalid SNR2 native loader catalogue");
        for (unsigned i = 0; i < 15; ++i)
            if (pointerField(i) && item.originalHeader[i] > item.descriptor.imageSize)
                throw std::invalid_argument("SNR2 pointer lies outside original image");
        for (unsigned field : {6u, 7u}) {
            const auto entry = item.originalHeader[field];
            if (!entry || std::none_of(item.descriptor.entries.begin(), item.descriptor.entries.end(),
                    [&](const auto& native) { return native.offset == entry; }))
                throw std::invalid_argument("Catalogue requires compiled constructor and destructor entries");
        }
    }
    const auto owned = std::make_shared<const std::vector<Snr2NativeBinding>>(std::move(bindings));
    runtime.setGuestBranchObserver(owned->front().loadSource,
        [owned](uint8_t* bytes, R5900Context* ctx, PS2Runtime* owner, uint32_t source, uint32_t target,
                PS2Runtime::GuestBranchKind kind) {
        const auto& config = owned->front();
        if (kind != PS2Runtime::GuestBranchKind::IndirectCall) return true;
        const auto base = uint32_t(_mm_cvtsi128_si32(ctx->r[config.loadBaseRegister]));
        // Any new original constructor call supersedes a previous instance
        // at this allocation, including an unsupported replacement module.
        owner->unbindNativeModule(base);
        const auto size = owner->memory().rdramSize();
        if (!bytes || bytes != owner->memory().getRDRAM() || size < 60 || (base & 3u) || base > size - 60
            || source > size - 4 || word(bytes + source) != config.loadSourceWord)
            return rejected("invalid loader RAM/base/call site", base);
        const uint32_t nameAt = word(bytes + base + 20);
        // Several images can share a file name (RE4 ships enemy variants under
        // one name); the first whose header and code both verify is bound.
        std::string lastReason;
        for (const auto& item : *owned) {
            const uint64_t imageEnd = uint64_t(base) + item.descriptor.imageSize;
            const uint64_t expectedName = uint64_t(base) + item.originalHeader[5];
            if (imageEnd > size || expectedName != nameAt || uint64_t(target) != uint64_t(base) + item.originalHeader[6]) continue;
            if (!std::equal(item.imageName.begin(), item.imageName.end(), bytes + nameAt)
                || bytes[nameAt + item.imageName.size()] != 0) continue;
            bool headerOk = true;
            for (unsigned i = 0; i < 15 && headerOk; ++i) {
                // +0x30 is the original loader's mutable module linked-list
                // pointer, not an immutable input-file identity field.
                if (i == 12) continue;
                const auto original = item.originalHeader[i];
                const uint64_t expected = pointerField(i) && original ? uint64_t(base) + original : original;
                if (expected > UINT32_MAX || word(bytes + base + i*4) != expected)
                    headerOk = false;
            }
            if (!headerOk) { lastReason = "relocated SNR2 header mismatch"; continue; }
            std::string reason;
            if (!owner->bindNativeModule(base, item.descriptor, &reason)) { lastReason = reason; continue; }
            std::cout << "[native-module:loaded] name=" << item.imageName << " base=0x" << std::hex << base << std::dec << '\n';
            return true;
        }
        if (!lastReason.empty())
            return rejected(lastReason.c_str(), base);
        // Unsupported modules still take ordinary dispatch and produce the
        // existing missing-target evidence; never skip their constructors.
        reportUntranslated(bytes, size, base, target);
        return true;
    });
    runtime.setGuestBranchObserver(owned->front().unloadSource,
        [owned](uint8_t* bytes, R5900Context* ctx, PS2Runtime* owner, uint32_t source, uint32_t target,
                PS2Runtime::GuestBranchKind kind) {
        const auto& config = owned->front();
        if (kind != PS2Runtime::GuestBranchKind::DirectCall || target != config.unloadTarget) return true;
        const auto size = owner->memory().rdramSize();
        const auto base = uint32_t(_mm_cvtsi128_si32(ctx->r[config.unloadBaseRegister]));
        if (!bytes || bytes != owner->memory().getRDRAM() || size < 4 || source > size - 4
            || word(bytes + source) != config.unloadSourceWord)
            return rejected("unload call site mismatch", base);
        if (owner->unbindNativeModule(base))
            std::cout << "[native-module:unloaded] base=0x" << std::hex << base << std::dec << '\n';
        return true;
    });
}
}

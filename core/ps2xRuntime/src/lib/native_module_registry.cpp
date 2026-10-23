#include "runtime/native_module_registry.h"
#include "ps2_runtime.h"
#include <unordered_set>

namespace ps2x {
bool NativeModuleRegistry::containsAddress(uint32_t address) const
{
    auto it = instances.upper_bound(address);
    if (it == instances.begin()) return false;
    --it;
    return uint64_t(address) < uint64_t(it->first) + it->second->descriptor->imageSize;
}
namespace {
bool allowedVariableBits(uint32_t word, uint32_t bits)
{
    if (!bits) return true;
    const uint32_t opcode = word >> 26;
    if (bits == 0x03FFFFFFu) return opcode == 2 || opcode == 3;
    if (bits != 0xFFFFu) return false;
    return (opcode >= 8 && opcode <= 15) || (opcode >= 24 && opcode <= 27) ||
           (opcode >= 30 && opcode <= 46) || opcode == 48 || opcode == 49 ||
           opcode == 54 || opcode == 55 || opcode == 56 || opcode == 57 ||
           opcode == 62 || opcode == 63;
}
uint32_t readWord(const uint8_t* bytes)
{
    return uint32_t(bytes[0]) | (uint32_t(bytes[1]) << 8) |
           (uint32_t(bytes[2]) << 16) | (uint32_t(bytes[3]) << 24);
}
}
uint64_t nativeModuleMaskedTextHash(const uint8_t* image, uint32_t textStart, uint32_t textEnd,
                                    const std::vector<uint32_t>& relocatedWords, bool* valid)
{
    // relocatedWords is sorted by offset; walk it alongside the text.
    uint64_t hash = 0xCBF29CE484222325ull;
    size_t next = 0;
    bool ok = (textStart & 3u) == 0u && (textEnd & 3u) == 0u && textStart < textEnd;
    for (uint32_t at = textStart; ok && at < textEnd; at += 4)
    {
        uint32_t w = readWord(image + at);
        while (next < relocatedWords.size() && ((relocatedWords[next] & 0x3FFFFFFFu) << 2) < at)
        {
            ok = false; // relocation outside text or unsorted
            ++next;
        }
        if (next < relocatedWords.size() && ((relocatedWords[next] & 0x3FFFFFFFu) << 2) == at)
        {
            const uint32_t bits = (relocatedWords[next] & 0x80000000u) ? 0x03FFFFFFu : 0xFFFFu;
            if (!allowedVariableBits(w, bits))
                ok = false;
            w &= ~bits;
            ++next;
        }
        for (int i = 0; i < 4; ++i)
        {
            hash ^= (w >> (8 * i)) & 0xFFu;
            hash *= 0x100000001B3ull;
        }
    }
    if (next != relocatedWords.size())
        ok = false;
    if (valid)
        *valid = ok;
    return hash;
}

bool NativeModuleRegistry::Handle::valid() const
{
    const auto loaded = instance.lock();
    return loaded && loaded->active && function;
}
bool NativeModuleRegistry::Handle::invoke(uint8_t* ram, R5900Context* ctx, PS2Runtime* runtime) const
{
    const auto loaded = instance.lock();
    if (!loaded || !loaded->active || !function || !ram || !ctx ||
        ram != loaded->ram || ctx->pc != address) return false;
    // A body may remove its own module; keep the descriptor alive while it
    // executes, then reject further continuation through that old binding.
    function(ram, ctx, runtime, loaded->base);
    return loaded->active;
}
bool NativeModuleRegistry::bind(uint32_t base, const NativeModuleDescriptor& descriptor,
                                std::span<const uint8_t> ram, std::string* reason)
{
    auto reject = [&](const char* message) { if (reason) *reason = message; return false; };
    const uint64_t end = uint64_t(base) + descriptor.imageSize;
    if ((base & 3u) || !descriptor.imageSize || end > ram.size() || end > 0xFFFFFFFFull)
        return reject("Module image is outside RAM or unaligned");
    const bool compact = descriptor.codeWords.empty();
    if (descriptor.identity.empty() || descriptor.entries.empty() ||
        (compact && (descriptor.textEnd <= descriptor.textStart || descriptor.textEnd > descriptor.imageSize)))
        return reject("Module descriptor lacks identity, code or entry points");
    for (const auto& [otherBase, other] : instances)
        if (base < uint64_t(otherBase) + other->descriptor->imageSize && otherBase < end)
            return reject("Module load ranges overlap");
    std::unordered_map<uint32_t, uint32_t> words;
    for (const auto& word : descriptor.codeWords) {
        if ((word.offset & 3u) || uint64_t(word.offset) + 4 > descriptor.imageSize ||
            !allowedVariableBits(word.original, word.variableBits) ||
            !words.emplace(word.offset, word.original).second)
            return reject("Invalid or duplicate native code identity word");
        const uint32_t observed = readWord(ram.data() + base + word.offset);
        if ((observed & ~word.variableBits) != (word.original & ~word.variableBits))
            return reject("Loaded code differs from the compiled instruction body");
    }
    if (compact)
    {
        bool valid = false;
        const uint64_t observed = nativeModuleMaskedTextHash(ram.data() + base, descriptor.textStart,
                                                             descriptor.textEnd, descriptor.relocatedWords, &valid);
        if (!valid)
            return reject("Invalid compact native text identity");
        if (observed != descriptor.maskedTextHash)
            return reject("Loaded code differs from the compiled module text");
    }
    std::unordered_set<uint32_t> offsets;
    std::map<uint32_t, std::pair<uint32_t, NativeModuleFunction>> owners;
    for (const auto& entry : descriptor.entries) {
        if (!entry.function || (entry.offset & 3u) || (entry.ownerStart & 3u) || (entry.ownerEnd & 3u) ||
            entry.ownerEnd <= entry.ownerStart || entry.ownerEnd > descriptor.imageSize ||
            entry.offset < entry.ownerStart || entry.offset >= entry.ownerEnd ||
            !offsets.insert(entry.offset).second)
            return reject("Invalid or duplicate native entry point");
        if (compact)
        {
            if (entry.ownerStart < descriptor.textStart || entry.ownerEnd > descriptor.textEnd)
                return reject("Native body lies outside the verified text");
        }
        else
        {
            for (uint32_t at = entry.ownerStart; at < entry.ownerEnd; at += 4)
                if (!words.contains(at)) return reject("Native body has unchecked instruction bytes");
        }
        const auto [owner, inserted] = owners.emplace(entry.ownerStart, std::make_pair(entry.ownerEnd, entry.function));
        if (!inserted && owner->second != std::make_pair(entry.ownerEnd, entry.function))
            return reject("Native resume entries disagree about their owner");
    }
    uint32_t previousEnd = 0;
    for (const auto& [start, owner] : owners) {
        if (start < previousEnd) return reject("Native body ranges overlap");
        previousEnd = owner.first;
    }
    // Stage copies first: validation/allocation failure cannot partially bind.
    auto stagedInstances = instances;
    auto stagedFunctions = functions;
    auto loaded = std::make_shared<Instance>();
    loaded->base = base;
    loaded->ram = ram.data();
    loaded->descriptor = std::make_shared<const NativeModuleDescriptor>(descriptor);
    stagedInstances.emplace(base, loaded);
    for (const auto& entry : descriptor.entries) {
        Handle handle;
        handle.instance = loaded;
        handle.function = entry.function;
        handle.address = base + entry.offset;
        stagedFunctions.emplace(base + entry.offset, handle);
    }
    instances.swap(stagedInstances);
    functions.swap(stagedFunctions);
    if (reason) reason->clear();
    return true;
}
bool NativeModuleRegistry::unbind(uint32_t base)
{
    const auto it = instances.find(base);
    if (it == instances.end()) return false;
    it->second->active = false;
    for (const auto& entry : it->second->descriptor->entries) functions.erase(base + entry.offset);
    instances.erase(it);
    return true;
}
void NativeModuleRegistry::clear()
{
    for (auto& [base, loaded] : instances) loaded->active = false;
    functions.clear();
    instances.clear();
}
NativeModuleRegistry::Handle NativeModuleRegistry::lookup(uint32_t address) const
{
    const auto it = functions.find(address);
    return it == functions.end() ? Handle{} : it->second;
}
bool NativeModuleRegistry::hasFunction(uint32_t address) const
{
    return functions.contains(address);
}
}

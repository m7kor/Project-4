#include "MiniTest.h"
#include "ps2_runtime.h"
#include "runtime/native_module_registry.h"
#include "runtime/snr2_native_binding.h"
#include <cstring>
#include <vector>
#include <sstream>
#include <iostream>

void native_relative_indirect_flow_probe(uint8_t*, R5900Context*, PS2Runtime*, uint32_t);
void reset_ps2_test_function_table();

namespace {
ps2x::NativeModuleRegistry* activeRegistry = nullptr;
unsigned enteredCallee = 0;
void nativeRuntimeProbe(uint8_t* ram, R5900Context* ctx, PS2Runtime* runtime, uint32_t base)
{
    if (ctx->pc == base + 0x24) ++enteredCallee;
    native_relative_indirect_flow_probe(ram, ctx, runtime, base);
}
void simpleBody(uint8_t*, R5900Context* ctx, PS2Runtime*, uint32_t base) { ctx->pc = base + 8; }
void staticBody(uint8_t*, R5900Context* ctx, PS2Runtime*) { ctx->pc += 4; }
void snrReturn(uint8_t*, R5900Context* ctx, PS2Runtime*, uint32_t)
{
    ctx->pc = uint32_t(_mm_cvtsi128_si32(ctx->r[31]));
}
ps2x::Snr2NativeBinding snrFixture(PS2Runtime& runtime, uint32_t base)
{
    ps2x::Snr2NativeBinding profile;
    profile.loadSource = 0x2000; profile.loadSourceWord = 0x0040F809;
    profile.unloadSource = 0x2008; profile.unloadSourceWord = 0x0C000C00;
    profile.unloadTarget = 0x3000;
    profile.originalHeader = {0x32524E53, 0, 0, 0, 0, 80, 60, 64, 0, 0, 128, 128, 0, 0, 0};
    profile.imageName = "fixture.elf";
    profile.descriptor = {"synthetic-snr2", 128, {{60, 0x03E00008, 0}, {64, 0, 0}},
        {{60, 60, 68, snrReturn}, {64, 60, 68, snrReturn}}};
    auto* ram = runtime.memory().getRDRAM();
    std::memcpy(ram + profile.loadSource, &profile.loadSourceWord, 4);
    std::memcpy(ram + profile.unloadSource, &profile.unloadSourceWord, 4);
    auto loaded = profile.originalHeader;
    for (unsigned i : {5u, 6u, 7u}) loaded[i] += base;
    loaded[12] = 0x76543210; // Original loader may insert the module into its list.
    std::memcpy(ram + base, loaded.data(), 60);
    std::memcpy(ram + base + 80, profile.imageName.c_str(), profile.imageName.size()+1);
    for (const auto& code : profile.descriptor.codeWords)
        std::memcpy(ram + base + code.offset, &code.original, 4);
    return profile;
}
void runtimeRemovingBody(uint8_t*, R5900Context* ctx, PS2Runtime* runtime, uint32_t base)
{
    runtime->unbindNativeModule(base);
    ctx->pc = base + 8;
}
void selfRemovingBody(uint8_t*, R5900Context* ctx, PS2Runtime*, uint32_t base)
{
    if (activeRegistry) activeRegistry->unbind(base);
    ctx->pc = base + 8;
}
ps2x::NativeModuleDescriptor simpleDescriptor()
{
    return {"synthetic-native-image", 16, {{0, 0x3C080004, 0xFFFF}, {4, 0x2508AF30, 0xFFFF}},
            {{0, 0, 8, simpleBody}, {4, 0, 8, simpleBody}}};
}
void seedSimple(std::vector<uint8_t>& ram, uint32_t base)
{
    const uint32_t words[] = {0x3C080114, 0x25088730};
    std::memcpy(ram.data()+base, words, sizeof(words));
}
}

void registerNativeRelocationRuntimeTests()
{
    MiniTest::Case("NativeRelocationRuntime", [](TestCase& tc) {
        tc.Run("Native presence queries follow bind, unbind and reset", [](TestCase& t) {
            ps2x::NativeModuleRegistry registry;
            std::vector<uint8_t> ram(0x4000);
            auto descriptor = simpleDescriptor();
            seedSimple(ram, 0x1000);
            t.IsFalse(registry.hasFunction(0x1000), "unbound code is absent");
            t.IsTrue(registry.bind(0x1000, descriptor, ram), "validated image binds");
            t.IsTrue(registry.hasFunction(0x1000), "first native entry is present");
            t.IsTrue(registry.hasFunction(0x1004), "resume entry is present");
            t.IsFalse(registry.hasFunction(0x1008), "data in the image is not executable");
            const auto cached = registry.lookup(0x1000);
            t.IsTrue(registry.unbind(0x1000), "image unbinds");
            t.IsFalse(registry.hasFunction(0x1000), "removed first entry is absent");
            t.IsFalse(registry.hasFunction(0x1004), "removed resume entry is absent");
            t.IsFalse(cached.valid(), "existing lifetime handle remains invalidated");
            t.IsTrue(registry.bind(0x1000, descriptor, ram), "same address can bind again");
            t.IsTrue(registry.hasFunction(0x1000), "new instance is visible");
            t.IsFalse(cached.valid(), "rebinding does not revive the old handle");
            registry.clear();
            t.IsFalse(registry.hasFunction(0x1000), "reset removes entries");
        });
        tc.Run("Untranslated SNR2 observation bounds image names and preserves missing targets", [](TestCase& t) {
            for (unsigned variant = 0; variant < 5; ++variant) {
                reset_ps2_test_function_table();
                PS2Runtime runtime;
                t.IsTrue(runtime.memory().initialize(), "RAM initializes");
                const uint32_t base = 0x10000;
                auto profile = snrFixture(runtime, base);
                ps2x::installSnr2NativeBindings(runtime, {profile});
                t.IsTrue(runtime.bindNativeModule(base, profile.descriptor), "old module bound");
                auto* ram = runtime.memory().getRDRAM();
                std::memcpy(ram+base+80, "unknown.elf", 12);
                if (variant == 1) {
                    const uint32_t outside = static_cast<uint32_t>(runtime.memory().rdramSize());
                    std::memcpy(ram+base+20, &outside, 4);
                } else if (variant == 2) ram[base+80] = '\n';
                else if (variant == 3) std::memset(ram+base+80, 'x', 48);
                else if (variant == 4) {
                    const uint32_t oversized = 0xffffffffu;
                    std::memcpy(ram+base+44, &oversized, 4);
                }
                R5900Context ctx{};
                ctx.r[18] = _mm_set_epi64x(0, base);
                ctx.r[31] = _mm_set_epi64x(0, 0x4000);
                std::ostringstream captured;
                struct RestoreBuffer {
                    std::streambuf* previous;
                    ~RestoreBuffer() { std::cout.rdbuf(previous); }
                } restore{std::cout.rdbuf(captured.rdbuf())};
                const bool dispatched = runtime.dispatchGuestBranch(ram, &ctx, base+60,
                    0x2000, 0x4000, PS2Runtime::GuestBranchKind::IndirectCall, "untranslated-fixture");
                std::cout.rdbuf(restore.previous);
                t.IsFalse(dispatched, "unsupported constructor is not silently skipped");
                t.IsFalse(runtime.hasFunction(base+60), "old generation removed");
                const auto log = captured.str();
                const std::string expected = variant == 0 ? "name=unknown.elf" : "name=<unreadable>";
                t.IsTrue(log.find("[native-module:untranslated] " + expected) != std::string::npos,
                         "only bounded printable terminated image names are reported");
                t.IsTrue(log.find("base=0x10000 target=0x1003c") != std::string::npos,
                         "actual load base and target are observed");
                t.IsTrue(log.find("header=32524e53,") != std::string::npos, "actual relocated header recorded");
                t.Equals(static_cast<unsigned>(std::count(log.begin(), log.end(), '\n')), 1u,
                         "malformed names cannot inject additional log lines");
            }
            reset_ps2_test_function_table();
        });
        tc.Run("SNR2 catalogue retains two distinct native modules through one original loader", [](TestCase& t) {
            PS2Runtime runtime;
            t.IsTrue(runtime.memory().initialize(), "owned RAM initializes");
            auto first = snrFixture(runtime, 0x10000);
            auto second = snrFixture(runtime, 0x11000);
            second.imageName = "another.elf";
            second.descriptor.identity = "second-native-image";
            second.originalHeader[6] += 8;
            second.originalHeader[7] += 8;
            auto* ram = runtime.memory().getRDRAM();
            std::memcpy(ram+0x11000+80, second.imageName.c_str(), second.imageName.size()+1);
            for (unsigned field : {6u,7u}) {
                const uint32_t pointer = 0x11000 + second.originalHeader[field];
                std::memcpy(ram+0x11000+field*4, &pointer, 4);
            }
            for (auto& code : second.descriptor.codeWords) {
                code.offset += 8;
                std::memcpy(ram+0x11000+code.offset, &code.original, 4);
            }
            for (auto& entry : second.descriptor.entries) {
                entry.offset += 8; entry.ownerStart += 8; entry.ownerEnd += 8;
            }
            ps2x::installSnr2NativeBindings(runtime, {first,second});
            R5900Context ctx{};
            ctx.r[31] = _mm_set_epi64x(0, 0x4000);
            for (uint32_t base : {0x10000u,0x11000u}) {
                ctx.r[18] = _mm_set_epi64x(0, base);
                const uint32_t offset = base == 0x10000 ? 60 : 68;
                t.IsTrue(runtime.dispatchGuestBranch(ram, &ctx, base+offset, 0x2000, 0x4000,
                    PS2Runtime::GuestBranchKind::IndirectCall, "catalogue-load"), "correct image selected by relocated header and name");
            }
            t.IsTrue(runtime.hasFunction(0x10000+60), "first image remains active after second load");
            t.IsTrue(runtime.hasFunction(0x11000+68), "second image registered through same observer");
            runtime.registerFunction(0x3000, staticBody);
            ctx.r[4] = _mm_set_epi64x(0, 0x10000);
            runtime.dispatchGuestBranch(ram, &ctx, 0x3000, 0x2008, 0x3004,
                PS2Runtime::GuestBranchKind::DirectCall, "catalogue-unlink");
            t.IsFalse(runtime.hasFunction(0x10000+60), "only requested image removed");
            t.IsTrue(runtime.hasFunction(0x11000+68), "unrelated image remains executable");
        });
        tc.Run("SNR2 original loader profile binds reloads and unlinks without skipping guest code", [](TestCase& t) {
            reset_ps2_test_function_table();
            PS2Runtime runtime;
            t.IsTrue(runtime.memory().initialize(), "owned RAM initializes");
            const uint32_t base = 0x10000;
            auto profile = snrFixture(runtime, base);
            ps2x::installSnr2NativeBindings(runtime, {profile});
            runtime.registerFunction(0x3000, staticBody);
            for (unsigned generation = 0; generation < 2; ++generation) {
                R5900Context ctx{};
                ctx.r[18] = _mm_set_epi64x(0, base);
                ctx.r[31] = _mm_set_epi64x(0, 0x4000);
                t.IsTrue(runtime.dispatchGuestBranch(runtime.memory().getRDRAM(), &ctx, base+60,
                    0x2000, 0x4000, PS2Runtime::GuestBranchKind::IndirectCall, "snr-load"),
                    "profile installs original constructor before target lookup");
                t.IsTrue(runtime.hasFunction(base+64), "destructor is registered with constructor");
                ctx.r[4] = _mm_set_epi64x(0, base);
                t.IsTrue(runtime.dispatchGuestBranch(runtime.memory().getRDRAM(), &ctx, 0x3000,
                    0x2008, 0x3004, PS2Runtime::GuestBranchKind::DirectCall, "snr-unlink"),
                    "original unlink target executes after deregistration");
                t.IsFalse(runtime.hasFunction(base+60), "all executable entries removed");
            }
            reset_ps2_test_function_table();
        });
        tc.Run("SNR2 malformed header code RAM and unsupported replacement fail without stale code", [](TestCase& t) {
            for (unsigned variant = 0; variant < 6; ++variant) {
                PS2Runtime runtime;
                t.IsTrue(runtime.memory().initialize(), "owned RAM initializes");
                const uint32_t base = 0x10000;
                auto profile = snrFixture(runtime, base);
                ps2x::installSnr2NativeBindings(runtime, {profile});
                t.IsTrue(runtime.bindNativeModule(base, profile.descriptor), "old generation present");
                auto* ram = runtime.memory().getRDRAM();
                switch (variant) {
                case 0: ram[base+40] ^= 1; break; // Immutable header.
                case 1: ram[base+60] ^= 1; break; // Compiled instruction.
                case 2: ram[base+80] = 'x'; break; // Unknown replacement image.
                case 3: ram[0x2000] ^= 1; break; // Modified original call site.
                case 4: break; // Invalid base.
                case 5: break; // Foreign RAM below.
                }
                R5900Context ctx{};
                ctx.r[18] = _mm_set_epi64x(0, variant == 4 ? 0xFFFFFFFCu : base);
                ctx.r[31] = _mm_set_epi64x(0, 0x4000);
                uint8_t foreign[64]{};
                t.IsFalse(runtime.dispatchGuestBranch(variant == 5 ? foreign : ram, &ctx, base+60,
                    0x2000, 0x4000, PS2Runtime::GuestBranchKind::IndirectCall, "snr-invalid"),
                    "corrupt or unsupported image does not execute old body");
                if (variant != 4) t.IsFalse(runtime.hasFunction(base+60), "old image invalidated before checking replacement");
            }
        });
        tc.Run("SNR2 catalogue rejects invalid call sites pointers and absent lifecycle entries", [](TestCase& t) {
            PS2Runtime runtime;
            t.IsTrue(runtime.memory().initialize(), "owned RAM initializes");
            auto profile = snrFixture(runtime, 0x10000);
            for (unsigned variant = 0; variant < 5; ++variant) {
                auto invalid = profile;
                switch (variant) {
                case 0: invalid.loadSourceWord ^= 1; break;
                case 1: invalid.originalHeader[13] = 129; break;
                case 2: invalid.descriptor.entries.pop_back(); break;
                case 3: invalid.loadBaseRegister = 32; break;
                case 4: invalid.imageName = std::string(100, 'x'); break;
                }
                bool rejected = false;
                try { ps2x::installSnr2NativeBindings(runtime, {invalid}); }
                catch (const std::invalid_argument&) { rejected = true; }
                t.IsTrue(rejected, "invalid catalogue rejected before observers install");
            }
        });
        tc.Run("Loader branch observers bind before call and remove after guest destructor return", [](TestCase& t) {
            PS2Runtime runtime;
            t.IsTrue(runtime.memory().initialize(), "owned RAM initializes");
            const uint32_t words[] = {0x3C080114, 0x25088730};
            std::memcpy(runtime.memory().getRDRAM() + 0x1000, words, sizeof(words));
            auto descriptor = simpleDescriptor();
            unsigned loadCalls = 0, unloadCalls = 0;
            runtime.setGuestBranchObserver(0x2000, [&](uint8_t* ram, R5900Context* ctx, PS2Runtime* owner,
                uint32_t source, uint32_t target, PS2Runtime::GuestBranchKind kind) {
                ++loadCalls;
                t.Equals(source, 0x2000u, "observer receives original call site");
                t.Equals(target, 0x1000u, "observer receives relocated constructor target");
                t.Equals(ctx->pc, target, "observer sees PC after target transfer");
                t.IsTrue(ram == owner->memory().getRDRAM(), "observer sees actual runtime RAM");
                t.IsTrue(kind == PS2Runtime::GuestBranchKind::IndirectCall, "original branch kind is preserved");
                return owner->bindNativeModule(0x1000, descriptor);
            });
            R5900Context ctx{};
            t.IsTrue(runtime.dispatchGuestBranch(runtime.memory().getRDRAM(), &ctx, 0x1000,
                0x2000, 0x1008, PS2Runtime::GuestBranchKind::IndirectCall, "native-loader-canary"),
                "constructor dispatch can find a module installed at original call boundary");
            t.Equals(loadCalls, 1u, "load observer ran exactly once");
            runtime.setGuestBranchObserver(0x2008, [&](uint8_t*, R5900Context*, PS2Runtime* owner,
                uint32_t, uint32_t, PS2Runtime::GuestBranchKind) {
                ++unloadCalls;
                return owner->unbindNativeModule(0x1000);
            });
            t.IsTrue(runtime.registerFunction(0x3000, staticBody), "original unlink target exists");
            t.IsTrue(runtime.dispatchGuestBranch(runtime.memory().getRDRAM(), &ctx, 0x3000,
                0x2008, 0x3004, PS2Runtime::GuestBranchKind::DirectCall, "native-unload-canary"),
                "unlink transfer continues after removal");
            t.Equals(unloadCalls, 1u, "unload observer ran exactly once");
            t.IsFalse(runtime.hasFunction(0x1000), "image entry is gone before unlink/free continues");
        });
        tc.Run("Branch observer removal replacement and veto do not corrupt dispatch", [](TestCase& t) {
            PS2Runtime runtime;
            t.IsTrue(runtime.registerFunction(0x3000, staticBody), "fixture target exists");
            unsigned calls = 0;
            runtime.setGuestBranchObserver(0x2000, [&](uint8_t*, R5900Context*, PS2Runtime* owner,
                uint32_t, uint32_t, PS2Runtime::GuestBranchKind) {
                ++calls;
                owner->setGuestBranchObserver(0x2000, {});
                return true;
            });
            R5900Context ctx{};
            t.IsTrue(runtime.dispatchGuestBranch(nullptr, &ctx, 0x3000, 0x2000, 0x3004,
                PS2Runtime::GuestBranchKind::DirectCall, "self-remove-observer"), "callback remains alive while removing itself");
            t.IsTrue(runtime.dispatchGuestBranch(nullptr, &ctx, 0x3000, 0x2000, 0x3004,
                PS2Runtime::GuestBranchKind::DirectCall, "removed-observer"), "later transfer uses ordinary target");
            t.Equals(calls, 1u, "removed callback does not run again");
            runtime.setGuestBranchObserver(0x2000, [](uint8_t*, R5900Context*, PS2Runtime*, uint32_t,
                uint32_t, PS2Runtime::GuestBranchKind) { return false; });
            t.IsTrue(runtime.dispatchGuestBranch(nullptr, &ctx, 0x3000, 0x2010, 0x3004,
                PS2Runtime::GuestBranchKind::DirectCall, "unrelated-source"), "observer does not intercept unrelated source");
            t.IsFalse(runtime.dispatchGuestBranch(nullptr, &ctx, 0x3000, 0x2000, 0x3004,
                PS2Runtime::GuestBranchKind::DirectCall, "rejected-binding"), "invalid binding may veto dispatch");
            t.Equals(ctx.pc, 0u, "veto cannot manufacture successful continuation");
            t.IsTrue(runtime.isStopRequested(), "veto is a stopped runtime rather than a successful PC-zero return");
        });
        tc.Run("Runtime module ownership rejects static collisions and invalidates RAM generations", [](TestCase& t) {
            reset_ps2_test_function_table();
            PS2Runtime runtime;
            auto descriptor = simpleDescriptor();
            t.IsFalse(runtime.bindNativeModule(0x1000, descriptor), "uninitialized RAM cannot validate module");
            t.IsTrue(runtime.memory().initialize(), "runtime memory initializes without a graphics window");
            const uint32_t words[] = {0x3C080114, 0x25088730};
            std::memcpy(runtime.memory().getRDRAM() + 0x1000, words, sizeof(words));
            t.IsTrue(runtime.bindNativeModule(0x1000, descriptor), "module binds to owned RAM");
            t.IsFalse(runtime.hasFunction(0x1008), "data address is not an executable entry");
            t.IsFalse(runtime.registerFunction(0x100C, staticBody), "static entry cannot replace loaded module data");
            auto dispatch = runtime.lookupFunction(0x1000);
            runtime.clearNativeModules();
            t.IsFalse(runtime.hasFunction(0x1000), "clear removes module from ordinary lookup");
            t.IsTrue(runtime.bindNativeModule(0x1000, descriptor), "module can reload after clear");
            const auto generation = runtime.memory().rdramGeneration();
            t.IsTrue(runtime.memory().initialize(), "memory can be replaced");
            t.IsTrue(runtime.memory().rdramGeneration() != generation, "RAM generation changes even if allocator reuses address");
            t.IsFalse(runtime.hasFunction(0x1000), "new RAM invalidates old native binding");
            R5900Context ctx{};
            ctx.pc = 0x1000;
            dispatch(runtime.memory().getRDRAM(), &ctx, &runtime);
            t.Equals(ctx.pc, 0u, "cached dispatcher cannot execute invalidated image");
            t.IsTrue(runtime.isStopRequested(), "invalidated image cannot complete a scheduler invocation successfully");
            std::memcpy(runtime.memory().getRDRAM() + 0x1000, words, sizeof(words));
            t.IsTrue(runtime.bindNativeModule(0x1000, descriptor), "new RAM may bind fresh verified image");
            runtime.clearNativeModules();
            t.IsTrue(runtime.registerFunction(0x1000, staticBody), "static fixture registers after removal");
            t.IsFalse(runtime.bindNativeModule(0x1000, descriptor), "module cannot hide main executable entry");
            t.IsTrue(runtime.hasFunction(0x1000), "rejected bind preserves existing static entry");
            reset_ps2_test_function_table();
        });
        tc.Run("Runtime refuses continuation when native body unloads its image", [](TestCase& t) {
            PS2Runtime runtime;
            t.IsTrue(runtime.memory().initialize(), "runtime RAM initializes");
            const uint32_t words[] = {0x3C080114, 0x25088730};
            std::memcpy(runtime.memory().getRDRAM() + 0x1000, words, sizeof(words));
            auto descriptor = simpleDescriptor();
            for (auto& entry : descriptor.entries) entry.function = runtimeRemovingBody;
            t.IsTrue(runtime.bindNativeModule(0x1000, descriptor), "self-unloading module binds");
            R5900Context ctx{};
            t.IsFalse(runtime.dispatchGuestBranch(runtime.memory().getRDRAM(), &ctx,
                0x1000, 0x2000, 0x1008, PS2Runtime::GuestBranchKind::IndirectCall, "unload-canary"),
                "removed image cannot manufacture successful call return");
            t.Equals(ctx.pc, 0u, "invalid continuation stops execution");
            t.IsTrue(runtime.isStopRequested(), "self-unload failure stops runtime");
            t.IsFalse(runtime.hasFunction(0x1000), "unloaded entries are absent");
        });
        tc.Run("Variable-base native JALR preserves same-register target and returns through actual runtime", [](TestCase& t) {
            reset_ps2_test_function_table();
            for (uint32_t base : {0x10FD800u, 0x100000u, 0x1A00000u}) {
                PS2Runtime runtime;
                enteredCallee = 0;
                t.IsTrue(runtime.memory().initialize(), "runtime owns initialized RAM");
                uint8_t* ram = runtime.memory().getRDRAM();
                const uint32_t words[] = {0, 0x24020005, 0x03E0F809, 0x24420007,
                    0x24420003, 0x0320F82D, 0x03E00008, 0x24420002, 0,
                    0x2442000B, 0x03E00008, 0x2442000D};
                std::memcpy(ram+base, words, sizeof(words));
                ps2x::NativeModuleDescriptor descriptor;
                descriptor.identity = "native-indirect-canary";
                descriptor.imageSize = sizeof(words);
                for (unsigned i = 0; i < 12; ++i) descriptor.codeWords.push_back({i*4, words[i], 0});
                for (uint32_t offset : {0u, 0x10u, 0x24u})
                    descriptor.entries.push_back({offset, 0, sizeof(words), nativeRuntimeProbe});
                t.IsTrue(runtime.bindNativeModule(base, descriptor), "runtime validates and owns generated native module");
                t.IsTrue(runtime.hasFunction(base + 0x24), "normal runtime dispatch sees module callee without manual adapter");
                R5900Context ctx{};
                ctx.pc = base;
                ctx.r[31] = _mm_set_epi64x(0, base + 0x24);
                ctx.r[25] = _mm_set_epi64x(0, 0x12345670u);
                runtime.lookupFunction(base)(ram, &ctx, &runtime);
                t.Equals(enteredCallee, 1u, "JALR ra,ra captures original target before setting link register");
                t.Equals(ctx.pc, 0x12345670u, "caller continuation and final return preserve actual addresses");
                t.Equals(static_cast<uint32_t>(_mm_cvtsi128_si32(ctx.r[2])), 41u, "callee and caller delay slots execute once");
                t.Equals(static_cast<uint32_t>(_mm_cvtsi128_si32(ctx.r[31])), 0x12345670u, "caller restores external return address");
                t.IsFalse(ctx.in_delay_slot, "delay slot state is clear after final return");
                t.IsTrue(runtime.unbindNativeModule(base), "removing module removes all entry points");
                t.IsFalse(runtime.hasFunction(base + 0x24), "normal runtime dispatch no longer sees removed callee");
                t.IsFalse(runtime.hasFunction(base), "caller lookup is absent after unload");
                activeRegistry = nullptr;
                reset_ps2_test_function_table();
            }
        });
        tc.Run("Module unload reload reset and wrong memory never revive stale bindings", [](TestCase& t) {
            ps2x::NativeModuleRegistry registry;
            std::vector<uint8_t> ram(0x4000), otherRam(0x4000);
            seedSimple(ram, 0x1000);
            auto descriptor = simpleDescriptor();
            t.IsTrue(registry.bind(0x1000, descriptor, ram), "relocated operands validate against immutable instruction fields");
            auto old = registry.lookup(0x1000);
            R5900Context ctx{};
            ctx.pc = 0x1000;
            t.IsFalse(old.invoke(otherRam.data(), &ctx, nullptr), "another RAM buffer cannot reuse validated image binding");
            ctx.pc = 0x1004;
            t.IsFalse(old.invoke(ram.data(), &ctx, nullptr), "handle cannot execute a different entry point");
            ctx.pc = 0x1000;
            t.IsTrue(old.invoke(ram.data(), &ctx, nullptr), "valid handle passes actual base to native body");
            t.Equals(ctx.pc, 0x1008u, "body receives correct base");
            t.IsTrue(registry.unbind(0x1000), "unbind removes image");
            t.IsFalse(old.valid(), "cached handle expires");
            t.IsTrue(registry.bind(0x1000, descriptor, ram), "same address can load a new instance");
            ctx.pc = 0x1000;
            t.IsFalse(old.invoke(ram.data(), &ctx, nullptr), "old generation cannot execute reloaded image");
            auto fresh = registry.lookup(0x1000);
            t.IsTrue(fresh.valid(), "new instance has valid independent handle");
            descriptor.codeWords.clear();
            t.IsTrue(fresh.invoke(ram.data(), &ctx, nullptr), "binding owns immutable descriptor copy");
            registry.clear();
            t.IsFalse(fresh.valid(), "reset invalidates all handles");
            t.Equals(registry.moduleCount(), size_t(0), "reset removes all instances");
        });
        tc.Run("Module identity coverage bounds collisions and invalid masks reject atomically", [](TestCase& t) {
            ps2x::NativeModuleRegistry registry;
            std::vector<uint8_t> ram(0x4000);
            seedSimple(ram, 0x1000);
            const auto descriptor = simpleDescriptor();
            t.IsTrue(registry.bind(0x1000, descriptor, ram), "baseline binds");
            std::string reason;
            t.IsFalse(registry.bind(0x1000, descriptor, ram, &reason), "overlapping instance rejected");
            t.IsFalse(reason.empty(), "rejection gives actionable reason");
            for (unsigned failure = 0; failure < 7; ++failure) {
                auto invalid = descriptor;
                seedSimple(ram, 0x2000);
                switch (failure) {
                case 0: invalid.codeWords.pop_back(); break;
                case 1: invalid.codeWords[0].variableBits = 0xFFFFFFFF; break;
                case 2: invalid.codeWords[0].original ^= 1u << 16; break;
                case 3: invalid.entries[1].offset = 0; break;
                case 4: invalid.entries[1].function = nullptr; break;
                case 5: invalid.entries[1].ownerEnd = 12; break;
                case 6: invalid.imageSize = 0x4000; break;
                }
                t.IsFalse(registry.bind(0x2000, invalid, ram, &reason), "invalid image descriptor is rejected");
                t.Equals(registry.moduleCount(), size_t(1), "failed bind cannot partially install instance");
                t.IsTrue(registry.lookup(0x1000).valid(), "existing binding survives rejected image");
                t.IsFalse(registry.lookup(0x2000).valid(), "failed image exposes no entry point");
            }
        });
        tc.Run("Module removed during native invocation stays alive until return and invalidates continuation", [](TestCase& t) {
            ps2x::NativeModuleRegistry registry;
            activeRegistry = &registry;
            std::vector<uint8_t> ram(0x4000);
            seedSimple(ram, 0x1000);
            auto descriptor = simpleDescriptor();
            for (auto& entry : descriptor.entries) entry.function = selfRemovingBody;
            t.IsTrue(registry.bind(0x1000, descriptor, ram), "self-removing fixture binds");
            auto handle = registry.lookup(0x1000);
            R5900Context ctx{};
            ctx.pc = 0x1000;
            t.IsFalse(handle.invoke(ram.data(), &ctx, nullptr), "return reports that binding was removed during invocation");
            t.Equals(ctx.pc, 0x1008u, "body completed without descriptor lifetime corruption");
            t.IsFalse(handle.valid(), "removed instance cannot continue");
            t.IsFalse(registry.hasFunction(0x1000), "self-removal removes presence query entries");
            t.Equals(registry.moduleCount(), size_t(0), "instance and resume entries are gone");
            activeRegistry = nullptr;
        });
    });
}

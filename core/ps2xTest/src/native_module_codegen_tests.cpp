#include "MiniTest.h"
#include "ps2recomp/native_module_codegen.h"
#include <cstring>
#include <stdexcept>

void registerNativeModuleCodegenTests()
{
    MiniTest::Case("NativeModuleCodegen", [](TestCase& tc) {
        auto fixture = [] {
            ps2recomp::NativeModuleCodegenInput input;
            input.identifier = "synthetic_module";
            input.identity = "reviewed-test-image";
            input.image.resize(0x100);
            const uint32_t words[] = {0x3C080004, 0x2508AF30, 0x0100F809, 0,
                                       0x03E00008, 0};
            std::memcpy(input.image.data() + 0x40, words, sizeof(words));
            input.bodies = {{0x40, 0x58, {}}};
            input.instructionRelocations = {{0x40, 5}, {0x44, 6}};
            return input;
        };
        tc.Run("Native descriptor covers compiled instructions and call resume entries", [=](TestCase& t) {
            const auto code = ps2recomp::generateNativeModule(fixture());
            t.IsTrue(code.find("synthetic_module_descriptor()") != std::string::npos, "descriptor factory is generated");
            t.IsTrue(code.find("{80u, 64u, 88u, synthetic_module_body_64}") != std::string::npos, "JALR continuation has its owner and body");
            t.IsTrue(code.find("{64u, 1007157252u, 65535u}") != std::string::npos, "LUI identity permits only relocated halfword");
            t.IsTrue(code.find("case 0x50u: goto label_50") != std::string::npos, "registered continuation actually resumes generated body");
            t.IsTrue(code.find("uint32_t ps2_module_base") != std::string::npos, "body uses variable load base ABI");
        });
        tc.Run("Invalid native range relocation entry and unsupported instruction fail before output", [=](TestCase& t) {
            for (unsigned variant = 0; variant < 8; ++variant) {
                auto input = fixture();
                switch (variant) {
                case 0: input.identifier = "bad-name"; break;
                case 1: input.bodies[0].end = 0x54; break;
                case 2: input.bodies.push_back(input.bodies[0]); break;
                case 3: input.bodies[0].entries = {0x100}; break;
                case 4: input.instructionRelocations[0x80] = 5; break;
                case 5: input.instructionRelocations[0x44] = 2; break;
                case 6: input.instructionRelocations[0x44] = 5; break;
                case 7: { const uint32_t word = 0x4C000000; std::memcpy(input.image.data()+0x44, &word, 4); input.instructionRelocations.erase(0x44); break; }
                }
                bool rejected = false;
                try { (void)ps2recomp::generateNativeModule(input); }
                catch (const std::invalid_argument&) { rejected = true; }
                t.IsTrue(rejected, "malformed module cannot produce a registered native descriptor");
            }
        });
        tc.Run("Native FBRST write declares and calls the control action API", [=](TestCase &t) {
            auto input = fixture();
            const uint32_t words[] = {0x48C8E000u, 0x03E00008u, 0u};
            std::memcpy(input.image.data() + 0x40, words, sizeof(words));
            input.bodies = {{0x40, 0x4C, {}}};
            input.instructionRelocations.clear();
            const auto code = ps2recomp::generateNativeModule(input);
            t.IsTrue(code.find("#include \"runtime/ps2_vu_control.h\"") != std::string::npos,
                     "native module source declares runtime control writes");
            t.IsTrue(code.find("ps2WriteVuFbrst(*runtime, *ctx, GPR_U32(ctx, 8))") != std::string::npos,
                     "native module executes reset actions rather than just latching enable bits");
            t.IsTrue(code.find("ctx->vu0_fbrst =") == std::string::npos,
                     "native control write cannot bypass the reset implementation");
        });
    });
}

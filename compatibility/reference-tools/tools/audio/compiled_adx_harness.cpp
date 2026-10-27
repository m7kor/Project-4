// Diagnostic harness for generated integer-only ADX routines. No devices or
// scheduler: special-address accesses fail, checkpoints use a controlled probe.
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"

static unsigned checkpointPeriod = 0, checkpointCount = 0;
static bool decoderCheckpointDue()
{
    return checkpointPeriod && (++checkpointCount % checkpointPeriod == 0);
}

#define LOAD_STUB(bits, type) type PS2Runtime::Load##bits(uint8_t*, R5900Context*, uint32_t) { throw std::runtime_error("device read unsupported"); }
LOAD_STUB(8, uint8_t)
LOAD_STUB(16, uint16_t)
LOAD_STUB(32, uint32_t)
LOAD_STUB(64, uint64_t)
LOAD_STUB(128, __m128i)
#define STORE_STUB(bits, type) void PS2Runtime::Store##bits(uint8_t*, R5900Context*, uint32_t, type) { throw std::runtime_error("device write unsupported"); }
STORE_STUB(8, uint8_t)
STORE_STUB(16, uint16_t)
STORE_STUB(32, uint32_t)
STORE_STUB(64, uint64_t)
STORE_STUB(128, __m128i)
void PS2Runtime::handleBreak(uint8_t*, R5900Context*) { throw std::runtime_error("guest BREAK unsupported"); }
void FUN_001893D0_0x1893d0(uint8_t*, R5900Context*, PS2Runtime*) { throw std::runtime_error("guest SJ validation failed"); }
void FUN_0018B640_0x18b640(uint8_t*, R5900Context*, PS2Runtime*) { throw std::runtime_error("guest CRI lock validation failed"); }

static bool decoderDispatchGuestBranch(uint8_t*, R5900Context*, uint32_t, uint32_t, uint32_t, PS2Runtime::GuestBranchKind, const char*);
#include "decoder_routes.inc"
static bool decoderDispatchGuestBranch(uint8_t* ram, R5900Context* ctx, uint32_t target, uint32_t, uint32_t fallthrough, PS2Runtime::GuestBranchKind, const char*)
{
    ctx->pc = target;
    // Production dispatch is a safe point before entering the callee too.
    // Unwind with PC at the target, then let the outer executor resume it.
    if (decoderCheckpointDue()) return false;
    decoderDispatchFunction(ram, ctx);
    return ctx->pc == fallthrough;
}

int main(int argc, char** argv)
{
    try
    {
        if (argc != 5) throw std::runtime_error("usage: harness RAM CONTEXT OUT_RAM CHECKPOINT_PERIOD");
        checkpointPeriod = static_cast<unsigned>(std::stoul(argv[4]));
        std::ifstream ramInput(argv[1], std::ios::binary), contextInput(argv[2], std::ios::binary);
        std::vector<uint8_t> ram(32u * 1024u * 1024u);
        R5900Context ctx;
        ramInput.read(reinterpret_cast<char*>(ram.data()), ram.size());
        contextInput.read(reinterpret_cast<char*>(ctx.r), sizeof(ctx.r));
        uint64_t hiLo[4]; uint32_t pcSa[2];
        contextInput.read(reinterpret_cast<char*>(hiLo), sizeof(hiLo));
        contextInput.read(reinterpret_cast<char*>(pcSa), sizeof(pcSa));
        if (!ramInput || !contextInput || ramInput.peek() != EOF || contextInput.peek() != EOF)
            throw std::runtime_error("invalid input sizes");
        ctx.hi = hiLo[0]; ctx.lo = hiLo[1]; ctx.hi1 = hiLo[2]; ctx.lo1 = hiLo[3];
        ctx.pc = pcSa[0]; ctx.sa = pcSa[1];
        const uint32_t returnPc = GPR_U32((&ctx), 31);
        unsigned dispatches = 0;
        while (ctx.pc != returnPc)
        {
            if (++dispatches > 1000000u) throw std::runtime_error("dispatch limit");
            decoderDispatchFunction(ram.data(), &ctx);
        }
        if (std::ifstream(argv[3]).good()) throw std::runtime_error("output exists");
        std::ofstream output(argv[3], std::ios::binary);
        output.write(reinterpret_cast<const char*>(ram.data()), ram.size()); output.close();
        if (!output) throw std::runtime_error("output write failed");
        std::cout << "{\"return_value\":" << GPR_S32((&ctx), 2) << ",\"dispatches\":" << dispatches
                  << ",\"checkpoint_period\":" << checkpointPeriod << ",\"gpr_hex\":[";
        for (unsigned reg = 0; reg < 32u; ++reg)
        {
            uint64_t parts[2]; std::memcpy(parts, &ctx.r[reg], sizeof(parts));
            std::cout << (reg ? "," : "") << "[\"" << std::hex << parts[0] << "\",\"" << parts[1] << "\"]";
        }
        std::cout << "],\"hi_lo_hex\":[\"" << ctx.hi << "\",\"" << ctx.lo
                  << "\",\"" << ctx.hi1 << "\",\"" << ctx.lo1 << "\"]}\n";
        return 0;
    }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}

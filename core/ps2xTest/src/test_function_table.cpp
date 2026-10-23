#include "ps2_runtime.h"
#include "runtime/ps2_memory.h"

#include <algorithm>

// For Unit tests link ps2_runtime without the generated runner source.
extern const uint32_t g_ps2RecompiledFunctionTableBase = 0x00000000u;
extern const uint32_t g_ps2RecompiledFunctionTableEnd = PS2_RAM_SIZE;
extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = (g_ps2RecompiledFunctionTableEnd - g_ps2RecompiledFunctionTableBase) >> 2;

PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[g_ps2RecompiledFunctionTableSlotCount] = {};

// Synthetic kernel patch entries, outside the dense RAM table. These test the
// same generated-table ABI used by runtime-installed guest code.
namespace
{
    void sparseFirst(uint8_t *, R5900Context *ctx, PS2Runtime *) { ctx->pc = 0x1234u; }
    void sparseLast(uint8_t *, R5900Context *ctx, PS2Runtime *) { ctx->pc = 0x5678u; }
}
extern const uint32_t g_ps2RecompiledFunctionSparseCount = 2u;
extern const uint32_t g_ps2RecompiledFunctionSparseAddress[2u] = {0x80075000u, 0x80076000u};
extern const PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionSparseTarget[2u] = {sparseFirst, sparseLast};

void reset_ps2_test_function_table()
{
    std::fill(g_ps2RecompiledFunctionTable,
              g_ps2RecompiledFunctionTable + g_ps2RecompiledFunctionTableSlotCount,
              nullptr);
}

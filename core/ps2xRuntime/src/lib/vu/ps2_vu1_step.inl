// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "ps2_vu1_detail.h"

// The per-pair step of VU1Interpreter::run (everything after the decoded
// pair is chosen). Inline so that a compiled microprogram can call it with a
// constexpr DecodedInstructionPair and let the compiler fold the decode.
// Returns 1 to leave the run loop.
PS2X_VU1_STEP_INLINE int VU1Interpreter::stepPairBody(const DecodedInstructionPair &decoded, uint8_t *vuData,
                                                      uint32_t dataSize, GS &gs, PS2Memory *memory,
                                                      uint32_t codeSize, uint64_t budgetEnd, bool &programEnded)
{
    auto &vu = *this;
#define PS2X_VU1_ISSUE_UPPER(instruction) execUpper(instruction)
#include "ps2_vu1_step_body.inl"
#undef PS2X_VU1_ISSUE_UPPER
}

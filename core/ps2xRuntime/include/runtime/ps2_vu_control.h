// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
class PS2Runtime;
struct R5900Context;

// EE-only hardware control. FBRST/VPU_STAT belong to runtime.cpu(), not to a
// guest thread or invocation. The context argument is a compatibility mirror;
// reads always use the shared owner. Async VU must synchronize before writes.
void ps2WriteVuFbrst(PS2Runtime &runtime, R5900Context &context, uint32_t value);
uint32_t ps2ReadVuFbrst(const PS2Runtime &runtime, const R5900Context &context);
uint32_t ps2ReadVuStatus(const PS2Runtime &runtime, const R5900Context &context);

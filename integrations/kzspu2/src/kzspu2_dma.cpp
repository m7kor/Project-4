// Keep the pinned upstream DMA implementation intact, but observe the bytes
// it actually copies into SPU2 input memory, rather than the earlier DMA start.
// The forced prefix has already included headers before this local macro.
// SPDX-License-Identifier: GPL-3.0-or-later
#include "kzspu2_prefix.h"
void* kzspu2DmaMemcpy(void* destination, const void* source, size_t bytes);
#define memcpy kzspu2DmaMemcpy
#include "SPU2/Dma.cpp"
#undef memcpy

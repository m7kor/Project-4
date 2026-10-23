// EE IPU model. See runtime/ps2_ipu.h for scope and provenance.
//
// Adapted from ico-recomp's hw/ipu.cpp (MIT, Copyright (c) 2026 ico-recomp
// contributors). The decode model, the FIFO/BP accounting and the DMA bridge
// follow that file; its long-form trace ring is replaced by the runtime's
// PS2X_TRACE_IPU switch, and its fatal stops on commands outside ICO's census
// become logged errors that finish the command with IPU_CTRL.ECD set.
//
// Input FIFO contract. Sony's libmpeg measures the stream position as
//
//     stream byte = D4_MADR - (IFC + FP) * 16 + (IPU_BP.BP >> 3)
//
// and its stop/restart bracket rewinds ch4 to MADR - (IFC + FP) * 16 with
// QWC + IFC + FP, then issues BCLR with the saved BP. RE4 does the same in
// its DMA restart at 0x2CDC90 (IFC = (bp >> 8) & 0xF, FP = (bp >> 16) & 3,
// MADR' = MADR - (IFC + FP) * 16, then BCLR(bp & 0x7F) and the D4 stores).
// So:
//   1. MADR/QWC/TADR advance only by what actually entered the input FIFO;
//      the DMA never runs more than the FIFO depth ahead of the decoder.
//   2. IPU_BP.BP is the bit offset inside the first resident quadword and
//      IFC + FP is the number of resident quadwords from the decode cursor.
//   3. CHCR written with STR clear stops the transfer with those registers
//      frozen where the FIFO fill left them.
//
// Model:
//   - Input is a byte queue standing for the 8-quadword FIFO plus the one
//     quadword the decoder is inside (FP=1). ch4 (normal or source chain)
//     pushes quadwords and stalls when the FIFO is full. Reading a chain tag
//     costs no FIFO space, so the walk reaches the end tag even with the FIFO
//     full and the transfer completes when the last payload has entered it.
//   - Commands execute synchronously at the IPU_CMD write. One that runs out
//     of input rewinds to its start and stays pending (BUSY); it is retried
//     whenever the guest observes the IPU or new input arrives. BDEC's
//     trailing start-code scan and CSC's per-macroblock output commit as they
//     go, because hardware has no rewind and their input exceeds the FIFO.
//   - BCLR discards the FIFO and sets BP; a pending command survives it and
//     resumes at the new BP (libmpeg issues BCLR from inside its restart).
//   - Output is an unbounded queue drained by ch3 (normal mode) while the
//     command runs, so IPU_CTRL.OFC returns to 0 as the library expects.
//   - Command completion raises INTC cause 8.
//
// Sources: EE User's Manual IPU chapter and ps2tek for registers and command
// encodings; ISO/IEC 13818-2 tables B-1..B-15 for the VLC code assignments
// (facts fixed by the standard); the IDCT is a direct double-precision
// implementation of the Annex A definition.

#include "runtime/ps2_ipu.h"
#include "ipu_round_pixel.h"

#include <algorithm>
#include <bit>
#include <cinttypes>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#if defined(__SSE4_1__)
#include <smmintrin.h>
#endif
#ifdef _MSC_VER
#include <intrin.h>
#endif

namespace
{
    bool isPow2(uint64_t v) { return v != 0u && (v & (v - 1u)) == 0u; }

    // PS2X_TRACE_IPU: register trace (ps2_memory.cpp) plus a command census
    // logged at power-of-two counts. PS2X_TRACE_IPU_MODEL: per-command and
    // per-transfer detail, which runs to one line per macroblock in a movie.
    bool censusEnabled()
    {
        static const bool enabled = std::getenv("PS2X_TRACE_IPU") != nullptr;
        return enabled;
    }

    bool traceEnabled()
    {
        static const bool enabled = std::getenv("PS2X_TRACE_IPU_MODEL") != nullptr;
        return enabled;
    }

    void ipuLog(const char *level, const char *fmt, ...)
    {
        char buffer[512];
        va_list ap;
        va_start(ap, fmt);
        std::vsnprintf(buffer, sizeof(buffer), fmt, ap);
        va_end(ap);
        std::cerr << "[IPU " << level << "] " << buffer << std::endl;
    }

#define IPU_DEBUG(...)                       \
    do                                       \
    {                                        \
        if (traceEnabled())                  \
            ipuLog("debug", __VA_ARGS__);    \
    } while (0)

// Always reported, but only on the 1st, 2nd, 4th, 8th ... occurrence.
#define IPU_WARN_SAMPLED(...)                                \
    do                                                       \
    {                                                        \
        static uint64_t sampledCount = 0;                    \
        if (traceEnabled() || isPow2(++sampledCount))        \
            ipuLog("warn", __VA_ARGS__);                     \
    } while (0)

    // Input FIFO depth in quadwords (IPU_CTRL.IFC / IPU_BP.IFC are 4 bits).
    constexpr size_t kFifoQw = 8;

    constexpr int MB_INTRA = 1, MB_PATTERN = 2, MB_BACKWARD = 4, MB_FORWARD = 8, MB_QUANT = 16;
    constexpr int MB_MC_FRAME = 128; // motion_type frame, bits 6-7 = 2

    // B-1 macroblock_address_increment. 0x22 = stuffing (MPEG1), 0x23 = escape.
    constexpr IpuVlc kMbai[] = {
        {0x0001, 1, 1}, {0x0002, 3, 3}, {0x0003, 3, 2}, {0x0002, 4, 5},
        {0x0003, 4, 4}, {0x0002, 5, 7}, {0x0003, 5, 6}, {0x0006, 7, 9},
        {0x0007, 7, 8}, {0x0006, 8, 15}, {0x0007, 8, 14}, {0x0008, 8, 13},
        {0x0009, 8, 12}, {0x000A, 8, 11}, {0x000B, 8, 10}, {0x0012, 10, 21},
        {0x0013, 10, 20}, {0x0014, 10, 19}, {0x0015, 10, 18}, {0x0016, 10, 17},
        {0x0017, 10, 16}, {0x0008, 11, 0x23}, {0x000F, 11, 0x22}, {0x0018, 11, 33},
        {0x0019, 11, 32}, {0x001A, 11, 31}, {0x001B, 11, 30}, {0x001C, 11, 29},
        {0x001D, 11, 28}, {0x001E, 11, 27}, {0x001F, 11, 26}, {0x0020, 11, 25},
        {0x0021, 11, 24}, {0x0022, 11, 23}, {0x0023, 11, 22},
    };

    // B-2/B-3/B-4 macroblock_type.
    constexpr IpuVlc kMbtI[] = {
        {0x0001, 1, MB_INTRA}, {0x0001, 2, MB_INTRA | MB_QUANT},
    };
    constexpr IpuVlc kMbtP[] = {
        {0x0001, 1, MB_FORWARD | MB_PATTERN}, {0x0001, 2, MB_PATTERN},
        {0x0001, 3, MB_FORWARD}, {0x0001, 5, MB_QUANT | MB_PATTERN},
        {0x0002, 5, MB_QUANT | MB_FORWARD | MB_PATTERN}, {0x0003, 5, MB_INTRA},
        {0x0001, 6, MB_QUANT | MB_INTRA},
    };
    constexpr IpuVlc kMbtB[] = {
        {0x0002, 2, MB_FORWARD | MB_BACKWARD},
        {0x0003, 2, MB_FORWARD | MB_BACKWARD | MB_PATTERN},
        {0x0002, 3, MB_BACKWARD}, {0x0003, 3, MB_BACKWARD | MB_PATTERN},
        {0x0002, 4, MB_FORWARD}, {0x0003, 4, MB_FORWARD | MB_PATTERN},
        {0x0002, 5, MB_QUANT | MB_FORWARD | MB_BACKWARD | MB_PATTERN},
        {0x0003, 5, MB_INTRA},
        {0x0001, 6, MB_QUANT | MB_INTRA},
        {0x0002, 6, MB_QUANT | MB_BACKWARD | MB_PATTERN},
        {0x0003, 6, MB_QUANT | MB_FORWARD | MB_PATTERN},
    };

    // B-10 motion_code magnitude (sign bit follows the code).
    constexpr IpuVlc kMotion[] = {
        {0x0001, 1, 0}, {0x0001, 2, 1}, {0x0001, 3, 2}, {0x0001, 4, 3},
        {0x0003, 6, 4}, {0x0003, 7, 7}, {0x0004, 7, 6}, {0x0005, 7, 5},
        {0x0009, 9, 10}, {0x000A, 9, 9}, {0x000B, 9, 8}, {0x000C, 10, 16},
        {0x000D, 10, 15}, {0x000E, 10, 14}, {0x000F, 10, 13}, {0x0010, 10, 12},
        {0x0011, 10, 11},
    };

    // B-11 dmvector.
    constexpr IpuVlc kDmv[] = {
        {0x0000, 1, 0}, {0x0002, 2, 1}, {0x0003, 2, -1},
    };

    // B-9 coded_block_pattern.
    constexpr IpuVlc kCbp[] = {
        {0x0007, 3, 0x3C}, {0x000A, 4, 0x20}, {0x000B, 4, 0x10}, {0x000C, 4, 0x08},
        {0x000D, 4, 0x04}, {0x0008, 5, 0x3E}, {0x0009, 5, 0x02}, {0x000A, 5, 0x3D},
        {0x000B, 5, 0x01}, {0x000C, 5, 0x38}, {0x000D, 5, 0x34}, {0x000E, 5, 0x2C},
        {0x000F, 5, 0x1C}, {0x0010, 5, 0x28}, {0x0011, 5, 0x14}, {0x0012, 5, 0x30},
        {0x0013, 5, 0x0C}, {0x000C, 6, 0x3F}, {0x000D, 6, 0x03}, {0x000E, 6, 0x24},
        {0x000F, 6, 0x18}, {0x0010, 7, 0x22}, {0x0011, 7, 0x12}, {0x0012, 7, 0x0A},
        {0x0013, 7, 0x06}, {0x0014, 7, 0x21}, {0x0015, 7, 0x11}, {0x0016, 7, 0x09},
        {0x0017, 7, 0x05}, {0x0004, 8, 0x3A}, {0x0005, 8, 0x36}, {0x0006, 8, 0x2E},
        {0x0007, 8, 0x1E}, {0x0008, 8, 0x39}, {0x0009, 8, 0x35}, {0x000A, 8, 0x2D},
        {0x000B, 8, 0x1D}, {0x000C, 8, 0x26}, {0x000D, 8, 0x1A}, {0x000E, 8, 0x25},
        {0x000F, 8, 0x19}, {0x0010, 8, 0x2B}, {0x0011, 8, 0x17}, {0x0012, 8, 0x33},
        {0x0013, 8, 0x0F}, {0x0014, 8, 0x2A}, {0x0015, 8, 0x16}, {0x0016, 8, 0x32},
        {0x0017, 8, 0x0E}, {0x0018, 8, 0x29}, {0x0019, 8, 0x15}, {0x001A, 8, 0x31},
        {0x001B, 8, 0x0D}, {0x001C, 8, 0x23}, {0x001D, 8, 0x13}, {0x001E, 8, 0x0B},
        {0x001F, 8, 0x07}, {0x0001, 9, 0x00}, {0x0002, 9, 0x27}, {0x0003, 9, 0x1B},
        {0x0004, 9, 0x3B}, {0x0005, 9, 0x37}, {0x0006, 9, 0x2F}, {0x0007, 9, 0x1F},
    };

    // B-12/B-13 dct_dc_size.
    constexpr IpuVlc kDcLuma[] = {
        {0x0000, 2, 1}, {0x0001, 2, 2}, {0x0004, 3, 0}, {0x0005, 3, 3},
        {0x0006, 3, 4}, {0x000E, 4, 5}, {0x001E, 5, 6}, {0x003E, 6, 7},
        {0x007E, 7, 8}, {0x00FE, 8, 9}, {0x01FE, 9, 10}, {0x01FF, 9, 11},
    };
    constexpr IpuVlc kDcChroma[] = {
        {0x0000, 2, 0}, {0x0001, 2, 1}, {0x0002, 2, 2}, {0x0006, 3, 3},
        {0x000E, 4, 4}, {0x001E, 5, 5}, {0x003E, 6, 6}, {0x007E, 7, 7},
        {0x00FE, 8, 8}, {0x01FE, 9, 9}, {0x03FE, 10, 10}, {0x03FF, 10, 11},
    };

    // B-14/B-15 DCT coefficients. run 64 = end of block, 65 = escape.
    struct DctVlc
    {
        uint16_t code;
        uint8_t len;
        uint8_t run;
        uint8_t level;
    };

    constexpr DctVlc kDct14[] = {
        {0x0002, 2, 64, 0}, {0x0003, 2, 0, 1}, {0x0003, 3, 1, 1}, {0x0004, 4, 0, 2},
        {0x0005, 4, 2, 1}, {0x0005, 5, 0, 3}, {0x0006, 5, 4, 1}, {0x0007, 5, 3, 1},
        {0x0001, 6, 65, 0}, {0x0004, 6, 7, 1}, {0x0005, 6, 6, 1}, {0x0006, 6, 1, 2},
        {0x0007, 6, 5, 1}, {0x0004, 7, 2, 2}, {0x0005, 7, 9, 1}, {0x0006, 7, 0, 4},
        {0x0007, 7, 8, 1}, {0x0020, 8, 13, 1}, {0x0021, 8, 0, 6}, {0x0022, 8, 12, 1},
        {0x0023, 8, 11, 1}, {0x0024, 8, 3, 2}, {0x0025, 8, 1, 3}, {0x0026, 8, 0, 5},
        {0x0027, 8, 10, 1}, {0x0008, 10, 16, 1}, {0x0009, 10, 5, 2}, {0x000A, 10, 0, 7},
        {0x000B, 10, 2, 3}, {0x000C, 10, 1, 4}, {0x000D, 10, 15, 1}, {0x000E, 10, 14, 1},
        {0x000F, 10, 4, 2}, {0x0010, 12, 0, 11}, {0x0011, 12, 8, 2}, {0x0012, 12, 4, 3},
        {0x0013, 12, 0, 10}, {0x0014, 12, 2, 4}, {0x0015, 12, 7, 2}, {0x0016, 12, 21, 1},
        {0x0017, 12, 20, 1}, {0x0018, 12, 0, 9}, {0x0019, 12, 19, 1}, {0x001A, 12, 18, 1},
        {0x001B, 12, 1, 5}, {0x001C, 12, 3, 3}, {0x001D, 12, 0, 8}, {0x001E, 12, 6, 2},
        {0x001F, 12, 17, 1}, {0x0010, 13, 10, 2}, {0x0011, 13, 9, 2}, {0x0012, 13, 5, 3},
        {0x0013, 13, 3, 4}, {0x0014, 13, 2, 5}, {0x0015, 13, 1, 7}, {0x0016, 13, 1, 6},
        {0x0017, 13, 0, 15}, {0x0018, 13, 0, 14}, {0x0019, 13, 0, 13}, {0x001A, 13, 0, 12},
        {0x001B, 13, 26, 1}, {0x001C, 13, 25, 1}, {0x001D, 13, 24, 1}, {0x001E, 13, 23, 1},
        {0x001F, 13, 22, 1}, {0x0010, 14, 0, 31}, {0x0011, 14, 0, 30}, {0x0012, 14, 0, 29},
        {0x0013, 14, 0, 28}, {0x0014, 14, 0, 27}, {0x0015, 14, 0, 26}, {0x0016, 14, 0, 25},
        {0x0017, 14, 0, 24}, {0x0018, 14, 0, 23}, {0x0019, 14, 0, 22}, {0x001A, 14, 0, 21},
        {0x001B, 14, 0, 20}, {0x001C, 14, 0, 19}, {0x001D, 14, 0, 18}, {0x001E, 14, 0, 17},
        {0x001F, 14, 0, 16}, {0x0010, 15, 0, 40}, {0x0011, 15, 0, 39}, {0x0012, 15, 0, 38},
        {0x0013, 15, 0, 37}, {0x0014, 15, 0, 36}, {0x0015, 15, 0, 35}, {0x0016, 15, 0, 34},
        {0x0017, 15, 0, 33}, {0x0018, 15, 0, 32}, {0x0019, 15, 1, 14}, {0x001A, 15, 1, 13},
        {0x001B, 15, 1, 12}, {0x001C, 15, 1, 11}, {0x001D, 15, 1, 10}, {0x001E, 15, 1, 9},
        {0x001F, 15, 1, 8}, {0x0010, 16, 1, 18}, {0x0011, 16, 1, 17}, {0x0012, 16, 1, 16},
        {0x0013, 16, 1, 15}, {0x0014, 16, 6, 3}, {0x0015, 16, 16, 2}, {0x0016, 16, 15, 2},
        {0x0017, 16, 14, 2}, {0x0018, 16, 13, 2}, {0x0019, 16, 12, 2}, {0x001A, 16, 11, 2},
        {0x001B, 16, 31, 1}, {0x001C, 16, 30, 1}, {0x001D, 16, 29, 1}, {0x001E, 16, 28, 1},
        {0x001F, 16, 27, 1},
    };

    constexpr DctVlc kDct15[] = {
        {0x0002, 2, 0, 1}, {0x0002, 3, 1, 1}, {0x0006, 3, 0, 2}, {0x0006, 4, 64, 0},
        {0x0007, 4, 0, 3}, {0x0005, 5, 2, 1}, {0x0006, 5, 1, 2}, {0x0007, 5, 3, 1},
        {0x001C, 5, 0, 4}, {0x001D, 5, 0, 5}, {0x0001, 6, 65, 0}, {0x0004, 6, 0, 7},
        {0x0005, 6, 0, 6}, {0x0006, 6, 4, 1}, {0x0007, 6, 5, 1}, {0x0004, 7, 7, 1},
        {0x0005, 7, 8, 1}, {0x0006, 7, 6, 1}, {0x0007, 7, 2, 2}, {0x0078, 7, 9, 1},
        {0x0079, 7, 1, 3}, {0x007A, 7, 10, 1}, {0x007B, 7, 0, 8}, {0x007C, 7, 0, 9},
        {0x0020, 8, 1, 5}, {0x0021, 8, 11, 1}, {0x0022, 8, 0, 11}, {0x0023, 8, 0, 10},
        {0x0024, 8, 13, 1}, {0x0025, 8, 12, 1}, {0x0026, 8, 3, 2}, {0x0027, 8, 1, 4},
        {0x00FA, 8, 0, 12}, {0x00FB, 8, 0, 13}, {0x00FC, 8, 2, 3}, {0x00FD, 8, 4, 2},
        {0x00FE, 8, 0, 14}, {0x00FF, 8, 0, 15}, {0x0004, 9, 5, 2}, {0x0005, 9, 14, 1},
        {0x0007, 9, 15, 1}, {0x000C, 10, 2, 4}, {0x000D, 10, 16, 1}, {0x0010, 12, 0, 11},
        {0x0011, 12, 8, 2}, {0x0012, 12, 4, 3}, {0x0013, 12, 0, 10}, {0x0014, 12, 2, 4},
        {0x0015, 12, 7, 2}, {0x0016, 12, 21, 1}, {0x0017, 12, 20, 1}, {0x0018, 12, 0, 9},
        {0x0019, 12, 19, 1}, {0x001A, 12, 18, 1}, {0x001B, 12, 1, 5}, {0x001C, 12, 3, 3},
        {0x001D, 12, 0, 8}, {0x001E, 12, 6, 2}, {0x001F, 12, 17, 1}, {0x0010, 13, 10, 2},
        {0x0011, 13, 9, 2}, {0x0012, 13, 5, 3}, {0x0013, 13, 3, 4}, {0x0014, 13, 2, 5},
        {0x0015, 13, 1, 7}, {0x0016, 13, 1, 6}, {0x0017, 13, 0, 15}, {0x0018, 13, 0, 14},
        {0x0019, 13, 0, 13}, {0x001A, 13, 0, 12}, {0x001B, 13, 26, 1}, {0x001C, 13, 25, 1},
        {0x001D, 13, 24, 1}, {0x001E, 13, 23, 1}, {0x001F, 13, 22, 1}, {0x0010, 14, 0, 31},
        {0x0011, 14, 0, 30}, {0x0012, 14, 0, 29}, {0x0013, 14, 0, 28}, {0x0014, 14, 0, 27},
        {0x0015, 14, 0, 26}, {0x0016, 14, 0, 25}, {0x0017, 14, 0, 24}, {0x0018, 14, 0, 23},
        {0x0019, 14, 0, 22}, {0x001A, 14, 0, 21}, {0x001B, 14, 0, 20}, {0x001C, 14, 0, 19},
        {0x001D, 14, 0, 18}, {0x001E, 14, 0, 17}, {0x001F, 14, 0, 16}, {0x0010, 15, 0, 40},
        {0x0011, 15, 0, 39}, {0x0012, 15, 0, 38}, {0x0013, 15, 0, 37}, {0x0014, 15, 0, 36},
        {0x0015, 15, 0, 35}, {0x0016, 15, 0, 34}, {0x0017, 15, 0, 33}, {0x0018, 15, 0, 32},
        {0x0019, 15, 1, 14}, {0x001A, 15, 1, 13}, {0x001B, 15, 1, 12}, {0x001C, 15, 1, 11},
        {0x001D, 15, 1, 10}, {0x001E, 15, 1, 9}, {0x001F, 15, 1, 8}, {0x0010, 16, 1, 18},
        {0x0011, 16, 1, 17}, {0x0012, 16, 1, 16}, {0x0013, 16, 1, 15}, {0x0014, 16, 6, 3},
        {0x0015, 16, 16, 2}, {0x0016, 16, 15, 2}, {0x0017, 16, 14, 2}, {0x0018, 16, 13, 2},
        {0x0019, 16, 12, 2}, {0x001A, 16, 11, 2}, {0x001B, 16, 31, 1}, {0x001C, 16, 30, 1},
        {0x001D, 16, 29, 1}, {0x001E, 16, 28, 1}, {0x001F, 16, 27, 1},
    };

    // Non-linear quantiser scale, ISO 13818-2 7.4.2.2 (q_scale_type = 1).
    constexpr int kNonLinearQ[32] = {
        0, 1, 2, 3, 4, 5, 6, 7,
        8, 10, 12, 14, 16, 18, 20, 22,
        24, 28, 32, 36, 40, 44, 48, 52,
        56, 64, 72, 80, 88, 96, 104, 112,
    };

    // Inverse scan patterns, ISO 13818-2 figures 7-2 / 7-3.
    constexpr uint8_t kScanZigzag[64] = {
        0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
        12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
        35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
        58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
    };
    constexpr uint8_t kScanAlt[64] = {
        0, 8, 16, 24, 1, 9, 2, 10, 17, 25, 32, 40, 48, 56, 57, 49,
        41, 33, 26, 18, 3, 11, 4, 12, 19, 27, 34, 42, 50, 58, 35, 43,
        51, 59, 20, 28, 5, 13, 6, 14, 21, 29, 36, 44, 52, 60, 37, 45,
        53, 61, 22, 30, 7, 15, 23, 31, 38, 46, 54, 62, 39, 47, 55, 63,
    };

    // [x][u] = C(u)/2 * cos((2x+1)u pi / 16)
    struct IdctMatrix
    {
        double m[8][8];
        IdctMatrix()
        {
            for (int x = 0; x < 8; ++x)
            {
                for (int u = 0; u < 8; ++u)
                {
                    const double cu = (u == 0) ? (1.0 / std::sqrt(2.0)) : 1.0;
                    m[x][u] = 0.5 * cu * std::cos((2 * x + 1) * u * 3.14159265358979323846 / 16.0);
                }
            }
        }
    };

    const IdctMatrix &idctMatrix()
    {
        static const IdctMatrix matrix;
        return matrix;
    }

    void idct8x8(const int16_t in[64], double out[64])
    {
        const auto &m = idctMatrix().m;
        double tmp[64];
        for (int y = 0; y < 8; ++y)
        {
            for (int x = 0; x < 8; ++x)
            {
                double s = 0;
                for (int u = 0; u < 8; ++u)
                    s += m[x][u] * in[y * 8 + u];
                tmp[y * 8 + x] = s;
            }
        }
        for (int x = 0; x < 8; ++x)
        {
            for (int y = 0; y < 8; ++y)
            {
                double s = 0;
                for (int v = 0; v < 8; ++v)
                    s += m[y][v] * tmp[v * 8 + x];
                out[y * 8 + x] = s;
            }
        }
    }

    void saturateCoeff(int32_t *v)
    {
        if (*v > 2047)
            *v = 2047;
        if (*v < -2048)
            *v = -2048;
    }

    int16_t clampPixel(double value, bool intra)
    {
        return ps2x::ipu::roundPixel(value, intra);
    }

    const char *commandName(uint32_t code)
    {
        static const char *names[16] = {"BCLR", "IDEC", "BDEC", "VDEC", "FDEC", "SETIQ", "SETVQ", "CSC",
                                        "PACK", "SETTH", "?", "?", "?", "?", "?", "?"};
        return names[code & 0xFu];
    }
}

Ps2Ipu::Ps2Ipu(Ps2IpuHost &host) : m_host(host)
{
    reset();
}

void Ps2Ipu::reset()
{
    m_toActive = m_toChain = m_toTagEnd = false;
    m_toKicks = m_toTags = 0;
    m_fromActive = m_fromDrainAll = false;
    m_in.clear();
    m_inPos = m_inHw = 0;
    m_underflow = false;
    m_out.clear();
    m_outHead = 0;
    m_outProduced = 0;
    m_ctrlBits = 0;
    m_ecd = m_scd = false;
    m_cbpReg = m_cmdData = m_top = 0;
    m_busy = false;
    m_stallIn = 0;
    m_curCmd = 0;
    m_lastCmdCode = 0xFu;
    std::memset(m_iq, 0, sizeof(m_iq));
    std::memset(m_niq, 0, sizeof(m_niq));
    std::memset(m_vq, 0, sizeof(m_vq));
    m_th[0] = m_th[1] = 0;
    m_dcpred[0] = m_dcpred[1] = m_dcpred[2] = 128;
    m_snap = Snapshot{};
    std::memset(m_cmdCensus, 0, sizeof(m_cmdCensus));
    m_cscDone = 0;
    m_bdecTail = m_bdecTailRun = false;
}

uint64_t Ps2Ipu::totalCommandCount() const
{
    uint64_t total = 0;
    for (uint64_t count : m_cmdCensus)
        total += count;
    return total;
}

// ---- input side -------------------------------------------------------------

size_t Ps2Ipu::qwFrom(size_t at) const
{
    const size_t total = (m_in.size() + 15u) / 16u;
    const size_t head = at / 128u;
    return total > head ? total - head : 0u;
}

// IFC saturates at the FIFO depth, as the 4-bit field does on hardware.
uint32_t Ps2Ipu::bpIfc()
{
    size_t held = heldQw();
    if (held == 0)
        return 0;
    if (held > kFifoQw + 1)
    {
        IPU_WARN_SAMPLED("%zu quadwords sit between the decode cursor and the end of the input, more than the "
                         "%zu IPU_BP can describe; the library's MADR - (IFC + FP) * 16 rewind would stop short "
                         "(pending command 0x%08x)",
                         held, kFifoQw + 1, m_busy ? m_curCmd : 0u);
    }
    held -= 1;
    return static_cast<uint32_t>(held > kFifoQw ? kFifoQw : held);
}

void Ps2Ipu::completeCh4()
{
    m_toActive = false;
    IPU_DEBUG("ch4 complete madr=0x%08x qwc=%u tadr=0x%08x after %" PRIu64 " tags, %zu qw resident",
              m_host.ipuDmaRegister(4, 1), m_host.ipuDmaRegister(4, 2), m_host.ipuDmaRegister(4, 3),
              m_toTags, heldQw());
    m_host.ipuDmaComplete(4);
}

// Runs the ch4 source (normal mode or source chain) as far as FIFO space
// allows. The DMAC walks the chain on its own; the transfer ends once the last
// tag's payload has entered the FIFO, whether or not the IPU consumed it.
void Ps2Ipu::advanceWalk()
{
    if (!m_toActive)
        return;
    // No channel advances while the DMAC is held: libmpeg reads MADR/TADR/QWC
    // back inside that window to work out how much the IPU consumed.
    if (m_host.ipuDmaSuspended())
        return;

    uint32_t &chcr = m_host.ipuDmaRegister(4, 0);
    uint32_t &madr = m_host.ipuDmaRegister(4, 1);
    uint32_t &qwc = m_host.ipuDmaRegister(4, 2);
    uint32_t &tadr = m_host.ipuDmaRegister(4, 3);

    if (!(chcr & 0x100u))
    {
        m_toActive = false; // stopped by the driver
        return;
    }
    for (;;)
    {
        if (qwc > 0)
        {
            if (walkQw() > kFifoQw)
                return; // FIFO full: the copy stalls until the decoder frees a quadword
            const uint8_t *src = m_host.ipuDmaPointer(madr, 16u);
            if (!src)
            {
                ipuLog("error", "toIPU ch4 reads unmapped guest address 0x%08x; transfer ended", madr);
                qwc = 0;
                completeCh4();
                return;
            }
            const size_t base = m_in.size();
            m_in.resize(base + 16u);
            std::memcpy(m_in.data() + base, src, 16u);
            madr += 16u;
            qwc -= 1u;
            if (qwc == 0 && (!m_toChain || m_toTagEnd))
            {
                completeCh4();
                return;
            }
            continue;
        }
        if (!m_toChain || m_toTagEnd)
        {
            completeCh4();
            return;
        }
        if (++m_toTags > 65536u)
        {
            ipuLog("error", "toIPU source chain exceeded 65536 tags in one kick; runaway TADR=0x%08x", tadr);
            completeCh4();
            return;
        }
        const uint8_t *tagPtr = m_host.ipuDmaPointer(tadr, 16u);
        if (!tagPtr)
        {
            ipuLog("error", "toIPU chain tag at unmapped guest address 0x%08x; transfer ended", tadr);
            completeCh4();
            return;
        }
        uint64_t lo;
        std::memcpy(&lo, tagPtr, 8u);
        if (lo == 0)
        {
            // An all-zero quadword is a ring slot the guest has not written
            // yet: libmpeg's ring builder never writes a tag without a payload
            // address and QWC. The walk stops with TADR on that slot, so the
            // guest's next append (which writes this slot and restarts at this
            // TADR) is still read. Consuming it as REFE would drop 2048 bytes.
            --m_toTags;
            IPU_DEBUG("ch4 chain caught up with the ring at TADR=0x%08x", tadr);
            completeCh4();
            return;
        }
        const uint32_t tagQwc = static_cast<uint32_t>(lo & 0xFFFFu);
        const uint32_t id = static_cast<uint32_t>((lo >> 28) & 7u);
        const bool irq = ((lo >> 31) & 1u) != 0;
        const uint32_t taddr = static_cast<uint32_t>((lo >> 32) & 0x7FFFFFF0u);
        const bool tspr = ((lo >> 63) & 1u) != 0;
        const bool tie = ((chcr >> 7) & 1u) != 0;
        chcr = (chcr & 0xFFFFu) | (static_cast<uint32_t>(lo >> 16) & 0xFFFF0000u);
        switch (id)
        {
        case 0: // REFE
            madr = taddr | (tspr ? 0x80000000u : 0u);
            qwc = tagQwc;
            tadr = tadr + 16u;
            m_toTagEnd = true;
            break;
        case 1: // CNT
            madr = tadr + 16u;
            qwc = tagQwc;
            tadr = tadr + 16u + tagQwc * 16u;
            break;
        case 2: // NEXT
            madr = tadr + 16u;
            qwc = tagQwc;
            tadr = taddr | (tspr ? 0x80000000u : 0u);
            break;
        case 3: // REF
        case 4: // REFS
            madr = taddr | (tspr ? 0x80000000u : 0u);
            qwc = tagQwc;
            tadr = tadr + 16u;
            break;
        case 7: // END
            madr = tadr + 16u;
            qwc = tagQwc;
            tadr = tadr + 16u + tagQwc * 16u;
            m_toTagEnd = true;
            break;
        default: // CALL/RET: ch4 has no address stack
            ipuLog("error", "toIPU chain tag id %u (CALL/RET) at 0x%08x is not supported on ch4; chain ended", id,
                   tadr);
            m_toTagEnd = true;
            qwc = 0;
            break;
        }
        if (irq && tie)
            m_toTagEnd = true;
        if (qwc == 0 && m_toTagEnd)
        {
            completeCh4();
            return;
        }
    }
}

bool Ps2Ipu::pullQword()
{
    const size_t before = m_in.size();
    advanceWalk();
    return m_in.size() > before;
}

// BCLR leaves the cursor partway into a quadword that has not arrived yet, so
// this saturates at zero.
size_t Ps2Ipu::availBits() const
{
    const size_t total = m_in.size() * 8u;
    return total > m_inPos ? total - m_inPos : 0u;
}

bool Ps2Ipu::ensureBits(size_t n)
{
    if (n > kFifoQw * 128u)
    {
        ipuLog("error", "a command asked for %zu bits at once, more than the input FIFO holds", n);
        m_underflow = true;
        return false;
    }
    while (availBits() < n)
    {
        if (!pullQword())
        {
            m_underflow = true;
            return false;
        }
    }
    return true;
}

// MSB-first peek of up to 32 bits at the cursor.
uint32_t Ps2Ipu::peekBits(unsigned n) const
{
    if (n == 0u)
        return 0u;
    const size_t byte = m_inPos >> 3;
    const unsigned shift = static_cast<unsigned>(m_inPos & 7u);
    const uint64_t mask = n == 32 ? 0xFFFFFFFFull : ((1ull << n) - 1u);
    if constexpr (std::endian::native == std::endian::little || std::endian::native == std::endian::big)
    {
        // Like PCSX2's word-based bit readers, read a resident word once.
        // memcpy permits unaligned cursors without aliasing or out-of-bounds
        // loads. Keep the zero-padded reader for the end of the input buffer.
        if (byte + sizeof(uint64_t) <= m_in.size())
        {
            uint64_t word;
            std::memcpy(&word, m_in.data() + byte, sizeof(word));
            if constexpr (std::endian::native == std::endian::little)
            {
#ifdef _MSC_VER
                word = _byteswap_uint64(word);
#else
                word = __builtin_bswap64(word);
#endif
            }
            return static_cast<uint32_t>((word >> (64u - shift - n)) & mask);
        }
    }
    uint64_t acc = 0;
    for (int i = 0; i < 6; ++i)
        acc = (acc << 8) | (byte + i < m_in.size() ? m_in[byte + i] : 0u);
    acc = (acc >> (48 - shift - n)) & mask;
    return static_cast<uint32_t>(acc);
}

void Ps2Ipu::advanceBits(size_t n)
{
    m_inPos += n;
    // The hardware position only moves forward: a retry replays bits the
    // decoder had already taken out of the FIFO.
    if (m_inPos > m_inHw)
        m_inHw = m_inPos;
}

uint32_t Ps2Ipu::getBits(unsigned n)
{
    const uint32_t v = peekBits(n);
    advanceBits(n);
    return v;
}

int32_t Ps2Ipu::getSigned(unsigned n)
{
    int32_t v = static_cast<int32_t>(peekBits(n));
    advanceBits(n);
    v = static_cast<int32_t>(static_cast<uint32_t>(v) << (32 - n));
    return v >> (32 - n);
}

// Retires whole quadwords the decoder has left behind. Callers that compact
// mid-command take a fresh snapshot afterwards.
void Ps2Ipu::compactIn()
{
    size_t drop = (m_inPos / 128u) * 16u;
    if (drop > m_in.size())
        drop = (m_in.size() / 16u) * 16u;
    if (drop == 0)
        return;
    m_in.erase(m_in.begin(), m_in.begin() + static_cast<std::ptrdiff_t>(drop));
    m_inPos -= drop * 8u;
    m_inHw = m_inHw > drop * 8u ? m_inHw - drop * 8u : 0u;
}

// ---- output side ------------------------------------------------------------

void Ps2Ipu::outPush(const void *data, size_t length)
{
    const size_t base = m_out.size();
    m_out.resize(base + length);
    std::memcpy(m_out.data() + base, data, length);
    m_outProduced += length;
}

void Ps2Ipu::completeCh3()
{
    m_fromActive = false;
    m_fromDrainAll = false;
    m_host.ipuDmaComplete(3);
}

void Ps2Ipu::drainCh3()
{
    if (!m_fromActive)
        return;
    uint32_t &chcr = m_host.ipuDmaRegister(3, 0);
    uint32_t &madr = m_host.ipuDmaRegister(3, 1);
    uint32_t &qwc = m_host.ipuDmaRegister(3, 2);
    if (!(chcr & 0x100u))
    {
        m_fromActive = false;
        m_fromDrainAll = false;
        return;
    }
    while ((qwc > 0 || m_fromDrainAll) && outAvail() >= 16u)
    {
        uint8_t *dst = m_host.ipuDmaPointer(madr, 16u);
        if (!dst)
        {
            ipuLog("error", "fromIPU ch3 writes unmapped guest address 0x%08x; transfer ended", madr);
            qwc = 0;
            completeCh3();
            return;
        }
        std::memcpy(dst, m_out.data() + m_outHead, 16u);
        m_outHead += 16u;
        madr += 16u;
        if (qwc > 0)
            qwc -= 1u;
    }
    if (m_outHead == m_out.size())
    {
        m_out.clear();
        m_outHead = 0;
    }
    if (m_fromDrainAll ? outAvail() == 0 : qwc == 0)
        completeCh3();
}

// ---- VLC decode -------------------------------------------------------------

// Peeks up to 16 bits and scans the table. Returns the index, -1 for no match
// (the caller raises ECD) or -2 for underflow. Consumes the code.
template <size_t N>
int Ps2Ipu::vlcDecode(const IpuVlc (&table)[N], int *lengthOut)
{
    if (!ensureBits(16))
    {
        // Near the end of the input fewer than 16 bits can still hold a short code.
        if (availBits() == 0)
            return -2;
        m_underflow = false;
    }
    const size_t have = availBits();
    const unsigned windowBits = static_cast<unsigned>(have < 16 ? have : 16);
    const uint32_t window = peekBits(windowBits);
    for (size_t i = 0; i < N; ++i)
    {
        if (table[i].len > windowBits)
        {
            if (table[i].len <= 16 && have < table[i].len)
            {
                m_underflow = true; // cannot rule the longer codes out yet
                return -2;
            }
            continue;
        }
        if ((window >> (windowBits - table[i].len)) == table[i].code)
        {
            advanceBits(table[i].len);
            if (lengthOut)
                *lengthOut = table[i].len;
            return static_cast<int>(i);
        }
    }
    return -1;
}

// Returns 0 ok (run/level/sign filled), 1 end of block, -1 invalid, -2 underflow.
int Ps2Ipu::dctVlcDecode(bool intraVlc, bool first, int *run, int *levelMag, bool *negative)
{
    if (!ensureBits(17))
        return -2;
    m_underflow = false;
    const uint32_t window = peekBits(17);
    if (!intraVlc && first && (window >> 16) == 1u)
    {
        // First coefficient of a non-intra block: '1s'.
        advanceBits(1);
        *run = 0;
        *levelMag = 1;
        *negative = getBits(1) != 0;
        return 0;
    }
    const DctVlc *table = intraVlc ? kDct15 : kDct14;
    const size_t count = intraVlc ? sizeof(kDct15) / sizeof(kDct15[0]) : sizeof(kDct14) / sizeof(kDct14[0]);
    for (size_t i = 0; i < count; ++i)
    {
        if ((window >> (17 - table[i].len)) != table[i].code)
            continue;
        advanceBits(table[i].len);
        if (table[i].run == 64)
            return 1;
        if (table[i].run == 65)
        {
            if (ctrlMp1())
            {
                // MPEG-1 escape (ISO 11172-2 2.4.3.7): 6-bit run, 8-bit signed
                // level; 0x00 and 0x80 extend to a second byte for |level| >= 128.
                if (!ensureBits(22))
                    return -2;
                *run = static_cast<int>(getBits(6));
                int32_t level = getSigned(8);
                if (level == 0)
                    level = static_cast<int32_t>(getBits(8));
                else if (level == -128)
                    level = static_cast<int32_t>(getBits(8)) - 256;
                if (level == 0)
                    return -1;
                *negative = level < 0;
                *levelMag = level < 0 ? -level : level;
                return 0;
            }
            // Escape: 6-bit run + 12-bit signed level (MPEG-2).
            if (!ensureBits(18))
                return -2;
            *run = static_cast<int>(getBits(6));
            const int32_t level = getSigned(12);
            if (level == 0 || level == -2048)
                return -1; // forbidden codes
            *negative = level < 0;
            *levelMag = level < 0 ? -level : level;
            return 0;
        }
        *run = table[i].run;
        *levelMag = table[i].level;
        if (!ensureBits(1))
            return -2;
        *negative = getBits(1) != 0;
        return 0;
    }
    return -1;
}

// ---- BDEC -------------------------------------------------------------------

// Decodes the AC (and for non-intra, all) coefficients of one block into
// m_dct. Returns false on underflow (m_ecd clear: rewind and retry) or on a
// bitstream error (m_ecd set: the command stops there).
bool Ps2Ipu::decodeBlockCoeffs(bool intra, int qscale, bool *anyAc)
{
    const uint8_t *scan = ctrlAs() ? kScanAlt : kScanZigzag;
    const uint8_t *weights = intra ? m_iq : m_niq;
    int index = intra ? 0 : -1;
    for (;;)
    {
        int run = 0, magnitude = 0;
        bool negative = false;
        const int r = dctVlcDecode(intra && ctrlIvf() && !ctrlMp1(), !intra && index < 0, &run, &magnitude, &negative);
        if (r == -2)
        {
            m_underflow = true;
            return false;
        }
        if (r == 1)
            return true;
        if (r == -1)
        {
            m_ecd = true;
            return false;
        }
        index = (index < 0 ? 0 : index + 1) + run;
        if (index >= 64)
            return true;
        const int j = scan[index];
        int32_t value;
        if (intra)
            value = (static_cast<int32_t>(magnitude) * qscale * weights[index]) >> 4;
        else
            value = ((2 * static_cast<int32_t>(magnitude) + 1) * qscale * weights[index]) >> 5;
        if (negative)
            value = -value;
        // MPEG-1 mismatch control: every reconstructed coefficient is odd,
        // rounded toward zero (ISO 11172-2 2.4.4.1/2.4.4.2).
        if (ctrlMp1() && value != 0 && (value & 1) == 0)
            value += value > 0 ? -1 : 1;
        saturateCoeff(&value);
        m_dct[j] = static_cast<int16_t>(value);
        if (j != 0)
            *anyAc = true;
    }
}

void Ps2Ipu::storeLumaBlock(int block, bool fieldDct, const double *px, bool intra)
{
    for (int i = 0; i < 8; ++i)
    {
        const int row = fieldDct ? ((block >> 1) + 2 * i) : ((block >> 1) * 8 + i);
        const int col = (block & 1) * 8;
        for (int x = 0; x < 8; ++x)
            m_mb16.y[row][col + x] = clampPixel(px[i * 8 + x], intra);
    }
}

void Ps2Ipu::storeChromaBlock(int16_t (*plane)[8], const double *px, bool intra)
{
    for (int i = 0; i < 8; ++i)
        for (int x = 0; x < 8; ++x)
            plane[i][x] = clampPixel(px[i * 8 + x], intra);
}

// The trailing scan is committed rather than replayed, so a stall inside it
// rewinds to the byte it reached, not to the BDEC that started it.
void Ps2Ipu::commitScan()
{
    compactIn();
    takeSnapshot();
}

// Trailing start-code scan after BDEC: if the next 8 bits are zero the stream
// aligns to a byte and zero bytes are skipped; a following 000001 sets SCD,
// other nonzero data sets ECD. Streams padded to a constant bit rate can have
// thousands of zero bytes here, far more than the FIFO holds, so every skipped
// byte commits.
bool Ps2Ipu::bdecTailScan()
{
    if (!m_bdecTailRun)
    {
        if (!ensureBits(8))
            return false;
        if (peekBits(8) == 0)
        {
            m_bdecTailRun = true;
            const size_t misalign = m_inPos & 7u;
            if (misalign)
            {
                advanceBits(8 - misalign);
                commitScan();
            }
        }
    }
    if (m_bdecTailRun)
    {
        for (;;)
        {
            if (!ensureBits(24))
                return false;
            const uint32_t startCode = peekBits(24);
            if (startCode != 0)
            {
                if (startCode == 1)
                    m_scd = true;
                else
                    m_ecd = true;
                break;
            }
            advanceBits(8);
            commitScan();
        }
    }
    if (!ensureBits(32))
        return false;
    m_top = peekBits(32);
    return true;
}

void Ps2Ipu::bdecError(const char *what)
{
    IPU_WARN_SAMPLED("BDEC: no %s code matches the bitstream at bit %zu; IPU_CTRL.ECD set, no macroblock output",
                     what, m_inPos);
}

bool Ps2Ipu::execBdec(uint32_t value)
{
    if (m_bdecTail)
        return bdecTailScan();

    const uint32_t fb = value & 0x3Fu;
    const uint32_t qsc = (value >> 16) & 0x1Fu;
    const bool dt = ((value >> 25) & 1u) != 0;
    const bool dcr = ((value >> 26) & 1u) != 0;
    const bool mbi = ((value >> 27) & 1u) != 0;

    if (!ensureBits(fb))
        return false;
    advanceBits(fb);

    if (dcr)
        m_dcpred[0] = m_dcpred[1] = m_dcpred[2] = 128 << ctrlIdp();
    const int qscale = ctrlQst() ? kNonLinearQ[qsc] : static_cast<int>(qsc << 1);
    std::memset(&m_mb16, 0, sizeof(m_mb16));

    uint32_t cbp = 0x3Fu;
    if (!mbi)
    {
        int length = 0;
        const int idx = vlcDecode(kCbp, &length);
        if (idx == -2)
        {
            m_underflow = true;
            return false;
        }
        if (idx < 0)
        {
            m_ecd = true;
            bdecError("coded_block_pattern");
            return true;
        }
        cbp = static_cast<uint32_t>(kCbp[idx].val);
    }

    double px[64];
    for (int block = 0; block < 6; ++block)
    {
        if (!(cbp & (0x20u >> block)))
            continue;
        std::memset(m_dct, 0, sizeof(m_dct));
        if (mbi)
        {
            int length = 0;
            const int idx = block < 4 ? vlcDecode(kDcLuma, &length) : vlcDecode(kDcChroma, &length);
            if (idx == -2)
            {
                m_underflow = true;
                return false;
            }
            if (idx < 0)
            {
                m_ecd = true;
                bdecError("dct_dc_size");
                return true;
            }
            const int size = block < 4 ? kDcLuma[idx].val : kDcChroma[idx].val;
            int diff = 0;
            if (size)
            {
                if (!ensureBits(static_cast<unsigned>(size)))
                    return false;
                diff = static_cast<int>(getBits(static_cast<unsigned>(size)));
                if (!(diff & (1 << (size - 1))))
                    diff -= (1 << size) - 1;
            }
            const int component = block < 4 ? 0 : (block == 4 ? 1 : 2);
            m_dcpred[component] += diff;
            m_dct[0] = static_cast<int16_t>(m_dcpred[component] << (3 - ctrlIdp()));
        }
        bool anyAc = false;
        if (!decodeBlockCoeffs(mbi, qscale, &anyAc))
        {
            if (!m_ecd)
                return false; // underflow: rewind and retry
            bdecError("DCT coefficient");
            return true;
        }
        if (anyAc)
        {
            idct8x8(m_dct, px);
        }
        else
        {
            const double c = m_dct[0] / 8.0; // DC-only block: constant dc/8
            for (double &p : px)
                p = c;
        }
        if (block < 4)
            storeLumaBlock(block, dt, px, mbi);
        else if (block == 4)
            storeChromaBlock(m_mb16.cb, px, mbi);
        else
            storeChromaBlock(m_mb16.cr, px, mbi);
    }

    m_cbpReg = cbp;
    outPush(&m_mb16, sizeof(m_mb16)); // 48 quadwords, RAW16
    // Nothing before this point can be replayed: the retry point moves here and
    // only the trailing scan remains.
    m_bdecTail = true;
    takeSnapshot();
    // ch3 drains while the command runs; libmpeg waits for OFC == 0 before its
    // DMA snapshot, and the scan below can run for thousands of bytes.
    drainCh3();
    return bdecTailScan();
}

// ---- VDEC -------------------------------------------------------------------

bool Ps2Ipu::execVdec(uint32_t value)
{
    const uint32_t fb = value & 0x3Fu;
    const uint32_t table = (value >> 26) & 3u;
    if (!ensureBits(fb))
        return false;
    advanceBits(fb);

    uint32_t result = 0;
    switch (table)
    {
    case 0:
    { // macroblock address increment
        int length = 0;
        const int idx = vlcDecode(kMbai, &length);
        if (idx == -2)
            return false;
        if (idx >= 0)
        {
            if (kMbai[idx].val == 0x22 && !ctrlMp1())
                result = 0; // stuffing is MPEG1-only
            else
                result = static_cast<uint32_t>(kMbai[idx].val) | (static_cast<uint32_t>(length) << 16);
        }
        break;
    }
    case 1:
    { // macroblock type, table selected by CTRL.PCT
        const int pct = ctrlPct() ? ctrlPct() : 1;
        int length = 0;
        if (pct == 1)
        {
            const int idx = vlcDecode(kMbtI, &length);
            if (idx == -2)
                return false;
            if (idx >= 0)
                result = static_cast<uint32_t>(kMbtI[idx].val);
        }
        else if (pct == 2)
        {
            const int idx = vlcDecode(kMbtP, &length);
            if (idx == -2)
                return false;
            if (idx >= 0)
            {
                uint32_t modes = static_cast<uint32_t>(kMbtP[idx].val);
                // The IPU decodes as frame_pred_frame_dct: motion type is frame MC.
                if (modes & MB_FORWARD)
                    modes |= MB_MC_FRAME;
                result = modes;
            }
        }
        else if (pct == 3)
        {
            const int idx = vlcDecode(kMbtB, &length);
            if (idx == -2)
                return false;
            if (idx >= 0)
                result = static_cast<uint32_t>(kMbtB[idx].val) | MB_MC_FRAME | (static_cast<uint32_t>(length) << 16);
        }
        else
        {
            IPU_WARN_SAMPLED("VDEC macroblock type with PCT=%d (D picture?); returning error", pct);
        }
        break;
    }
    case 2:
    { // motion code
        if (!ensureBits(1))
            return false;
        if (peekBits(1) == 1)
        {
            advanceBits(1);
            result = 0x00010000u; // value 0, length 1
        }
        else
        {
            int length = 0;
            const int idx = vlcDecode(kMotion, &length);
            if (idx == -2)
                return false;
            if (idx > 0)
            {
                const int32_t magnitude = kMotion[idx].val;
                if (!ensureBits(1))
                    return false;
                const int32_t sign = getBits(1) ? -1 : 0;
                const int32_t v = (magnitude ^ sign) - sign;
                result = (static_cast<uint32_t>(v) & 0xFFFFu) | (static_cast<uint32_t>(length) << 16);
            }
        }
        break;
    }
    default:
    { // dmvector
        int length = 0;
        const int idx = vlcDecode(kDmv, &length);
        if (idx == -2)
            return false;
        if (idx >= 0)
            result = (static_cast<uint32_t>(static_cast<int32_t>(kDmv[idx].val)) & 0xFFFFu) |
                     (static_cast<uint32_t>(length) << 16);
        break;
    }
    }

    m_cmdData = result;
    m_ecd = (result == 0);
    if (!ensureBits(32))
        return false;
    m_top = peekBits(32);
    return true;
}

// ---- CSC --------------------------------------------------------------------

// Integer BT.601 conversion documented for the IPU: Y 0x95, R/Cr 0xCC,
// G/Cr -0x68, G/Cb -0x32, B/Cb 0x102, biases 16 (Y) and 128 (C), >>6 then a
// rounded >>1. Alpha is 0x80 before thresholding.
void Ps2Ipu::cscOneMacroblock(const MacroBlock8 &mb, uint8_t *rgbaOut)
{
#if defined(__SSE4_1__)
    static const bool scalar = [] {
        const char *value = std::getenv("PS2X_IPU_CSC_SCALAR");
        return value && *value == '1';
    }();
    if (!scalar)
    {
        // Four pixels retain the scalar integer coefficients, arithmetic
        // shifts and threshold order. No floating-point approximation.
        const __m128i zero = _mm_setzero_si128();
        const __m128i one = _mm_set1_epi32(1);
        const __m128i maximum = _mm_set1_epi32(255);
        const auto bytes = [&](const __m128i values) {
            return _mm_packus_epi16(_mm_packs_epi32(values, values), zero);
        };
        for (int yy = 0; yy < 16; ++yy)
        {
            for (int xx = 0; xx < 16; xx += 4)
            {
                uint32_t ys;
                uint16_t cbs, crs;
                std::memcpy(&ys, &mb.y[yy][xx], sizeof(ys));
                std::memcpy(&cbs, &mb.cb[yy >> 1][xx >> 1], sizeof(cbs));
                std::memcpy(&crs, &mb.cr[yy >> 1][xx >> 1], sizeof(crs));
                const __m128i y = _mm_max_epi32(zero, _mm_sub_epi32(
                    _mm_cvtepu8_epi32(_mm_cvtsi32_si128(ys)), _mm_set1_epi32(16)));
                const __m128i cbPair = _mm_cvtepu8_epi32(_mm_cvtsi32_si128(cbs));
                const __m128i crPair = _mm_cvtepu8_epi32(_mm_cvtsi32_si128(crs));
                const __m128i cb = _mm_sub_epi32(_mm_shuffle_epi32(cbPair, _MM_SHUFFLE(1, 1, 0, 0)), _mm_set1_epi32(128));
                const __m128i cr = _mm_sub_epi32(_mm_shuffle_epi32(crPair, _MM_SHUFFLE(1, 1, 0, 0)), _mm_set1_epi32(128));
                const __m128i lum = _mm_srli_epi32(_mm_mullo_epi32(y, _mm_set1_epi32(149)), 6);
                __m128i r = _mm_srai_epi32(_mm_add_epi32(one, _mm_add_epi32(lum,
                    _mm_srai_epi32(_mm_mullo_epi32(cr, _mm_set1_epi32(204)), 6))), 1);
                __m128i g = _mm_srai_epi32(_mm_add_epi32(one, _mm_add_epi32(lum,
                    _mm_add_epi32(_mm_srai_epi32(_mm_mullo_epi32(cr, _mm_set1_epi32(-104)), 6),
                                  _mm_srai_epi32(_mm_mullo_epi32(cb, _mm_set1_epi32(-50)), 6)))), 1);
                __m128i b = _mm_srai_epi32(_mm_add_epi32(one, _mm_add_epi32(lum,
                    _mm_srai_epi32(_mm_mullo_epi32(cb, _mm_set1_epi32(258)), 6))), 1);
                r = _mm_min_epi32(maximum, _mm_max_epi32(zero, r));
                g = _mm_min_epi32(maximum, _mm_max_epi32(zero, g));
                b = _mm_min_epi32(maximum, _mm_max_epi32(zero, b));
                const auto below = [&](int threshold) {
                    const __m128i limit = _mm_set1_epi32(threshold);
                    return _mm_and_si128(_mm_cmplt_epi32(r, limit),
                        _mm_and_si128(_mm_cmplt_epi32(g, limit), _mm_cmplt_epi32(b, limit)));
                };
                // A zero threshold naturally produces an empty mask because
                // RGB has already been clamped to nonnegative values.
                const __m128i transparent = below(m_th[0]);
                __m128i alpha = _mm_blendv_epi8(_mm_set1_epi32(128), _mm_set1_epi32(64), below(m_th[1]));
                alpha = _mm_andnot_si128(transparent, alpha);
                r = _mm_andnot_si128(transparent, r);
                g = _mm_andnot_si128(transparent, g);
                b = _mm_andnot_si128(transparent, b);
                const __m128i rg = _mm_unpacklo_epi8(bytes(r), bytes(g));
                const __m128i ba = _mm_unpacklo_epi8(bytes(b), bytes(alpha));
                _mm_storeu_si128(reinterpret_cast<__m128i *>(rgbaOut + (yy * 16 + xx) * 4),
                                _mm_unpacklo_epi16(rg, ba));
            }
        }
        return;
    }
#endif
    for (int yy = 0; yy < 16; ++yy)
    {
        for (int xx = 0; xx < 16; ++xx)
        {
            int ylev = mb.y[yy][xx] - 16;
            if (ylev < 0)
                ylev = 0;
            const int lum = (0x95 * ylev) >> 6;
            const int cr = mb.cr[yy >> 1][xx >> 1] - 128;
            const int cb = mb.cb[yy >> 1][xx >> 1] - 128;
            int r = (lum + ((0xCC * cr) >> 6) + 1) >> 1;
            int g = (lum + ((-0x68 * cr) >> 6) + ((-0x32 * cb) >> 6) + 1) >> 1;
            int b = (lum + ((0x102 * cb) >> 6) + 1) >> 1;
            r = r < 0 ? 0 : (r > 255 ? 255 : r);
            g = g < 0 ? 0 : (g > 255 ? 255 : g);
            b = b < 0 ? 0 : (b > 255 ? 255 : b);
            int a = 0x80;
            if (m_th[0] > 0 && r < m_th[0] && g < m_th[0] && b < m_th[0])
            {
                r = g = b = a = 0;
            }
            else if (m_th[1] > 0 && r < m_th[1] && g < m_th[1] && b < m_th[1])
            {
                a = 0x40;
            }
            uint8_t *p = rgbaOut + (yy * 16 + xx) * 4;
            p[0] = static_cast<uint8_t>(r);
            p[1] = static_cast<uint8_t>(g);
            p[2] = static_cast<uint8_t>(b);
            p[3] = static_cast<uint8_t>(a);
        }
    }
}

// CSC input (a whole frame of RAW8, 24 quadwords per macroblock) dwarfs the
// FIFO, so each converted macroblock commits and a stall resumes from there.
bool Ps2Ipu::execCsc(uint32_t value)
{
    // Diagnostic A/B switch: retain the bit reader for measuring the old path
    // with the same executable and input. Configured once before startup.
    static const bool useBitReader = std::getenv("PS2X_IPU_CSC_BIT_READER") != nullptr;
    const uint32_t mbc = value & 0x7FFu;
    const bool ofm = ((value >> 27) & 1u) != 0; // 1 = RGB16
    MacroBlock8 mb;
    uint8_t rgba[1024];
    for (; m_cscDone < mbc; ++m_cscDone)
    {
        if (!useBitReader && (m_inPos & 7u) == 0u)
        {
            // CSC consumes bytes rather than VLC codes. Copy the resident
            // bytes together, retaining the same FIFO refill and rollback
            // boundaries as the bit reader when input runs out mid-block.
            size_t copied = 0;
            while (copied < sizeof(mb))
            {
                if (!ensureBits(8))
                    return false;
                const size_t available = availBits() / 8u;
                const size_t length = std::min(available, sizeof(mb) - copied);
                std::memcpy(reinterpret_cast<uint8_t *>(&mb) + copied,
                            m_in.data() + m_inPos / 8u, length);
                advanceBits(length * 8u);
                copied += length;
            }
        }
        else
        {
            // BCLR can leave a non-byte-aligned cursor. Keep the bit reader
            // for that case; a byte copy would silently change the image.
            for (size_t i = 0; i < sizeof(mb); ++i)
            {
                if (!ensureBits(8))
                    return false;
                reinterpret_cast<uint8_t *>(&mb)[i] = static_cast<uint8_t>(getBits(8));
            }
        }
        cscOneMacroblock(mb, rgba);
        if (ofm)
        {
            // RGB16: 5:5:5 with the alpha bit set unless thresholding cleared it.
            // DTE dithering (bit 26) is not modeled.
            uint16_t rgb16[256];
            for (int i = 0; i < 256; ++i)
            {
                const uint8_t *p = rgba + i * 4;
                rgb16[i] = static_cast<uint16_t>((p[0] >> 3) | ((p[1] >> 3) << 5) | ((p[2] >> 3) << 10) |
                                                 (p[3] ? 0x8000u : 0u));
            }
            outPush(rgb16, sizeof(rgb16));
        }
        else
        {
            outPush(rgba, sizeof(rgba));
        }
        takeSnapshot();
        drainCh3();
    }
    return true;
}

// ---- SETIQ / SETVQ / BCLR / reset -------------------------------------------

bool Ps2Ipu::execSetiq(uint32_t value)
{
    const uint32_t fb = value & 0x3Fu;
    const bool nonIntra = ((value >> 27) & 1u) != 0;
    if (!ensureBits(fb))
        return false;
    advanceBits(fb);
    if (!ensureBits(64 * 8))
        return false;
    uint8_t *dst = nonIntra ? m_niq : m_iq;
    for (int i = 0; i < 64; ++i)
        dst[i] = static_cast<uint8_t>(getBits(8));
    return true;
}

bool Ps2Ipu::execSetvq()
{
    if (!ensureBits(32 * 8))
        return false;
    for (int i = 0; i < 32; ++i)
        m_vq[i] = static_cast<uint8_t>(getBits(8));
    return true;
}

// BCLR discards the input FIFO and sets the bit position. libmpeg restarts
// ch4 at the quadword the decoder was inside and issues this with the saved
// BP, so everything resident has to go: the same bytes are about to arrive
// again. A pending command survives and its retry point is rebased onto BP.
void Ps2Ipu::execBclr(uint32_t value)
{
    const uint32_t bp = value & 0x7Fu;
    IPU_DEBUG("BCLR bp=%u: dropping %zu resident qw, pending 0x%08x", bp, heldQw(), m_busy ? m_curCmd : 0u);
    m_in.clear();
    m_inPos = bp;
    m_inHw = bp;
    if (m_busy)
    {
        m_snap.inPos = bp;
        m_stallIn = 0;
    }
    m_underflow = false;
}

void Ps2Ipu::softReset()
{
    m_in.clear();
    m_inPos = m_inHw = 0;
    m_out.clear();
    m_outHead = 0;
    m_outProduced = 0;
    m_cbpReg = 0;
    m_th[0] = m_th[1] = 0;
    m_ecd = m_scd = false;
    m_busy = false;
    m_bdecTail = m_bdecTailRun = false;
    m_top = 0;
    m_cmdData = 0;
    m_underflow = false;
    m_toActive = false;
    m_fromActive = false;
    m_fromDrainAll = false;
    // Keeps the IQ/VQ matrices and the CTRL picture bits; the DC predictors are
    // reinitialised only at 8-bit precision.
    if (ctrlIdp() == 0)
        m_dcpred[0] = m_dcpred[1] = m_dcpred[2] = 128;
    m_host.ipuRaiseInterrupt();
    IPU_DEBUG("soft reset (IPU_CTRL.RST)");
}

// ---- command dispatch / retry -----------------------------------------------

void Ps2Ipu::takeSnapshot()
{
    m_snap.inPos = m_inPos;
    m_snap.outProduced = m_outProduced;
    std::memcpy(m_snap.dcpred, m_dcpred, sizeof(m_dcpred));
    m_snap.cbp = m_cbpReg;
}

void Ps2Ipu::restoreSnapshot()
{
    m_inPos = m_snap.inPos; // m_inHw deliberately kept
    if (m_outProduced != m_snap.outProduced)
    {
        const uint64_t drop = m_outProduced - m_snap.outProduced;
        if (drop > static_cast<uint64_t>(outAvail()))
        {
            ipuLog("error", "a stalled command has to take back %" PRIu64 " output bytes but only %zu are queued",
                   drop, outAvail());
        }
        else
        {
            m_out.resize(m_out.size() - static_cast<size_t>(drop));
        }
        m_outProduced = m_snap.outProduced;
    }
    std::memcpy(m_dcpred, m_snap.dcpred, sizeof(m_dcpred));
    m_cbpReg = m_snap.cbp;
}

void Ps2Ipu::finishWithError(const char *why, uint32_t value)
{
    IPU_WARN_SAMPLED("%s 0x%08x: %s; the command ends with IPU_CTRL.ECD set", commandName(value >> 28), value, why);
    m_busy = false;
    m_ecd = true;
    m_host.ipuRaiseInterrupt();
}

void Ps2Ipu::runPending()
{
    if (!m_busy)
        return;
    restoreSnapshot();
    m_underflow = false;
    m_ecd = false;
    m_scd = false;

    const uint32_t value = m_curCmd;
    bool done = false;
    switch (value >> 28)
    {
    case 2:
        done = execBdec(value);
        break;
    case 3:
        done = execVdec(value);
        break;
    case 4:
    { // FDEC: skip FB, then the next 32 bits without advancing
        const uint32_t fb = value & 0x3Fu;
        if (!ensureBits(fb))
            break;
        advanceBits(fb);
        if (!ensureBits(32))
            break;
        m_cmdData = peekBits(32);
        m_top = m_cmdData;
        done = true;
        break;
    }
    case 5:
        done = execSetiq(value);
        break;
    case 6:
        done = execSetvq();
        break;
    case 7:
        done = execCsc(value);
        break;
    default:
        finishWithError("unreachable pending command", value);
        return;
    }

    if (!done)
    {
        // Underflow: rewind and wait. The attempt still moved the hardware
        // position, so walk again to use the FIFO space it freed.
        restoreSnapshot();
        advanceWalk();
        m_stallIn = m_in.size();
        IPU_DEBUG("command 0x%08x stalls on input (%zu bits available)", value, availBits());
        return;
    }

    m_busy = false;
    compactIn();
    advanceWalk();
    m_host.ipuRaiseInterrupt();
    drainCh3();
}

// Hardware runs the DMA and the decoder alongside the guest; the model
// advances both whenever the guest could observe them.
void Ps2Ipu::serviceInput()
{
    advanceWalk();
    // With the same input a retry would take the same path, so only replay a
    // stalled command when the fill delivered something.
    if (m_busy && m_in.size() == m_stallIn)
        return;
    runPending();
}

void Ps2Ipu::commandWrite(uint32_t value)
{
    const uint32_t code = value >> 28;
    ++m_cmdCensus[code];
    m_debugCommands.fetch_add(1, std::memory_order_relaxed);
    m_debugLastCommand.store(value, std::memory_order_relaxed);
    if (censusEnabled() && isPow2(m_cmdCensus[code]))
    {
        ipuLog("census", "%s 0x%08x #%" PRIu64 " (bp=%u ifc=%u, %zu bits available)", commandName(code), value,
               m_cmdCensus[code], bpBp(), bpIfc(), availBits());
    }
    IPU_DEBUG("%s 0x%08x [#%" PRIu64 "] bp=%u ifc=%u avail=%zu", commandName(code), value, m_cmdCensus[code],
              bpBp(), bpIfc(), availBits());
    if (m_busy && code != 0)
    {
        // libmpeg polls BUSY before every command but BCLR (which it issues
        // under a pending command on purpose).
        IPU_WARN_SAMPLED("command 0x%08x written while 0x%08x is still pending; previous dropped", value, m_curCmd);
        m_busy = false;
        m_inHw = m_inPos;
    }
    m_ecd = false;
    m_scd = false;
    m_lastCmdCode = code;

    switch (code)
    {
    case 0: // BCLR: immediate
        execBclr(value);
        m_host.ipuRaiseInterrupt();
        return;
    case 9: // SETTH: immediate
        m_th[0] = static_cast<uint16_t>(value & 0x1FFu);
        m_th[1] = static_cast<uint16_t>((value >> 16) & 0x1FFu);
        m_host.ipuRaiseInterrupt();
        return;
    case 1:
        finishWithError("IDEC is not modeled (libmpeg decodes with BDEC)", value);
        return;
    case 8:
        finishWithError("PACK is not modeled", value);
        return;
    case 2:
    case 3:
    case 4:
    case 5:
    case 6:
    case 7:
        m_curCmd = value;
        m_busy = true;
        m_cscDone = 0;
        m_bdecTail = false;
        m_bdecTailRun = false;
        takeSnapshot();
        runPending();
        return;
    default:
        finishWithError("unknown IPU command", value);
        return;
    }
}

// ---- DMA bridge ---------------------------------------------------------------

void Ps2Ipu::dmaKick(int channel)
{
    if (channel == 4)
    {
        ++m_toKicks;
        const uint32_t chcr = m_host.ipuDmaRegister(4, 0);
        const uint32_t mode = (chcr >> 2) & 3u;
        if (mode == 2)
        {
            ipuLog("error", "toIPU ch4 kicked in interleave mode (chcr=0x%08x); treated as normal mode", chcr);
        }
        m_toActive = true;
        m_toChain = (mode == 1);
        // A kick moves whatever QWC is outstanding and then reads the tag at
        // TADR; it does not end on the tag id left in CHCR bits 28-31.
        // libmpeg's restarts hand back a CHCR whose TAG field its own stop
        // (CHCR = 5) zeroed, so ending there would stop the channel after the
        // outstanding QWC on every restart.
        m_toTagEnd = false;
        m_toTags = 0;
        IPU_DEBUG("ch4 kick #%" PRIu64 " %s chcr=0x%08x madr=0x%08x qwc=%u tadr=0x%08x, %zu qw resident",
                  m_toKicks, m_toChain ? "chain" : "normal", chcr, m_host.ipuDmaRegister(4, 1),
                  m_host.ipuDmaRegister(4, 2), m_host.ipuDmaRegister(4, 3), heldQw());
        if (!m_toChain && m_host.ipuDmaRegister(4, 2) == 0)
        {
            completeCh4();
            return;
        }
        advanceWalk();
        runPending();
        drainCh3();
        return;
    }
    if (channel == 3)
    {
        m_fromActive = true;
        m_fromDrainAll = (m_host.ipuDmaRegister(3, 2) == 0);
        IPU_DEBUG("ch3 kick madr=0x%08x qwc=%u (out has %zu qw)", m_host.ipuDmaRegister(3, 1),
                  m_host.ipuDmaRegister(3, 2), outAvail() / 16u);
        drainCh3();
    }
}

// CHCR written with STR clear: the transfer stops where it is. The registers
// are left alone (libmpeg reads them back immediately), the FIFO keeps what it
// holds, and no completion is raised because nothing completed.
void Ps2Ipu::dmaStop(int channel)
{
    if (channel == 4)
    {
        if (m_toActive)
            IPU_DEBUG("ch4 stopped at madr=0x%08x qwc=%u tadr=0x%08x, %zu qw resident",
                      m_host.ipuDmaRegister(4, 1), m_host.ipuDmaRegister(4, 2), m_host.ipuDmaRegister(4, 3),
                      heldQw());
        m_toActive = false;
        return;
    }
    if (channel == 3)
    {
        m_fromActive = false;
        m_fromDrainAll = false;
    }
}

void Ps2Ipu::dmaResume()
{
    if (!m_toActive && !m_fromActive)
        return;
    advanceWalk();
    runPending();
    drainCh3();
}

// ---- MMIO ---------------------------------------------------------------------

bool Ps2Ipu::readRegister64(uint32_t address, uint64_t &value)
{
    switch (address & ~0x7u)
    {
    case 0x10002000u:
    { // IPU_CMD: result DATA, BUSY in bit 63
        serviceInput();
        uint32_t data = m_cmdData;
        if (m_lastCmdCode != 3u && m_lastCmdCode != 4u)
        {
            // After commands other than VDEC/FDEC the register shows a live
            // 32-bit peek of the bitstream.
            const bool saved = m_underflow;
            if (ensureBits(32))
                data = peekBits(32);
            m_underflow = saved;
        }
        value = static_cast<uint64_t>(data) | (m_busy ? (1ull << 63) : 0u);
        return true;
    }
    case 0x10002010u:
    { // IPU_CTRL
        serviceInput();
        const uint32_t ifc = bpIfc();
        uint32_t ofc = static_cast<uint32_t>(outAvail() / 16u);
        if (ofc > 8u)
            ofc = 8u;
        value = ifc | (ofc << 4) | ((m_cbpReg & 0x3Fu) << 8) | (m_ecd ? 1u << 14 : 0u) | (m_scd ? 1u << 15 : 0u) |
                (m_ctrlBits & 0x07F30000u) | (m_busy ? 1u << 31 : 0u);
        return true;
    }
    case 0x10002020u:
    { // IPU_BP: BP bits 0-6, IFC bits 8-11, FP bits 16-17
        serviceInput();
        value = bpBp() | (bpIfc() << 8) | (bpFp() << 16);
        return true;
    }
    case 0x10002030u:
    { // IPU_TOP: next 32 bits, BUSY in bit 63
        serviceInput();
        value = static_cast<uint64_t>(m_top) | (m_busy ? (1ull << 63) : 0u);
        return true;
    }
    default:
        return false;
    }
}

bool Ps2Ipu::writeRegister(uint32_t address, uint64_t value)
{
    switch (address)
    {
    case 0x10002000u: // IPU_CMD
        commandWrite(static_cast<uint32_t>(value));
        return true;
    case 0x10002010u:
    { // IPU_CTRL: bits 16-26 stored (18-19 reserved), RST acts
        const uint32_t v = static_cast<uint32_t>(value);
        m_ctrlBits = v & 0x07F30000u;
        if (((m_ctrlBits >> 16) & 3u) == 3u)
        {
            IPU_WARN_SAMPLED("IPU_CTRL.IDP=3 is reserved; treating as 9-bit precision");
            m_ctrlBits = (m_ctrlBits & ~0x30000u) | 0x10000u;
        }
        if (v & 0x40000000u)
            softReset();
        return true;
    }
    case 0x10002004u:
    case 0x10002014u:
    case 0x10002024u:
    case 0x10002034u:
        return true; // upper halves of 64-bit registers
    case 0x10002020u:
    case 0x10002030u:
        IPU_WARN_SAMPLED("write to read-only IPU register 0x%08x = 0x%llx ignored", address,
                         static_cast<unsigned long long>(value));
        return true;
    default:
        return address >= 0x10002000u && address < 0x10002040u;
    }
}

void Ps2Ipu::writeInputFifo(const uint8_t *qw16)
{
    // Hardware stalls the store until there is room. Give the pending command
    // a chance to drain first; if the FIFO is still full the store is accepted
    // anyway, because dropping guest data would be worse.
    if (walkQw() > kFifoQw)
        runPending();
    if (walkQw() > kFifoQw)
        IPU_WARN_SAMPLED("toIPU FIFO store with the input FIFO already full (%zu qw)", walkQw());
    const size_t base = m_in.size();
    m_in.resize(base + 16u);
    std::memcpy(m_in.data() + base, qw16, 16u);
    runPending();
}

void Ps2Ipu::readOutputFifo(uint8_t *qw16)
{
    serviceInput();
    if (outAvail() < 16u)
    {
        IPU_WARN_SAMPLED("fromIPU FIFO read with %zu bytes queued; returns zeros", outAvail());
        std::memset(qw16, 0, 16u);
        return;
    }
    std::memcpy(qw16, m_out.data() + m_outHead, 16u);
    m_outHead += 16u;
    if (m_outHead == m_out.size())
    {
        m_out.clear();
        m_outHead = 0;
    }
}

// ---- test hooks ---------------------------------------------------------------

void Ps2Ipu::testFeed(const uint8_t *data, size_t length)
{
    const size_t base = m_in.size();
    m_in.resize(base + length);
    std::memcpy(m_in.data() + base, data, length);
}

size_t Ps2Ipu::testReadOutput(uint8_t *dst, size_t maxLength)
{
    size_t n = outAvail();
    if (n > maxLength)
        n = maxLength;
    std::memcpy(dst, m_out.data() + m_outHead, n);
    m_outHead += n;
    if (m_outHead == m_out.size())
    {
        m_out.clear();
        m_outHead = 0;
    }
    return n;
}

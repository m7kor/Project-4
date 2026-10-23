#include "MiniTest.h"
#include "runtime/ps2_memory.h"
#include "runtime/ps2_ipu.h"
#include "../../ps2xRuntime/src/lib/ipu_round_pixel.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>
#include <limits>
#include <cstring>
#include <vector>

// Register-level tests for the IPU model behind PS2Memory. Expected values
// are computed by hand from the MPEG-2 code tables and the register layout,
// so a regression in the bit accounting shows up as a wrong number here.

namespace
{
    constexpr uint32_t IPU_CMD = 0x10002000u;
    constexpr uint32_t IPU_CTRL = 0x10002010u;
    constexpr uint32_t IPU_BP = 0x10002020u;
    constexpr uint32_t IPU_TOP = 0x10002030u;
    constexpr uint32_t IPU_IN_FIFO = 0x10007010u;
    constexpr uint32_t D3_CHCR = 0x1000B000u, D3_MADR = 0x1000B010u, D3_QWC = 0x1000B020u;
    constexpr uint32_t D4_CHCR = 0x1000B400u, D4_MADR = 0x1000B410u, D4_QWC = 0x1000B420u, D4_TADR = 0x1000B430u;
    constexpr uint32_t D_STAT = 0x1000E010u;
    constexpr uint32_t D_ENABLEW = 0x1000F590u, D_ENABLER = 0x1000F520u;

    void pushQword(PS2Memory &mem, const uint8_t *bytes)
    {
        __m128i v;
        std::memcpy(&v, bytes, 16);
        mem.write128(IPU_IN_FIFO, v);
    }

    // Packs a string of '0'/'1' into bytes, MSB first, zero padded.
    std::vector<uint8_t> packBits(const char *bits, size_t padTo)
    {
        std::vector<uint8_t> out(padTo, 0u);
        for (size_t i = 0; bits[i]; ++i)
        {
            if (bits[i] == '1')
                out[i / 8] |= static_cast<uint8_t>(0x80u >> (i % 8));
        }
        return out;
    }

    bool busy(PS2Memory &mem) { return (mem.read64(IPU_CMD) >> 63) != 0u; }
}

void register_ps2_ipu_tests()
{
    MiniTest::Case("PS2Ipu", [](TestCase &tc)
    {
        tc.Run("IPU pixel rounding matches lround at half boundaries and saturation", [](TestCase &t)
        {
            for (bool intra : {false, true})
                for (int whole = -4096; whole <= 4096; ++whole)
                    for (double fraction : {-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75})
                    {
                        const double center = whole + fraction;
                        for (double value : {center,
                             std::nextafter(center, -std::numeric_limits<double>::max()),
                             std::nextafter(center, std::numeric_limits<double>::max())})
                        {
                            const long rounded = std::lround(value);
                            const auto expected = static_cast<int16_t>(std::clamp(rounded, intra ? 0l : -256l, 255l));
                            t.Equals(ps2x::ipu::roundPixel(value, intra), expected,
                                     "finite pixel output matches the independent standard-library reference");
                        }
                    }
        });
        tc.Run("FDEC word reads preserve every cursor and input-tail retry", [](TestCase &t)
        {
            struct Host final : Ps2IpuHost {
                uint32_t regs[2][4]{};
                uint8_t *ipuDmaPointer(uint32_t, uint32_t) override { return nullptr; }
                uint32_t &ipuDmaRegister(int c, int r) override { return regs[c == 4][r & 3]; }
                void ipuDmaComplete(int) override {}
                bool ipuDmaSuspended() override { return false; }
                void ipuRaiseInterrupt() override {}
            } host;
            std::array<uint8_t, 32> input;
            for (size_t i = 0; i < input.size(); ++i) input[i] = static_cast<uint8_t>(i * 73u + 29u);
            for (unsigned offset = 0; offset < 128; ++offset)
                for (unsigned skip : {0u, 1u, 63u})
                    for (size_t initial : {4u, 5u, 7u, 8u, 16u, 32u}) {
                        Ps2Ipu ipu(host);
                        ipu.writeRegister(IPU_CMD, offset);
                        ipu.testFeed(input.data(), initial);
                        ipu.writeRegister(IPU_CMD, 0x40000000u | skip);
                        t.Equals(ipu.busy(), offset + skip + 32u > initial * 8u, "FDEC stalls only when required bits are missing");
                        if (initial < input.size()) ipu.testFeed(input.data() + initial, input.size() - initial);
                        uint64_t observed = 0;
                        ipu.readRegister64(IPU_CMD, observed);
                        uint32_t expected = 0;
                        for (unsigned bit = offset + skip; bit < offset + skip + 32u; ++bit)
                            expected = (expected << 1u) | ((input[bit / 8u] >> (7u - bit % 8u)) & 1u);
                        t.IsFalse(ipu.busy(), "additional input completes the read");
                        t.Equals(static_cast<uint32_t>(observed), expected, "all 32 bits match the independent bit-at-a-time reference");
                        ipu.readRegister64(IPU_TOP, observed);
                        t.Equals(static_cast<uint32_t>(observed), expected, "IPU_TOP keeps the same peek");
                    }
        });
        tc.Run("CSC preserves pixels across byte alignment and partial input retries", [](TestCase &t)
        {
            struct Host final : Ps2IpuHost {
                uint32_t regs[2][4]{};
                uint8_t *ipuDmaPointer(uint32_t, uint32_t) override { return nullptr; }
                uint32_t &ipuDmaRegister(int c, int r) override { return regs[c == 4][r & 3]; }
                void ipuDmaComplete(int) override {}
                bool ipuDmaSuspended() override { return false; }
                void ipuRaiseInterrupt() override {}
            } host;
            const unsigned offsets[] = {0, 1, 7, 8, 120, 127};
            const unsigned thresholds[][2] = {{0, 0}, {20, 90}, {200, 100}, {256, 511}};
            for (unsigned pattern = 0; pattern < 16; ++pattern) {
            std::array<uint8_t, 768> raw;
            uint32_t random = 0x12345678u ^ (pattern * 2654435761u);
            for (auto &byte : raw) {
                random = random * 1664525u + 1013904223u;
                const uint8_t edges[] = {0, 16, 128, 255};
                byte = pattern < 4 ? edges[pattern] : static_cast<uint8_t>(random >> 24);
            }
            for (unsigned offset : offsets) for (const auto &th : thresholds) for (unsigned rgb16 = 0; rgb16 < 2; ++rgb16) {
                Ps2Ipu ipu(host);
                ipu.writeRegister(IPU_CMD, 0x90000000u | th[0] | (th[1] << 16));
                ipu.writeRegister(IPU_CMD, offset); // BCLR bit cursor, including non-byte alignment.
                ipu.writeRegister(IPU_CMD, 0x70000002u | (rgb16 << 27));
                std::vector<uint8_t> input(((offset + raw.size() * 8u + 127u) / 128u) * 16u);
                for (size_t bit = 0; bit < raw.size() * 8u; ++bit)
                    if (raw[bit / 8u] & (0x80u >> (bit % 8u)))
                        input[(offset + bit) / 8u] |= static_cast<uint8_t>(0x80u >> ((offset + bit) % 8u));
                uint64_t command = 0;
                for (size_t at = 0; at < input.size(); at += 16u) {
                    ipu.testFeed(input.data() + at, 16u);
                    ipu.readRegister64(IPU_CMD, command);
                }
                t.IsFalse(ipu.busy(), "partial input completes both macroblocks");
                std::array<uint8_t, 2048> output{};
                const size_t bytes = 2u * 256u * (rgb16 ? 2u : 4u);
                t.Equals(ipu.testReadOutput(output.data(), output.size()), bytes, "no duplicate output after retries");
                bool matches = true;
                for (size_t block = 0; block < 2; ++block) for (size_t y = 0; y < 16; ++y) for (size_t x = 0; x < 16; ++x) {
                    const uint8_t *mb = raw.data() + block * 384u;
                    const int cb = int(mb[256u + (y / 2u) * 8u + x / 2u]) - 128;
                    const int cr = int(mb[320u + (y / 2u) * 8u + x / 2u]) - 128;
                    const int lum = (149 * std::max(0, int(mb[y * 16u + x]) - 16)) >> 6;
                    int r = std::clamp((lum + ((204 * cr) >> 6) + 1) >> 1, 0, 255);
                    int g = std::clamp((lum + ((-104 * cr) >> 6) + ((-50 * cb) >> 6) + 1) >> 1, 0, 255);
                    int b = std::clamp((lum + ((258 * cb) >> 6) + 1) >> 1, 0, 255);
                    int a = 128;
                    if (th[0] && r < int(th[0]) && g < int(th[0]) && b < int(th[0])) r = g = b = a = 0;
                    else if (th[1] && r < int(th[1]) && g < int(th[1]) && b < int(th[1])) a = 64;
                    const size_t pixel = block * 256u + y * 16u + x;
                    if (rgb16) {
                        uint16_t observed;
                        std::memcpy(&observed, output.data() + pixel * 2u, 2u);
                        matches &= observed == uint16_t((r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10) | (a ? 0x8000u : 0u));
                    } else {
                        const auto *p = output.data() + pixel * 4u;
                        matches &= p[0] == r && p[1] == g && p[2] == b && p[3] == a;
                    }
                }
                t.IsTrue(matches, "CSC pixel bytes match the scalar reference at every alignment and threshold");
            }
            }
        });
        tc.Run("BDEC decodes a DC-only intra macroblock and ch3 delivers it", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "PS2Memory initialize should succeed");
            // IDP=0 (8-bit DC), IVF=1 (table B-15), PCT=1 (I picture).
            mem.write32(IPU_CTRL, (1u << 21) | (1u << 24));

            // Luma: dct_dc_size_luminance 0 = '100', EOB (B-15) = '0110'.
            // Chroma: dct_dc_size_chrominance 0 = '00', EOB = '0110'.
            // 40 bits, byte aligned, then a sequence end start code.
            std::vector<uint8_t> stream = packBits(
                "1000110" "1000110" "1000110" "1000110" "000110" "000110", 16);
            stream[5] = 0x00; stream[6] = 0x00; stream[7] = 0x01; stream[8] = 0xB7;
            pushQword(mem, stream.data());

            // BDEC: MBI=1, DCR=1, QSC=1.
            mem.write32(IPU_CMD, 0x20000000u | (1u << 27) | (1u << 26) | (1u << 16));
            t.IsFalse(busy(mem), "BDEC with a complete macroblock in the FIFO must finish");
            const uint32_t ctrl = mem.read32(IPU_CTRL);
            t.IsTrue((ctrl & (1u << 15)) != 0u, "the trailing start code must set SCD");
            t.IsTrue((ctrl & (1u << 14)) == 0u, "no decoding error expected");
            t.Equals((ctrl >> 4) & 0xFu, 8u, "OFC saturates at 8 with 48 quadwords queued");
            t.Equals(static_cast<uint32_t>(mem.read64(IPU_TOP)), 0x000001B7u, "IPU_TOP shows the start code");

            constexpr uint32_t kOut = 0x00100000u;
            mem.write32(D3_MADR, kOut);
            mem.write32(D3_QWC, 48u);
            mem.write32(D3_CHCR, 0x100u);
            t.Equals(mem.read32(D3_CHCR) & 0x100u, 0u, "ch3 completes once 48 quadwords are moved");
            t.Equals(mem.read32(D3_QWC), 0u, "ch3 QWC counts down to zero");
            t.IsTrue((mem.read32(D_STAT) & (1u << 3)) != 0u, "D_STAT CIS3 must be raised");
            const std::vector<uint32_t> causes = mem.consumeCompletedDmacCauses();
            t.IsTrue(std::find(causes.begin(), causes.end(), 3u) != causes.end(), "DMAC cause 3 queued");
            t.IsTrue(mem.consumeIpuInterrupt(), "command completion raises the IPU interrupt");

            // dc = 128 (reset predictor) << 3 = 1024; IDCT of a DC-only block is dc / 8.
            const uint8_t *rdram = mem.getRDRAM();
            bool allMid = true;
            for (size_t i = 0; i < 384; ++i)
            {
                int16_t v;
                std::memcpy(&v, rdram + kOut + i * 2, 2);
                allMid = allMid && v == 128;
            }
            t.IsTrue(allMid, "every Y/Cb/Cr sample of the RAW16 macroblock is 128");
        });

        tc.Run("FDEC reads through a ch4 normal transfer and IPU_BP tracks the stream position", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "PS2Memory initialize should succeed");
            constexpr uint32_t kSrc = 0x00200000u;
            uint8_t *rdram = mem.getRDRAM();
            for (uint32_t i = 0; i < 32u; ++i)
                rdram[kSrc + i] = static_cast<uint8_t>(0x12u + i * 0x22u);

            mem.write32(D4_MADR, kSrc);
            mem.write32(D4_QWC, 2u);
            mem.write32(D4_CHCR, 0x101u); // normal mode, from memory, STR
            t.Equals(mem.read32(D4_CHCR) & 0x100u, 0u, "two quadwords fit the FIFO, so ch4 completes");
            t.Equals(mem.read32(D4_MADR), kSrc + 32u, "MADR advances by what entered the FIFO");
            t.IsTrue((mem.read32(D_STAT) & (1u << 4)) != 0u, "D_STAT CIS4 must be raised");

            mem.write32(IPU_CMD, 0x40000000u); // FDEC 0
            t.IsFalse(busy(mem), "FDEC with data resident must finish");
            t.Equals(mem.read32(IPU_CMD), 0x12345678u, "FDEC returns the next 32 bits");
            uint32_t bp = mem.read32(IPU_BP);
            t.Equals(bp & 0x7Fu, 0u, "BP is still 0 after FDEC 0");
            t.Equals(((bp >> 8) & 0xFu) + ((bp >> 16) & 3u), 2u, "IFC + FP counts both resident quadwords");

            mem.write32(IPU_CMD, 0x40000008u); // FDEC 8
            t.Equals(mem.read32(IPU_CMD), 0x3456789Au, "FDEC 8 skips one byte");
            bp = mem.read32(IPU_BP);
            const uint32_t ifc = (bp >> 8) & 0xFu, fp = (bp >> 16) & 3u;
            const uint32_t streamByte = mem.read32(D4_MADR) - (ifc + fp) * 16u + ((bp & 0x7Fu) >> 3);
            t.Equals(streamByte, kSrc + 1u, "libmpeg's MADR - (IFC + FP) * 16 + BP / 8 names the next byte");
        });

        tc.Run("A command stalled on input resumes when the FIFO is fed", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "PS2Memory initialize should succeed");
            mem.write32(IPU_CMD, 0x40000000u);
            t.IsTrue(busy(mem), "FDEC without input stays busy");
            t.IsTrue((mem.read32(IPU_CTRL) & 0x80000000u) != 0u, "IPU_CTRL.BUSY mirrors the pending command");
            const uint8_t qw[16] = {0xCA, 0xFE, 0xBA, 0xBE};
            pushQword(mem, qw);
            t.IsFalse(busy(mem), "the FIFO store lets the pending FDEC finish");
            t.Equals(mem.read32(IPU_CMD), 0xCAFEBABEu, "the resumed FDEC sees the stored bits");
        });

        tc.Run("ch4 does not advance while the DMAC is held and runs when the hold lifts", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "PS2Memory initialize should succeed");
            t.Equals(mem.read32(D_ENABLER), 0x1201u, "D_ENABLER boots at 0x1201");
            mem.write32(D_ENABLEW, 0x11201u); // suspend
            t.Equals(mem.read32(D_ENABLER), 0x11201u, "D_ENABLER mirrors D_ENABLEW");
            mem.write32(D4_MADR, 0x00300000u);
            mem.write32(D4_QWC, 1u);
            mem.write32(D4_CHCR, 0x101u);
            t.Equals(mem.read32(D4_CHCR) & 0x100u, 0x100u, "a kick inside the hold leaves STR set");
            t.Equals(mem.read32(D4_CHCR) & 0x100u, 0x100u, "reading CHCR does not clear STR on ch4");
            t.Equals(mem.read32(D4_QWC), 1u, "nothing moves while the DMAC is held");
            mem.write32(D_ENABLEW, 0x1201u);
            t.Equals(mem.read32(D4_CHCR) & 0x100u, 0u, "the queued kick runs on release");
            t.Equals(mem.read32(D4_QWC), 0u, "the quadword entered the FIFO");
        });

        tc.Run("BCLR drops resident input and libmpeg's rewind replays it from BP", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "PS2Memory initialize should succeed");
            constexpr uint32_t kSrc = 0x00400000u;
            uint8_t *rdram = mem.getRDRAM();
            for (uint32_t i = 0; i < 64u; ++i)
                rdram[kSrc + i] = static_cast<uint8_t>(i);
            mem.write32(D4_MADR, kSrc);
            mem.write32(D4_QWC, 4u);
            mem.write32(D4_CHCR, 0x101u);
            mem.write32(IPU_CMD, 0x40000000u | 20u); // FDEC 20: cursor at bit 20 (byte 2.5)

            // Stop/restart as RE4 does at 0x2CDC90: rewind MADR by the resident
            // quadwords, BCLR with the saved BP, restart.
            mem.write32(D_ENABLEW, 0x11201u);
            mem.write32(D4_CHCR, 0x1u);
            const uint32_t saved = mem.read32(IPU_BP);
            const uint32_t madr = mem.read32(D4_MADR), qwc = mem.read32(D4_QWC);
            const uint32_t resident = ((saved >> 8) & 0xFu) + ((saved >> 16) & 3u);
            mem.write32(IPU_CMD, saved & 0x7Fu); // BCLR
            t.Equals(mem.read32(IPU_BP) & 0x00030F00u, 0u, "BCLR empties the FIFO");
            mem.write32(D4_MADR, madr - resident * 16u);
            mem.write32(D4_QWC, qwc + resident);
            mem.write32(D4_CHCR, 0x101u);
            mem.write32(D_ENABLEW, 0x1201u);

            mem.write32(IPU_CMD, 0x40000000u | 4u); // FDEC 4: byte aligned at byte 3
            t.Equals(mem.read32(IPU_CMD), 0x03040506u, "the replay resumes exactly where the decoder was");
        });

        tc.Run("BDEC applies MPEG-1 oddification only when IPU_CTRL.MP1 is set", [](TestCase &t)
        {
            // Non-intra block 0 with one first coefficient '1s' (level 1),
            // flat non-intra matrix 16, QSC 4 (linear q 8):
            //   ((2*1+1) * 8 * 16) >> 5 = 12; MPEG-1 makes it odd: 11.
            //   DC-only IDCT is coefficient / 8: 1.5 -> 2 (MPEG-2), 1.375 -> 1 (MPEG-1).
            auto decode = [](bool mpeg1) {
                PS2Memory mem;
                mem.initialize();
                uint8_t flat[64];
                std::memset(flat, 16, sizeof(flat));
                for (int i = 0; i < 4; ++i)
                    pushQword(mem, flat + i * 16);
                mem.write32(IPU_CMD, 0x58000000u); // SETIQ non-intra
                mem.write32(IPU_CTRL, (mpeg1 ? (1u << 23) : 0u) | (2u << 24)); // P picture
                // cbp 0x20 '1010', first coefficient '1' + sign '0', EOB '10'.
                std::vector<uint8_t> stream = packBits("1010" "10" "10", 16);
                stream[1] = 0x00; stream[2] = 0x00; stream[3] = 0x01; stream[4] = 0xB7;
                pushQword(mem, stream.data());
                mem.write32(IPU_CMD, 0x20000000u | (4u << 16)); // BDEC non-intra, QSC 4
                uint8_t out[768] = {};
                mem.write32(D3_MADR, 0x00100000u);
                mem.write32(D3_QWC, 48u);
                mem.write32(D3_CHCR, 0x100u);
                std::memcpy(out, mem.getRDRAM() + 0x00100000u, sizeof(out));
                int16_t y0;
                std::memcpy(&y0, out, 2);
                return y0;
            };
            t.Equals(static_cast<int>(decode(false)), 2, "MPEG-2 keeps the even coefficient 12");
            t.Equals(static_cast<int>(decode(true)), 1, "MPEG-1 reconstructs it as 11");
        });

        tc.Run("toSPR source chain copies REF payloads into the scratchpad", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "PS2Memory initialize should succeed");
            uint8_t *rdram = mem.getRDRAM();
            constexpr uint32_t kTags = 0x00700000u, kA = 0x00710000u, kB = 0x00720000u;
            std::memset(rdram + kA, 0xA1, 32);
            std::memset(rdram + kB, 0xB2, 16);
            const uint64_t tags[3] = {
                (static_cast<uint64_t>(kA) << 32) | (3ull << 28) | 2u, // REF, 2 qw
                (static_cast<uint64_t>(kB) << 32) | (3ull << 28) | 1u, // REF, 1 qw
                (static_cast<uint64_t>(kA) << 32) | (0ull << 28) | 1u, // REFE, 1 qw
            };
            for (int i = 0; i < 3; ++i)
                std::memcpy(rdram + kTags + i * 16, &tags[i], 8);
            mem.write32(0x1000D480u, 0x100u); // SADR
            mem.write32(0x1000D420u, 0u);
            mem.write32(0x1000D430u, kTags);
            mem.write32(0x1000D400u, 0x105u); // source chain, STR
            const uint8_t *spr = mem.getScratchpad();
            t.Equals(static_cast<uint32_t>(spr[0x100]), 0xA1u, "first REF lands at SADR");
            t.Equals(static_cast<uint32_t>(spr[0x11F]), 0xA1u, "first REF moves two quadwords");
            t.Equals(static_cast<uint32_t>(spr[0x120]), 0xB2u, "second REF follows");
            t.Equals(static_cast<uint32_t>(spr[0x130]), 0xA1u, "REFE payload closes the chain");
            t.Equals(mem.read32(0x1000D480u), 0x140u, "SADR advances by four quadwords");
            t.Equals(mem.read32(0x1000D430u), kTags + 48u, "TADR sits past the REFE");
        });

        tc.Run("CSC converts a white RAW8 macroblock to RGB32", [](TestCase &t)
        {
            PS2Memory mem;
            t.IsTrue(mem.initialize(), "PS2Memory initialize should succeed");
            std::array<uint8_t, 384> mb{};
            std::memset(mb.data(), 235, 256);       // Y
            std::memset(mb.data() + 256, 128, 128); // Cb, Cr
            constexpr uint32_t kSrc = 0x00500000u, kOut = 0x00600000u;
            std::memcpy(mem.getRDRAM() + kSrc, mb.data(), mb.size());
            mem.write32(IPU_CMD, 0x70000001u); // CSC, RGB32, 1 macroblock
            t.IsTrue(busy(mem), "CSC waits for its 24 input quadwords");
            mem.write32(D3_MADR, kOut);
            mem.write32(D3_QWC, 64u);
            mem.write32(D3_CHCR, 0x100u);
            mem.write32(D4_MADR, kSrc);
            mem.write32(D4_QWC, 24u);
            mem.write32(D4_CHCR, 0x101u);
            t.IsFalse(busy(mem), "CSC finishes once ch4 has streamed the macroblock");
            t.Equals(mem.read32(D4_CHCR) & 0x100u, 0u, "ch4 completes");
            t.Equals(mem.read32(D3_CHCR) & 0x100u, 0u, "ch3 receives all 64 output quadwords");
            uint32_t pixel;
            std::memcpy(&pixel, mem.getRDRAM() + kOut + 4u * 255u, 4);
            t.Equals(pixel, 0x80FFFFFFu, "Y=235 converts to opaque white (alpha 0x80)");
        });
    });
}

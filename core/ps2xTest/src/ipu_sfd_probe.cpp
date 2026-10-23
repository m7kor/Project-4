// ps2x_ipu_sfd_probe: decodes the first I picture of an SFD movie through the
// IPU model, without booting a game.
//
//   ps2x_ipu_sfd_probe <archive.afs> <entry> <out.bmp> [skip-pictures]
//
// The movie is located through the AFS table, its MPEG system stream is
// demuxed for video stream 0xE0, and the elementary stream is decoded the way
// Sony's libmpeg drives the hardware: FDEC/VDEC for headers and macroblock
// addressing, SETIQ for quantiser matrices, BDEC per macroblock. Input is fed
// to the model 8 quadwords at a time whenever a command stalls, so the FIFO
// accounting stays inside what IPU_BP can describe.
//
// Pass criteria printed at the end: the picture decodes to exactly
// mb_width x mb_height macroblocks with no ECD, and the luma statistics are
// plausible. The BMP is for visual inspection; it is written next to nothing
// in the repository (pass an output path outside it).

#include "runtime/ps2_ipu.h"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace
{
    [[noreturn]] void fail(const char *fmt, const char *detail = "", unsigned a = 0, unsigned b = 0)
    {
        std::fprintf(stderr, "FAIL: ");
        std::fprintf(stderr, fmt, detail, a, b);
        std::fprintf(stderr, "\n");
        std::exit(1);
    }

    class NullHost final : public Ps2IpuHost
    {
    public:
        uint8_t *ipuDmaPointer(uint32_t, uint32_t) override { return nullptr; }
        uint32_t &ipuDmaRegister(int channel, int which) override { return regs[channel == 4 ? 1 : 0][which & 3]; }
        void ipuDmaComplete(int) override {}
        bool ipuDmaSuspended() override { return false; }
        void ipuRaiseInterrupt() override {}
        uint32_t regs[2][4] = {};
    };

    NullHost g_host;
    Ps2Ipu g_ipu(g_host);
    std::vector<uint8_t> g_es;
    size_t g_fed = 0;

    constexpr uint32_t IPU_CMD = 0x10002000u, IPU_CTRL = 0x10002010u, IPU_BP = 0x10002020u;

    uint64_t r64(uint32_t address)
    {
        uint64_t v = 0;
        g_ipu.readRegister64(address, v);
        return v;
    }

    bool feedMore()
    {
        if (g_fed >= g_es.size())
            return false;
        size_t n = g_es.size() - g_fed;
        if (n > 128)
            n = 128;
        uint8_t buf[128] = {};
        std::memcpy(buf, g_es.data() + g_fed, n);
        g_ipu.testFeed(buf, (n + 15) & ~size_t{15});
        g_fed += n;
        return true;
    }

    std::vector<uint8_t> g_out;

    uint64_t cmdResult()
    {
        uint64_t r = r64(IPU_CMD);
        while (r >> 63)
        {
            if (!feedMore())
                fail("IPU stayed busy with the whole elementary stream fed%s");
            r = r64(IPU_CMD);
        }
        uint8_t buf[4096];
        for (;;)
        {
            const size_t n = g_ipu.testReadOutput(buf, sizeof(buf));
            if (n == 0)
                break;
            g_out.insert(g_out.end(), buf, buf + n);
        }
        return r;
    }

    void cmd(uint32_t v) { g_ipu.writeRegister(IPU_CMD, v); }
    uint32_t fdec(unsigned skip)
    {
        cmd(0x40000000u | skip);
        return static_cast<uint32_t>(cmdResult());
    }
    void advance(unsigned bits)
    {
        while (bits > 32)
        {
            fdec(32);
            bits -= 32;
        }
        if (bits)
            fdec(bits);
    }
    uint32_t peekbits(unsigned n) { return fdec(0) >> (32 - n); }
    uint32_t getbits(unsigned n)
    {
        const uint32_t v = peekbits(n);
        advance(n);
        return v;
    }
    uint32_t vdec(unsigned table)
    {
        cmd(0x30000000u | (table << 26));
        return static_cast<uint32_t>(cmdResult());
    }
    uint32_t ctrl() { return static_cast<uint32_t>(r64(IPU_CTRL)); }
    void byteAlign()
    {
        const uint32_t bp = static_cast<uint32_t>(r64(IPU_BP)) & 0x7Fu;
        if (bp & 7u)
            advance(8 - (bp & 7u));
    }
    bool findStartCode()
    {
        byteAlign();
        for (int guard = 0; guard < (1 << 22); ++guard)
        {
            if (peekbits(24) == 1u)
                return true;
            if (g_fed >= g_es.size() && g_ipu.testAvailableBits() < 32)
                return false;
            advance(8);
        }
        return false;
    }

    // ---- SFD (MPEG system stream) demux ----

    std::vector<uint8_t> demuxVideo(const std::vector<uint8_t> &sfd, size_t want)
    {
        std::vector<uint8_t> es;
        size_t pos = 0;
        auto rd16 = [&](size_t at) { return static_cast<unsigned>((sfd[at] << 8) | sfd[at + 1]); };
        while (pos + 6 <= sfd.size() && es.size() < want)
        {
            if (!(sfd[pos] == 0 && sfd[pos + 1] == 0 && sfd[pos + 2] == 1))
            {
                ++pos;
                continue;
            }
            const uint8_t sid = sfd[pos + 3];
            if (sid == 0xBA)
            {
                if ((sfd[pos + 4] & 0xC0) == 0x40) // MPEG-2 pack header
                    pos += 14 + (sfd[pos + 13] & 7);
                else // MPEG-1 pack header
                    pos += 12;
                continue;
            }
            if (sid == 0xB9)
                break;
            if (sid < 0xBB)
            {
                ++pos;
                continue;
            }
            const unsigned len = rd16(pos + 4);
            const size_t end = pos + 6 + len;
            if (end > sfd.size())
                break;
            if (sid == 0xE0)
            {
                size_t p = pos + 6;
                if ((sfd[p] & 0xC0) == 0x80)
                {
                    p += 3 + sfd[p + 2]; // MPEG-2 PES header
                }
                else
                {
                    while (p < end && sfd[p] == 0xFF)
                        ++p; // stuffing
                    if ((sfd[p] & 0xC0) == 0x40)
                        p += 2; // STD buffer
                    if ((sfd[p] & 0xF0) == 0x20)
                        p += 5;
                    else if ((sfd[p] & 0xF0) == 0x30)
                        p += 10;
                    else
                        p += 1; // 0x0F
                }
                if (p < end)
                    es.insert(es.end(), sfd.begin() + static_cast<std::ptrdiff_t>(p),
                              sfd.begin() + static_cast<std::ptrdiff_t>(end));
            }
            pos = end;
        }
        return es;
    }

    // ---- MPEG-2 decode driver (libmpeg's role) ----

    constexpr int MB_INTRA = 1, MB_PATTERN = 2, MB_BACKWARD = 4, MB_FORWARD = 8, MB_QUANT = 16;

    constexpr uint8_t kDefaultIntraQ[64] = {
        8, 16, 19, 22, 26, 27, 29, 34, 16, 16, 22, 24, 27, 29, 34, 37,
        19, 22, 26, 27, 29, 34, 34, 38, 22, 22, 26, 27, 29, 34, 37, 40,
        22, 26, 27, 29, 32, 35, 40, 48, 26, 27, 29, 32, 35, 40, 48, 58,
        26, 27, 29, 34, 38, 46, 56, 69, 27, 29, 35, 38, 46, 56, 69, 83,
    };

    unsigned g_width = 0, g_height = 0, g_mbw = 0, g_mbh = 0;
    unsigned g_picType = 0, g_fpfd = 1, g_conceal = 0, g_structure = 3;
    unsigned g_fcode[2][2] = {{15, 15}, {15, 15}};
    std::vector<uint8_t> g_y, g_cb, g_cr;

    void parseSequenceHeader()
    {
        advance(32);
        g_width = getbits(12);
        g_height = getbits(12);
        advance(4 + 4 + 18 + 1 + 10 + 1);
        if (getbits(1))
        {
            cmd(0x50000000u);
            cmdResult();
        }
        if (getbits(1))
        {
            cmd(0x58000000u);
            cmdResult();
        }
        g_mbw = (g_width + 15) / 16;
        g_mbh = (g_height + 15) / 16;
        std::printf("sequence: %ux%u (%ux%u macroblocks)\n", g_width, g_height, g_mbw, g_mbh);
    }

    bool g_mpeg2 = false; // a sequence extension was seen

    void parsePictureHeader()
    {
        advance(32 + 10);
        g_picType = getbits(3);
        advance(16);
        unsigned forward = 0, backward = 0;
        if (g_picType == 2 || g_picType == 3)
        {
            advance(1); // full_pel_forward_vector
            forward = getbits(3);
        }
        if (g_picType == 3)
        {
            advance(1); // full_pel_backward_vector
            backward = getbits(3);
        }
        if (!g_mpeg2)
        {
            // MPEG-1: no picture coding extension follows; libmpeg programs
            // IPU_CTRL with MP1 and the picture type straight away.
            g_fcode[0][0] = g_fcode[0][1] = forward;
            g_fcode[1][0] = g_fcode[1][1] = backward;
            g_fpfd = 1;
            g_conceal = 0;
            g_structure = 3;
            g_ipu.writeRegister(IPU_CTRL, (1u << 23) | (g_picType << 24));
        }
    }

    void parseExtension()
    {
        advance(32);
        const unsigned id = getbits(4);
        if (id == 1)
            g_mpeg2 = true; // sequence extension
        if (id != 8)
        {
            advance(4);
            return;
        }
        for (int i = 0; i < 4; ++i)
            g_fcode[i >> 1][i & 1] = getbits(4);
        const unsigned idp = getbits(2);
        g_structure = getbits(2);
        advance(1);
        g_fpfd = getbits(1);
        g_conceal = getbits(1);
        const unsigned qst = getbits(1), ivf = getbits(1), as = getbits(1);
        advance(3);
        if (getbits(1))
            advance(20);
        g_ipu.writeRegister(IPU_CTRL, (idp << 16) | (as << 20) | (ivf << 21) | (qst << 22) | (g_picType << 24));
        std::printf("picture type %u: idp=%u structure=%u fpfd=%u qst=%u ivf=%u as=%u\n", g_picType, idp,
                    g_structure, g_fpfd, qst, ivf, as);
        if (g_structure != 3)
            fail("field picture%s is not handled by this probe");
    }

    void parseMvComponent(int dir, int sv)
    {
        const uint32_t r = vdec(2);
        if (r == 0)
            fail("invalid motion code%s");
        const int16_t code = static_cast<int16_t>(r & 0xFFFFu);
        const unsigned rsize = g_fcode[dir][sv] - 1;
        if (code != 0 && rsize)
            advance(rsize);
    }

    unsigned decodeSlice(uint32_t startCode)
    {
        const unsigned row = (startCode & 0xFFu) - 1;
        advance(32);
        unsigned qsc = getbits(5);
        while (getbits(1))
            advance(8);
        int address = static_cast<int>(row * g_mbw) - 1;
        bool needDcr = true;
        unsigned decoded = 0;
        for (;;)
        {
            int increment = 0;
            bool sliceEnd = false;
            for (;;)
            {
                const uint32_t r = vdec(0);
                const uint16_t v = static_cast<uint16_t>(r & 0xFFFFu);
                if (r == 0)
                {
                    sliceEnd = true;
                    break;
                }
                if (v == 0x23)
                {
                    increment += 33;
                    continue;
                }
                if (v == 0x22)
                    continue;
                increment += v;
                break;
            }
            if (sliceEnd)
                break;
            if (increment > 1)
                needDcr = true;
            address += increment;

            const unsigned modes = vdec(1) & 0xFFFFu;
            if (modes == 0)
                fail("invalid macroblock type%s at mb %u (row %u)", "", static_cast<unsigned>(address), row);
            bool dt = false;
            if (!g_fpfd && (modes & (MB_PATTERN | MB_INTRA)))
                dt = getbits(1) != 0;
            if (modes & MB_QUANT)
                qsc = getbits(5);
            if ((modes & MB_INTRA) && g_conceal)
            {
                parseMvComponent(0, 0);
                parseMvComponent(0, 1);
                advance(1);
            }
            if (!(modes & MB_INTRA))
            {
                for (int dir = 0; dir < 2; ++dir)
                {
                    if (!(modes & (dir ? MB_BACKWARD : MB_FORWARD)))
                        continue;
                    parseMvComponent(dir, 0);
                    parseMvComponent(dir, 1);
                }
            }
            if (!(modes & (MB_INTRA | MB_PATTERN)))
            {
                needDcr = true;
                continue;
            }
            const bool intra = (modes & MB_INTRA) != 0;
            cmd(0x20000000u | (intra ? 1u << 27 : 0u) | ((intra ? needDcr : true) ? 1u << 26 : 0u) |
                (dt ? 1u << 25 : 0u) | (qsc << 16));
            cmdResult();
            if (ctrl() & (1u << 14))
                fail("ECD after BDEC%s at mb %u (row %u)", "", static_cast<unsigned>(address), row);
            if (g_out.size() != 768)
                fail("BDEC produced %s%u bytes, expected 768", "", static_cast<unsigned>(g_out.size()));
            int16_t mb[384];
            std::memcpy(mb, g_out.data(), sizeof(mb));
            g_out.clear();
            if (g_picType == 1)
            {
                const unsigned mx = static_cast<unsigned>(address) % g_mbw, my = static_cast<unsigned>(address) / g_mbw;
                for (int yy = 0; yy < 16; ++yy)
                    for (int xx = 0; xx < 16; ++xx)
                    {
                        const int v = mb[yy * 16 + xx];
                        const size_t py = my * 16 + yy, px = mx * 16 + xx;
                        if (py < g_height && px < g_width)
                            g_y[py * g_width + px] = static_cast<uint8_t>(v < 0 ? 0 : (v > 255 ? 255 : v));
                    }
                for (int yy = 0; yy < 8; ++yy)
                    for (int xx = 0; xx < 8; ++xx)
                    {
                        const size_t py = my * 8 + yy, px = mx * 8 + xx;
                        if (py >= g_height / 2 || px >= g_width / 2)
                            continue;
                        const size_t at = py * (g_width / 2) + px;
                        g_cb[at] = static_cast<uint8_t>(std::min(255, std::max(0, static_cast<int>(mb[256 + yy * 8 + xx]))));
                        g_cr[at] = static_cast<uint8_t>(std::min(255, std::max(0, static_cast<int>(mb[320 + yy * 8 + xx]))));
                    }
            }
            ++decoded;
            needDcr = !intra;
            if (ctrl() & (1u << 15))
                break; // SCD: a start code follows
        }
        return decoded;
    }

    void writeBmp(const std::string &path)
    {
        const unsigned w = g_width, h = g_height;
        const uint32_t rowBytes = w * 3, pad = (4 - (rowBytes & 3)) & 3, imageSize = (rowBytes + pad) * h;
        uint8_t header[54] = {'B', 'M'};
        const uint32_t fileSize = 54 + imageSize, offset = 54, infoSize = 40;
        std::memcpy(header + 2, &fileSize, 4);
        std::memcpy(header + 10, &offset, 4);
        std::memcpy(header + 14, &infoSize, 4);
        std::memcpy(header + 18, &w, 4);
        std::memcpy(header + 22, &h, 4);
        header[26] = 1;
        header[28] = 24;
        std::memcpy(header + 34, &imageSize, 4);
        std::ofstream out(path, std::ios::binary);
        out.write(reinterpret_cast<const char *>(header), 54);
        std::vector<uint8_t> row(rowBytes + pad, 0);
        for (int y = static_cast<int>(h) - 1; y >= 0; --y)
        {
            for (unsigned x = 0; x < w; ++x)
            {
                const double Y = g_y[y * w + x];
                const double cb = g_cb[(y / 2) * (w / 2) + x / 2] - 128.0;
                const double cr = g_cr[(y / 2) * (w / 2) + x / 2] - 128.0;
                const double l = 1.164 * (Y - 16.0);
                auto clamp = [](double v) { return static_cast<uint8_t>(v < 0 ? 0 : (v > 255 ? 255 : v)); };
                row[x * 3 + 2] = clamp(l + 1.596 * cr);
                row[x * 3 + 1] = clamp(l - 0.392 * cb - 0.813 * cr);
                row[x * 3 + 0] = clamp(l + 2.017 * cb);
            }
            out.write(reinterpret_cast<const char *>(row.data()), static_cast<std::streamsize>(row.size()));
        }
    }
}

int main(int argc, char **argv)
{
    if (argc < 4)
    {
        std::fprintf(stderr, "usage: %s <archive.afs> <entry> <out.bmp> [skip-pictures]\n", argv[0]);
        return 2;
    }
    const unsigned entry = static_cast<unsigned>(std::strtoul(argv[2], nullptr, 0));
    const unsigned skipPictures = argc > 4 ? static_cast<unsigned>(std::strtoul(argv[4], nullptr, 0)) : 0u;

    std::ifstream afs(argv[1], std::ios::binary);
    if (!afs)
        fail("cannot open %s", argv[1]);
    char magic[4];
    uint32_t count = 0;
    afs.read(magic, 4);
    afs.read(reinterpret_cast<char *>(&count), 4);
    if (std::memcmp(magic, "AFS\0", 4) != 0 || entry >= count)
        fail("%s is not an AFS archive or has no entry %u", argv[1], entry);
    uint32_t offsetSize[2];
    afs.seekg(8 + 8 * static_cast<std::streamoff>(entry));
    afs.read(reinterpret_cast<char *>(offsetSize), 8);
    const uint32_t readSize = std::min<uint32_t>(offsetSize[1], 24u << 20);
    std::vector<uint8_t> sfd(readSize);
    afs.seekg(offsetSize[0]);
    afs.read(reinterpret_cast<char *>(sfd.data()), readSize);
    std::printf("entry %u: offset 0x%x size %u\n", entry, offsetSize[0], offsetSize[1]);

    g_es = demuxVideo(sfd, 16u << 20);
    std::printf("demuxed %zu bytes of video elementary stream\n", g_es.size());
    if (g_es.empty())
        fail("no video stream 0xE0 found%s");

    g_ipu.writeRegister(IPU_CTRL, 1u << 30);
    cmd(0x00000000u);
    // libmpeg loads the default intra and a flat non-intra matrix out of band.
    uint8_t flat[64];
    std::memset(flat, 16, sizeof(flat));
    g_ipu.testFeed(kDefaultIntraQ, 64);
    g_ipu.testFeed(flat, 64);
    cmd(0x50000000u);
    cmdResult();
    cmd(0x58000000u);
    cmdResult();

    bool seqSeen = false, decodingI = false;
    unsigned picturesSeen = 0, mbs = 0;
    while (findStartCode())
    {
        const uint32_t sc = peekbits(32);
        if (sc == 0x1B3u)
        {
            parseSequenceHeader();
            if (!seqSeen)
            {
                g_y.assign(static_cast<size_t>(g_width) * g_height, 0);
                g_cb.assign(static_cast<size_t>(g_width) * g_height / 4, 128);
                g_cr.assign(static_cast<size_t>(g_width) * g_height / 4, 128);
            }
            seqSeen = true;
        }
        else if (!seqSeen)
        {
            advance(32);
        }
        else if (sc == 0x1B5u)
        {
            parseExtension();
        }
        else if (sc == 0x100u)
        {
            if (decodingI)
                break; // the next picture header ends the I picture
            parsePictureHeader();
            if (g_picType == 1 && picturesSeen++ >= skipPictures)
                decodingI = true;
        }
        else if (sc >= 0x101u && sc <= 0x1AFu)
        {
            if (!decodingI)
            {
                advance(32);
                continue;
            }
            mbs += decodeSlice(sc);
        }
        else if (sc == 0x1B7u)
        {
            break;
        }
        else
        {
            advance(32);
        }
    }

    if (!decodingI)
        fail("no I picture found%s");
    double sum = 0, sq = 0;
    for (uint8_t v : g_y)
    {
        sum += v;
        sq += static_cast<double>(v) * v;
    }
    const double mean = sum / g_y.size(), sd = std::sqrt(sq / g_y.size() - mean * mean);
    writeBmp(argv[3]);
    std::printf("I picture: %u of %u macroblocks, luma mean %.1f sd %.1f, %llu BDEC, written %s\n", mbs,
                g_mbw * g_mbh, mean, sd, static_cast<unsigned long long>(g_ipu.commandCount(2)), argv[3]);
    if (mbs != g_mbw * g_mbh)
        fail("I picture decoded %s%u macroblocks, expected %u", "", mbs, g_mbw * g_mbh);
    // A fade-in starts on a uniformly black picture; that decodes correctly
    // and is reported, not failed. Bright, flat output is still an error.
    if (mean > 235.0 || (sd < 1.0 && mean > 20.0))
        fail("luma statistics%s are implausible");
    if (mean < 16.0)
        std::printf("note: picture is black (fade-in)\n");
    std::printf("PASS\n");
    return 0;
}

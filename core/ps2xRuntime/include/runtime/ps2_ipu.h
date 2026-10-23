#pragma once

// EE IPU (image processing unit) model: command execution, the input FIFO and
// decode window, the output queue, and the toIPU (ch4) / fromIPU (ch3) DMA
// bridge. Sony's libmpeg, statically linked into games such as RE4 and
// recompiled with them, drives this hardware directly through IPU_CMD,
// IPU_CTRL, IPU_BP and IPU_TOP plus DMA channels 3 and 4.
//
// Adapted from the MIT-licensed IPU model of ico-recomp
// (research/project-survey/20261007/ico/sources/src/runtime/hw/ipu.cpp,
// Copyright (c) 2026 ico-recomp contributors). The state that file kept in
// globals lives in an instance here, and its DMAC/INTC/logging dependencies
// are reached through Ps2IpuHost.

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <vector>

// One variable-length code: matched when the next `len` bits equal `code`.
struct IpuVlc
{
    uint16_t code;
    uint8_t len;
    int16_t val;
};

class Ps2IpuHost
{
public:
    virtual ~Ps2IpuHost() = default;

    // Host pointer for `bytes` of guest memory at a DMA address (bit 31 selects
    // the scratchpad). nullptr when the range is not mapped.
    virtual uint8_t *ipuDmaPointer(uint32_t address, uint32_t bytes) = 0;
    // DMA channel register for ch 3 or 4: 0 CHCR, 1 MADR, 2 QWC, 3 TADR.
    virtual uint32_t &ipuDmaRegister(int channel, int which) = 0;
    // Transfer end: clear CHCR.STR, raise the D_STAT channel bit and queue the
    // DMAC handlers. Delivered after the guest access, never inside it.
    virtual void ipuDmaComplete(int channel) = 0;
    // True while the DMAC is held (D_ENABLE suspend or D_CTRL.DMAE clear).
    virtual bool ipuDmaSuspended() = 0;
    // INTC cause 8.
    virtual void ipuRaiseInterrupt() = 0;
};

class Ps2Ipu
{
public:
    explicit Ps2Ipu(Ps2IpuHost &host);

    void reset();

    // Register window 0x10002000..0x1000203F, 64-bit view (IPU_CMD and IPU_TOP
    // carry BUSY in bit 63). Returns false for addresses outside the window.
    bool readRegister64(uint32_t address, uint64_t &value);
    bool writeRegister(uint32_t address, uint64_t value);

    // 128-bit stores to the toIPU FIFO window (0x10007010) and loads from the
    // fromIPU FIFO window (0x10007000).
    void writeInputFifo(const uint8_t *qw16);
    void readOutputFifo(uint8_t *qw16);

    // DMAC bridge: CHCR written with STR set (kick) or clear (stop) for ch3/4,
    // and the DMAC hold lifted with no IPU kick queued.
    void dmaKick(int channel);
    void dmaStop(int channel);
    void dmaResume();

    bool busy() const { return m_busy; }
    uint64_t commandCount(uint32_t code) const { return code < 16u ? m_cmdCensus[code] : 0u; }
    uint64_t totalCommandCount() const;
    // Relaxed copies for the diagnostics thread: commands written and the last
    // IPU_CMD value.
    uint64_t debugCommands() const { return m_debugCommands.load(std::memory_order_relaxed); }
    uint32_t debugLastCommand() const { return m_debugLastCommand.load(std::memory_order_relaxed); }

    // Test hooks: bypass the DMA and read the output queue directly.
    void testFeed(const uint8_t *data, size_t length);
    size_t testOutputAvailable() const { return m_out.size() - m_outHead; }
    size_t testReadOutput(uint8_t *dst, size_t maxLength);
    size_t testAvailableBits() const { return availBits(); }
    size_t testResidentQuadwords() const { return heldQw(); }

private:
    struct Snapshot
    {
        size_t inPos = 0;
        uint64_t outProduced = 0;
        int dcpred[3] = {0, 0, 0};
        uint32_t cbp = 0;
    };

    struct MacroBlock16
    {
        int16_t y[16][16];
        int16_t cb[8][8];
        int16_t cr[8][8];
    };

    struct MacroBlock8
    {
        uint8_t y[16][16];
        uint8_t cb[8][8];
        uint8_t cr[8][8];
    };

    // Input side.
    size_t qwFrom(size_t at) const;
    size_t heldQw() const { return qwFrom(m_inPos); }
    size_t walkQw() const { return qwFrom(m_inHw); }
    uint32_t bpBp() const { return static_cast<uint32_t>(m_inPos % 128u); }
    uint32_t bpFp() const { return heldQw() ? 1u : 0u; }
    uint32_t bpIfc();
    void completeCh4();
    void advanceWalk();
    bool pullQword();
    size_t availBits() const;
    bool ensureBits(size_t n);
    uint32_t peekBits(unsigned n) const;
    void advanceBits(size_t n);
    uint32_t getBits(unsigned n);
    int32_t getSigned(unsigned n);
    void compactIn();

    // Output side.
    size_t outAvail() const { return m_out.size() - m_outHead; }
    void outPush(const void *data, size_t length);
    void completeCh3();
    void drainCh3();

    // Decoder.
    int ctrlIdp() const { return (m_ctrlBits >> 16) & 3; }
    int ctrlAs() const { return (m_ctrlBits >> 20) & 1; }
    int ctrlIvf() const { return (m_ctrlBits >> 21) & 1; }
    int ctrlQst() const { return (m_ctrlBits >> 22) & 1; }
    int ctrlMp1() const { return (m_ctrlBits >> 23) & 1; }
    int ctrlPct() const { return (m_ctrlBits >> 24) & 7; }

    template <size_t N>
    int vlcDecode(const IpuVlc (&table)[N], int *lengthOut);
    int dctVlcDecode(bool intraVlc, bool first, int *run, int *levelMag, bool *negative);
    bool decodeBlockCoeffs(bool intra, int qscale, bool *anyAc);
    void storeLumaBlock(int block, bool fieldDct, const double *px, bool intra);
    void storeChromaBlock(int16_t (*plane)[8], const double *px, bool intra);
    void commitScan();
    bool bdecTailScan();
    void bdecError(const char *what);
    bool execBdec(uint32_t value);
    bool execVdec(uint32_t value);
    void cscOneMacroblock(const MacroBlock8 &mb, uint8_t *rgbaOut);
    bool execCsc(uint32_t value);
    bool execSetiq(uint32_t value);
    bool execSetvq();
    void execBclr(uint32_t value);
    void softReset();
    void takeSnapshot();
    void restoreSnapshot();
    void runPending();
    void serviceInput();
    void commandWrite(uint32_t value);
    void finishWithError(const char *why, uint32_t value);

    Ps2IpuHost &m_host;

    // toIPU (ch4) source state.
    bool m_toActive = false;
    bool m_toChain = false;
    bool m_toTagEnd = false;
    uint64_t m_toKicks = 0;
    uint64_t m_toTags = 0;

    // fromIPU (ch3) state.
    bool m_fromActive = false;
    bool m_fromDrainAll = false;

    // Input bytes resident in the FIFO and decode window. m_inPos is the
    // decode cursor in bits (rewinds when a stalled command retries); m_inHw
    // is the furthest the decoder has actually read, which bounds the DMA.
    std::vector<uint8_t> m_in;
    size_t m_inPos = 0;
    size_t m_inHw = 0;
    bool m_underflow = false;

    std::vector<uint8_t> m_out;
    size_t m_outHead = 0;
    uint64_t m_outProduced = 0;

    uint32_t m_ctrlBits = 0; // IDP/AS/IVF/QST/MP1/PCT as last written
    bool m_ecd = false;
    bool m_scd = false;
    uint32_t m_cbpReg = 0;
    uint32_t m_cmdData = 0;
    uint32_t m_top = 0;
    bool m_busy = false;
    size_t m_stallIn = 0;
    uint32_t m_curCmd = 0;
    uint32_t m_lastCmdCode = 0xFu;

    uint8_t m_iq[64] = {};
    uint8_t m_niq[64] = {};
    uint8_t m_vq[32] = {};
    uint16_t m_th[2] = {0, 0};
    int m_dcpred[3] = {128, 128, 128};

    Snapshot m_snap;
    uint64_t m_cmdCensus[16] = {};
    std::atomic<uint64_t> m_debugCommands{0};
    std::atomic<uint32_t> m_debugLastCommand{0};
    uint32_t m_cscDone = 0;
    bool m_bdecTail = false;
    bool m_bdecTailRun = false;

    int16_t m_dct[64] = {};
    MacroBlock16 m_mb16 = {};
};

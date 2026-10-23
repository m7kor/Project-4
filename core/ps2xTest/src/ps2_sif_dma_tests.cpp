#include "MiniTest.h"
#include "ps2_runtime.h"
#include "ps2_iop_host.h"
#include "ps2_iop_transport.h"
#include "ps2_syscalls.h"
#include "ps2_stubs.h"
#include "Kernel/Stubs/SIF.h"
#include "Kernel/Stubs/iop_reboot_image.h"
#include "runtime/ee_scheduler.h"

#include <array>
#include <cstdint>
#include <cstring>
#include <vector>

namespace ps2_stubs
{
    void resetSifState();
}

namespace
{
    constexpr int KE_OK = 0;

    struct TestEnv
    {
        std::vector<uint8_t> rdram;
        R5900Context ctx{};
        PS2Runtime runtime;

        TestEnv() : rdram(PS2_RAM_SIZE, 0u)
        {
            ps2_stubs::resetSifState();
            std::memset(&ctx, 0, sizeof(ctx));
        }
    };

    #pragma pack(push, 1)
    struct Ps2SifDmaTransfer
    {
        uint32_t src;
        uint32_t dest;
        int32_t size;
        int32_t attr;
    };

    struct SifRpcHeader
    {
        uint32_t pkt_addr;
        uint32_t rpc_id;
        int32_t sema_id;
        uint32_t mode;
    };

    struct SifRpcReceiveData
    {
        SifRpcHeader hdr;
        uint32_t src;
        uint32_t dest;
        int32_t size;
    };
    #pragma pack(pop)

    static_assert(sizeof(Ps2SifDmaTransfer) == 16u, "Unexpected Ps2SifDmaTransfer size.");
    static_assert(sizeof(SifRpcReceiveData) == 28u, "Unexpected SifRpcReceiveData size.");

    void setRegU32(R5900Context &ctx, int reg, uint32_t value)
    {
        ctx.r[reg] = _mm_set_epi64x(0, static_cast<int64_t>(value));
    }

    int32_t getRegS32(const R5900Context &ctx, int reg)
    {
        return static_cast<int32_t>(::getRegU32(&ctx, reg));
    }

    void writeGuestU32(uint8_t *rdram, uint32_t addr, uint32_t value)
    {
        std::memcpy(rdram + addr, &value, sizeof(value));
    }

    uint32_t readGuestU32(const uint8_t *rdram, uint32_t addr)
    {
        uint32_t value = 0;
        std::memcpy(&value, rdram + addr, sizeof(value));
        return value;
    }

    uint32_t g_dmacHandlerWriteAddr = 0u;
    uint32_t g_dmacHandlerValue = 0u;
    uint32_t g_dmacHandlerLastCause = 0u;
    uint32_t g_dmacHandlerLastArg = 0u;
    int32_t g_sifDmaResult = 0;

    constexpr uint32_t kSchedulerSifDmaEntryPc = 0x00101000u;
    constexpr uint32_t kSchedulerSifDmaResumePc = 0x00101010u;
    constexpr uint32_t kSchedulerSifDmaHandlerPc = 0x00101020u;
    constexpr uint32_t kSchedulerSifDmaDescAddr = 0x00020300u;
    constexpr uint32_t kSchedulerSifDmaHandlerArg = 0x12345678u;
    constexpr uint32_t kNativeCmdData = 0x00020800u;
    constexpr uint32_t kNativePacket = 0x00020900u;
    constexpr uint32_t kNativeSreg = 0x00020a00u;
    uint32_t g_sifQueueGuestCalls = 0u;
    bool g_sifQueueReplyReceived = false;
    void sifQueueProgressProbe(uint8_t *rdram, R5900Context *, PS2Runtime *runtime)
    {
        if (++g_sifQueueGuestCalls == 1u)
            writeGuestU32(rdram, kNativePacket, 0u);
        else if (readGuestU32(rdram, kNativePacket) == 16u &&
                 readGuestU32(rdram, kNativePacket + 12u) == 22u)
        {
            g_sifQueueReplyReceived = true;
            runtime->requestStop();
        }
    }

    void nativeSifReceiver(uint8_t *rdram, R5900Context *ctx, PS2Runtime *)
    {
        const uint32_t buffer = readGuestU32(rdram, kNativeCmdData);
        if ((readGuestU32(rdram, buffer) & 0xffu) == 24u &&
            readGuestU32(rdram, buffer + 8u) == 0x80000001u &&
            readGuestU32(rdram, buffer + 16u) == 0u)
            writeGuestU32(rdram, kNativeSreg, readGuestU32(rdram, buffer + 20u));
        writeGuestU32(rdram, buffer, 0u);
        ctx->pc = 0u;
    }

    void testDmacHandler(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        (void)runtime;
        g_dmacHandlerLastCause = ::getRegU32(ctx, 4);
        g_dmacHandlerLastArg = ::getRegU32(ctx, 5);
        if (g_dmacHandlerWriteAddr != 0u)
        {
            writeGuestU32(rdram, g_dmacHandlerWriteAddr, g_dmacHandlerValue);
        }
        ctx->pc = 0u;
    }

    void schedulerSifDmaEntry(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        runtime->eeScheduler().addIrqHandler(true,
                                             5u,
                                             kSchedulerSifDmaHandlerPc,
                                             true,
                                             kSchedulerSifDmaHandlerArg,
                                             0u,
                                             0u);
        setRegU32(*ctx, 4, kSchedulerSifDmaDescAddr);
        setRegU32(*ctx, 5, 1u);
        ctx->pc = kSchedulerSifDmaResumePc;
        ps2_stubs::sceSifSetDma(rdram, ctx, runtime);
    }

    void schedulerSifDmaResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_sifDmaResult = getRegS32(*ctx, 2);
        ctx->pc = 0u;
        runtime->requestStop();
    }
}

void register_ps2_sif_dma_tests()
{
    MiniTest::Case("PS2SifDma", [](TestCase &tc)
    {
        tc.Run("sceSifSetDma copies payload and sceSifDmaStat reports complete", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kDescAddr = 0x00020000u;
            constexpr uint32_t kSrcAddr = 0x00020100u;
            constexpr uint32_t kDstAddr = 0x00020200u;

            std::array<uint8_t, 16> payload{};
            for (size_t i = 0; i < payload.size(); ++i)
            {
                payload[i] = static_cast<uint8_t>(0x30u + i);
            }
            std::memcpy(env.rdram.data() + kSrcAddr, payload.data(), payload.size());
            std::memset(env.rdram.data() + kDstAddr, 0x5A, payload.size());

            const Ps2SifDmaTransfer desc{
                kSrcAddr,
                kDstAddr,
                static_cast<int32_t>(payload.size()),
                0};
            std::memcpy(env.rdram.data() + kDescAddr, &desc, sizeof(desc));

            setRegU32(env.ctx, 4, kDescAddr);
            setRegU32(env.ctx, 5, 1u);
            ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            const int32_t dmaId = getRegS32(env.ctx, 2);
            t.IsTrue(dmaId > 0, "sceSifSetDma should return a positive transfer id on success");

            std::array<uint8_t, 16> iopReadback{};
            t.IsTrue(env.runtime.readIopMemory(kDstAddr, iopReadback.data(), iopReadback.size()) &&
                         iopReadback == payload,
                     "sceSifSetDma should copy EE payload into IOP RAM");
            const std::array<uint8_t, 16> eeSentinel = {
                0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A,
                0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A};
            t.IsTrue(std::memcmp(env.rdram.data() + kDstAddr, eeSentinel.data(), eeSentinel.size()) == 0,
                     "sceSifSetDma must not alias an equal-numbered EE address");

            setRegU32(env.ctx, 4, static_cast<uint32_t>(dmaId));
            ps2_stubs::sceSifDmaStat(env.rdram.data(), &env.ctx, &env.runtime);
            t.IsTrue(getRegS32(env.ctx, 2) < 0, "sceSifDmaStat should be negative when transfer is complete");
        });

        tc.Run("IOP heap DMA uses private backing instead of aliasing EE RDRAM", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kDescAddr = 0x00020040u;
            constexpr uint32_t kSrcAddr = 0x00020140u;
            constexpr uint32_t kRoundTripAddr = 0x00020240u;
            constexpr uint32_t kIopBlockSize = 0x880u;

            std::array<uint8_t, 32> payload{};
            for (size_t i = 0; i < payload.size(); ++i)
            {
                payload[i] = static_cast<uint8_t>(0x80u + i);
            }
            std::memcpy(env.rdram.data() + kSrcAddr, payload.data(), payload.size());
            std::memset(env.rdram.data() + kRoundTripAddr, 0, payload.size());

            setRegU32(env.ctx, 4, kIopBlockSize);
            ps2_stubs::sceSifAllocIopHeap(env.rdram.data(), &env.ctx, &env.runtime);
            const uint32_t iopAddress = ::getRegU32(&env.ctx, 2);
            t.IsTrue(iopAddress >= 0x00120000u && iopAddress < 0x00200000u,
                     "sceSifAllocIopHeap should return an address in physical IOP RAM");
            std::memset(env.rdram.data() + iopAddress, 0x5Au, payload.size());

            Ps2SifDmaTransfer desc{
                kSrcAddr,
                iopAddress,
                static_cast<int32_t>(payload.size()),
                0};
            std::memcpy(env.rdram.data() + kDescAddr, &desc, sizeof(desc));
            setRegU32(env.ctx, 4, kDescAddr);
            setRegU32(env.ctx, 5, 1u);
            ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            t.IsTrue(getRegS32(env.ctx, 2) > 0,
                     "EE-to-IOP DMA should accept a private IOP heap destination");

            const std::array<uint8_t, 32> aliasSentinel{
                0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A,
                0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A,
                0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A,
                0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A};
            t.IsTrue(std::memcmp(env.rdram.data() + iopAddress,
                                 aliasSentinel.data(), aliasSentinel.size()) == 0,
                     "IOP DMA must not overwrite the equal-numbered EE range");

            PS2IopHostAdapter host(env.runtime);
            auto scope = host.enterCall(&env.ctx, env.rdram.data());
            std::array<uint8_t, 32> hostReadback{};
            t.IsTrue(host.readIopMemory(iopAddress, hostReadback.data(), hostReadback.size()) &&
                         hostReadback == payload,
                     "IOP modules should read the shared physical IOP RAM");

            constexpr uint32_t kRdAddr = 0x00020340u;
            setRegU32(env.ctx, 4, kRdAddr);
            setRegU32(env.ctx, 5, iopAddress);
            setRegU32(env.ctx, 6, kRoundTripAddr);
            setRegU32(env.ctx, 7, static_cast<uint32_t>(payload.size()));
            ps2_stubs::sceSifGetOtherData(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), 0,
                     "IOP-to-EE transfer should accept a physical IOP source");
            t.IsTrue(std::memcmp(env.rdram.data() + kRoundTripAddr,
                                 payload.data(), payload.size()) == 0,
                     "IOP-to-EE DMA should round-trip the payload");
        });

        tc.Run("isceSifSetDma and isceSifSetDChain alias the SIF DMA helpers", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kDescAddr = 0x00020240u;
            constexpr uint32_t kSrcAddr = 0x00020340u;
            constexpr uint32_t kDstAddr = 0x00020440u;

            std::array<uint8_t, 12> payload{};
            for (size_t i = 0; i < payload.size(); ++i)
            {
                payload[i] = static_cast<uint8_t>(0x50u + i);
            }
            std::memcpy(env.rdram.data() + kSrcAddr, payload.data(), payload.size());
            std::memset(env.rdram.data() + kDstAddr, 0x5A, payload.size());

            const Ps2SifDmaTransfer desc{
                kSrcAddr,
                kDstAddr,
                static_cast<int32_t>(payload.size()),
                0};
            std::memcpy(env.rdram.data() + kDescAddr, &desc, sizeof(desc));

            setRegU32(env.ctx, 4, kDescAddr);
            setRegU32(env.ctx, 5, 1u);
            ps2_stubs::isceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            t.IsTrue(getRegS32(env.ctx, 2) > 0, "isceSifSetDma should report a successful transfer id");
            std::array<uint8_t, 12> iopReadback{};
            t.IsTrue(env.runtime.readIopMemory(kDstAddr, iopReadback.data(), iopReadback.size()) &&
                         iopReadback == payload,
                     "isceSifSetDma should copy EE payload into IOP RAM");

            ps2_stubs::isceSifSetDChain(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), 0, "isceSifSetDChain should mirror sceSifSetDChain");
        });

        tc.Run("sceSifSetDma dispatches enabled DMAC handlers for cause 5", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kSrcAddr = 0x00020400u;
            constexpr uint32_t kDstAddr = 0x00020500u;
            constexpr uint32_t kHandlerWriteAddr = 0x00020600u;

            g_dmacHandlerWriteAddr = kHandlerWriteAddr;
            g_dmacHandlerValue = 0xCAFEBABEu;
            g_dmacHandlerLastCause = 0u;
            g_dmacHandlerLastArg = 0u;
            g_sifDmaResult = 0;
            env.runtime.registerFunction(kSchedulerSifDmaEntryPc, schedulerSifDmaEntry);
            env.runtime.registerFunction(kSchedulerSifDmaResumePc, schedulerSifDmaResume);
            env.runtime.registerFunction(kSchedulerSifDmaHandlerPc, testDmacHandler);

            std::array<uint8_t, 16> payload{};
            for (size_t i = 0; i < payload.size(); ++i)
            {
                payload[i] = static_cast<uint8_t>(0x40u + i);
            }
            std::memcpy(env.rdram.data() + kSrcAddr, payload.data(), payload.size());

            const Ps2SifDmaTransfer desc{
                kSrcAddr,
                kDstAddr,
                static_cast<int32_t>(payload.size()),
                0};
            std::memcpy(env.rdram.data() + kSchedulerSifDmaDescAddr, &desc, sizeof(desc));

            R5900Context mainContext{};
            mainContext.pc = kSchedulerSifDmaEntryPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            t.IsTrue(g_sifDmaResult > 0, "sceSifSetDma should still report success");
            t.Equals(readGuestU32(env.rdram.data(), kHandlerWriteAddr), g_dmacHandlerValue,
                     "the scheduler should execute the queued DMAC invocation");
            t.Equals(g_dmacHandlerLastCause, 5u, "DMAC handler should observe cause 5");
            t.Equals(g_dmacHandlerLastArg, kSchedulerSifDmaHandlerArg,
                     "DMAC handler should receive registered argument");
        });

        tc.Run("SIF replies wait for a busy receive buffer and retain FIFO packet ownership", [](TestCase &t)
        {
            TestEnv env;
            writeGuestU32(env.rdram.data(), kNativeCmdData, kNativePacket);
            setRegU32(env.ctx, 4, 0x80000001u);
            setRegU32(env.ctx, 5, kNativeCmdData);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);
            R5900Context idle{};
            auto &scheduler = env.runtime.eeScheduler();
            scheduler.reset(env.rdram.data(), idle);
            std::array<uint32_t, 4> first{16u, 0u, 0x80000008u, 11u};
            std::array<uint32_t, 4> second{16u, 0u, 0x80000008u, 22u};
            std::array<uint32_t, 4> third{16u, 0u, 0x80000008u, 33u};
            t.IsTrue(ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, first[2], first.data(), sizeof(first)),
                     "first reply should occupy the receive buffer");
            t.IsTrue(ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, second[2], second.data(), sizeof(second)),
                     "busy buffer must queue the second reply instead of dropping it");
            t.IsTrue(ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, third[2], third.data(), sizeof(third)),
                     "third reply must remain behind the second");
            second[3] = third[3] = 99u;
            std::vector<uint32_t> observed;
            for (uint64_t deadline : {64u, 128u, 192u})
                scheduler.scheduleTransportCompletion(deadline, [&] {
                    observed.push_back(readGuestU32(env.rdram.data(), kNativePacket + 12u));
                    writeGuestU32(env.rdram.data(), kNativePacket, 0u);
                    if (observed.size() == 3u) scheduler.requestStop();
                });
            scheduler.run();
            t.IsTrue(observed == std::vector<uint32_t>({11u, 22u, 33u}),
                     "queued replies must retain their own bytes and preserve order");
        });

        tc.Run("a busy SIF receive buffer must not starve its runnable guest consumer", [](TestCase &t)
        {
            TestEnv env;
            writeGuestU32(env.rdram.data(), kNativeCmdData, kNativePacket);
            writeGuestU32(env.rdram.data(), kNativePacket, 16u);
            setRegU32(env.ctx, 4, 0x80000001u);
            setRegU32(env.ctx, 5, kNativeCmdData);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);
            env.runtime.registerFunction(kSchedulerSifDmaEntryPc, sifQueueProgressProbe);
            R5900Context main{};
            main.pc = kSchedulerSifDmaEntryPc;
            auto &scheduler = env.runtime.eeScheduler();
            scheduler.reset(env.rdram.data(), main);
            g_sifQueueGuestCalls = 0u;
            g_sifQueueReplyReceived = false;
            const std::array<uint32_t, 4> reply{16u, 0u, 0x80000008u, 22u};
            t.IsTrue(ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, reply[2], reply.data(), sizeof(reply)),
                     "reply should wait for the runnable consumer");
            scheduler.scheduleTransportCompletion(4096u, [&] { scheduler.requestStop(); });
            scheduler.run();
            t.IsTrue(g_sifQueueGuestCalls > 0u, "transport retries must leave time for guest execution");
            t.IsTrue(g_sifQueueReplyReceived, "guest must consume the old packet and receive the queued reply");
        });

        tc.Run("native SIF RPC init reaches the registered guest receive buffer", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t packetAddress = 0x00020700u;
            writeGuestU32(env.rdram.data(), kNativeCmdData, kNativePacket);
            writeGuestU32(env.rdram.data(), kNativeCmdData + 8u, 0x1000u);
            setRegU32(env.ctx, 4, 0x80000001u);
            setRegU32(env.ctx, 5, kNativeCmdData);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);
            const std::array<uint32_t, 4u> request{16u, 0u, 0x80000002u, 1u};
            std::memcpy(env.rdram.data() + packetAddress, request.data(), sizeof(request));
            const Ps2SifDmaTransfer descriptor{packetAddress, 0x1000u, 16, 0x44};
            std::memcpy(env.rdram.data() + kSchedulerSifDmaDescAddr, &descriptor, sizeof(descriptor));
            env.runtime.registerFunction(kSchedulerSifDmaEntryPc, schedulerSifDmaEntry);
            env.runtime.registerFunction(kSchedulerSifDmaResumePc, schedulerSifDmaResume);
            env.runtime.registerFunction(kSchedulerSifDmaHandlerPc, nativeSifReceiver);
            t.Equals(readGuestU32(env.rdram.data(), kNativeSreg), 0u, "RPC must not be ready before the request");
            R5900Context mainContext{};
            mainContext.pc = kSchedulerSifDmaEntryPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();
            t.Equals(readGuestU32(env.rdram.data(), kNativeSreg), 1u,
                     "SET_SREG reply must execute through the guest SIF0 receiver");
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket), 0u,
                     "receiver must consume the packet");
        });

        tc.Run("SIF RPC init ignores ordinary DMA and malformed command packets", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t packetAddress = 0x00020700u;
            writeGuestU32(env.rdram.data(), kNativeCmdData, kNativePacket);
            writeGuestU32(env.rdram.data(), kNativeCmdData + 8u, 0x1000u);
            setRegU32(env.ctx, 4, 0x80000001u);
            setRegU32(env.ctx, 5, kNativeCmdData);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);
            for (const auto request : {std::array<uint32_t, 4u>{16u, 0u, 0x80000002u, 0u},
                                       std::array<uint32_t, 4u>{15u, 0u, 0x80000002u, 1u},
                                       std::array<uint32_t, 4u>{0x110u, 0u, 0x80000002u, 1u},
                                       std::array<uint32_t, 4u>{16u, 0u, 0x80000003u, 1u}})
            {
                std::memcpy(env.rdram.data() + packetAddress, request.data(), sizeof(request));
                const Ps2SifDmaTransfer descriptor{packetAddress, 0x1000u, 16, 0x44};
                std::memcpy(env.rdram.data() + kSchedulerSifDmaDescAddr, &descriptor, sizeof(descriptor));
                setRegU32(env.ctx, 4, kSchedulerSifDmaDescAddr);
                setRegU32(env.ctx, 5, 1u);
                ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
                t.Equals(readGuestU32(env.rdram.data(), kNativePacket), 0u,
                         "non-init or invalid packets must not generate a reply");
            }
            const std::array<uint32_t, 4u> request{16u, 0u, 0x80000002u, 1u};
            std::memcpy(env.rdram.data() + packetAddress, request.data(), sizeof(request));
            const Ps2SifDmaTransfer descriptor{packetAddress, 0x1000u, 16, 0};
            std::memcpy(env.rdram.data() + kSchedulerSifDmaDescAddr, &descriptor, sizeof(descriptor));
            setRegU32(env.ctx, 4, kSchedulerSifDmaDescAddr);
            setRegU32(env.ctx, 5, 1u);
            ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket), 0u, "ordinary DMA must not be decoded as SIFCMD");
            const Ps2SifDmaTransfer wrongDestination{packetAddress, 0x1100u, 16, 0x44};
            std::memcpy(env.rdram.data() + kSchedulerSifDmaDescAddr, &wrongDestination, sizeof(wrongDestination));
            setRegU32(env.ctx, 4, kSchedulerSifDmaDescAddr);
            setRegU32(env.ctx, 5, 1u);
            ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket), 0u,
                     "an init-shaped payload outside the command buffer must not generate a reply");
            const std::array<uint32_t, 6u> reply{24u, 0u, 0x80000001u, 0u, 0u, 1u};
            writeGuestU32(env.rdram.data(), kNativePacket, 24u);
            std::array<uint8_t, 128> occupiedBytes{};
            std::memcpy(occupiedBytes.data(), env.rdram.data() + kNativePacket, occupiedBytes.size());
            t.IsTrue(ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, reply[2], reply.data(), sizeof(reply)),
                     "a valid reply must wait behind the pending guest packet");
            t.IsTrue(std::memcmp(occupiedBytes.data(), env.rdram.data() + kNativePacket, occupiedBytes.size()) == 0,
                     "queueing must preserve every byte of the unconsumed guest packet");
            for (const uint32_t invalidBuffer : {0u, PS2_RAM_SIZE - 64u, 0xe0000000u, 0x10000000u})
            {
                writeGuestU32(env.rdram.data(), kNativeCmdData, invalidBuffer);
                t.IsTrue(!ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, reply[2], reply.data(), sizeof(reply)),
                         "invalid or truncated receive buffers must be rejected");
            }
        });

        tc.Run("native RPC bind and CD init preserve packet identity and private IOP buffers", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t requestAddress = 0x00020700u;
            constexpr uint32_t clientAddress = 0x00020b00u;
            constexpr uint32_t receiveAddress = 0x00020c00u;
            writeGuestU32(env.rdram.data(), kNativeCmdData, kNativePacket);
            writeGuestU32(env.rdram.data(), kNativeCmdData + 8u, 0x1000u);
            setRegU32(env.ctx, 4, 0x80000001u);
            setRegU32(env.ctx, 5, kNativeCmdData);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);
            auto send = [&](const std::array<uint32_t, 16u> &packet)
            {
                std::memcpy(env.rdram.data() + requestAddress, packet.data(), sizeof(packet));
                const Ps2SifDmaTransfer descriptor{requestAddress, 0x1000u, 64, 0x44};
                std::memcpy(env.rdram.data() + kSchedulerSifDmaDescAddr, &descriptor, sizeof(descriptor));
                setRegU32(env.ctx, 4, kSchedulerSifDmaDescAddr);
                setRegU32(env.ctx, 5, 1u);
                ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            };
            std::array<uint32_t, 16u> request{64u, 0u, 0x80000009u, 0u, 5u,
                                             requestAddress, 2u, clientAddress, 0x80000592u};
            send(request);
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket + 8u), 0x80000008u, "bind must return RPC_END");
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket + 24u), 2u, "rpc_id must match the request");
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket + 28u), clientAddress, "client address must match");
            const uint32_t server = readGuestU32(env.rdram.data(), kNativePacket + 36u);
            const uint32_t buffer = readGuestU32(env.rdram.data(), kNativePacket + 40u);
            t.IsTrue(server != 0u && buffer != 0u, "CD init must bind to the actual IOP CDVD provider");
            const uint32_t gameBuffer = env.runtime.guestMalloc(32768u, 64u);
            env.runtime.guestFree(gameBuffer);
            std::memset(env.rdram.data() + gameBuffer, 0x5Au, 32768u);
            const uint32_t mode = 0u;
            t.IsTrue(env.runtime.writeIopMemory(buffer, &mode, 4u), "server input must reside in IOP RAM");
            writeGuestU32(env.rdram.data(), kNativePacket, 0u);
            request[2] = 0x8000000au;
            request[0] = 64u | (4u << 8u);
            request[1] = buffer;
            request[8] = 0u;
            request[9] = 4u;
            request[10] = receiveAddress;
            request[11] = 16u;
            request[12] = 1u;
            request[13] = server;
            send(request);
            bool gameBufferPreserved = true;
            for (uint32_t offset = 0; offset < 32768u; ++offset)
                gameBufferPreserved &= env.rdram[gameBuffer + offset] == 0x5Au;
            t.IsTrue(gameBufferPreserved, "RPC scratch must not overwrite native game allocations");
            t.Equals(env.runtime.nativeRpcScratch(), env.runtime.nativeRpcScratch(), "scratch reservation is reused");
            t.Equals(readGuestU32(env.rdram.data(), receiveAddress), 1u, "CD init must return its backend result");
            t.Equals(readGuestU32(env.rdram.data(), receiveAddress + 4u), 0u, "native provider must not invent an IRX version");
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket + 32u), 0x8000000au, "call completion must identify the original command");
            writeGuestU32(env.rdram.data(), kNativePacket, 0u);
            request[2] = 0x80000009u;
            request[0] = 64u;
            request[1] = 0u;
            request[8] = 0xdeadbeefu;
            send(request);
            t.Equals(readGuestU32(env.rdram.data(), kNativePacket + 36u), 0u, "unknown service must return a null server");
            ps2_stubs::sceSifExitCmd(env.rdram.data(), &env.ctx, &env.runtime);
            t.IsTrue(!env.runtime.freeIopMemory(server),
                     "exit must have already released the transport-owned allocation");
        });

        tc.Run("IOPRP ROMDIR parser validates file extents before returning modules", [](TestCase &t)
        {
            std::vector<uint8_t> image(100u, 0u);
            const auto entry = [&](uint32_t index, const char *name, uint32_t size)
            {
                std::memcpy(image.data() + index * 16u, name, std::strlen(name));
                std::memcpy(image.data() + index * 16u + 12u, &size, 4u);
            };
            entry(0u, "RESET", 0u);
            entry(1u, "ROMDIR", 80u);
            entry(2u, "EXTINFO", 16u);
            entry(3u, "FILEIO", 4u);
            std::vector<ps2_stubs::detail::RebootImageFile> files;
            t.IsTrue(ps2_stubs::detail::parseRebootImage(image, files), "a bounded ROMDIR image must parse");
            t.Equals(files.size(), size_t(4u), "metadata and module entries must be returned");
            t.Equals(files.back().offset, 96u, "module offset must follow 16-byte-aligned preceding files");
            image.resize(99u);
            t.IsTrue(!ps2_stubs::detail::parseRebootImage(image, files) && files.empty(),
                     "a truncated module must not return a partial file list");
            image.resize(100u);
            const uint32_t huge = 0xffffffffu;
            std::memcpy(image.data() + 60u, &huge, 4u);
            t.IsTrue(!ps2_stubs::detail::parseRebootImage(image, files), "oversized extents must be rejected");
        });

        tc.Run("SIF SMFLAG writes clear selected bits instead of replacing status", [](TestCase &t)
        {
            TestEnv env;
            setRegU32(env.ctx, 4, 4u);
            setRegU32(env.ctx, 5, 0x10000u);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);
            setRegU32(env.ctx, 4, 4u);
            ps2_stubs::sceSifGetReg(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(::getRegU32(&env.ctx, 2), 0x20000u, "clearing SIFINIT must preserve CMDINIT");
            setRegU32(env.ctx, 4, 4u);
            setRegU32(env.ctx, 5, 0x20000u);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);
            setRegU32(env.ctx, 4, 4u);
            ps2_stubs::sceSifGetReg(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(::getRegU32(&env.ctx, 2), 0u, "clearing CMDINIT must remove only that bit");
        });

        tc.Run("resetSifState seeds boot-ready SIF registers", [](TestCase &t)
        {
            TestEnv env;

            auto getReg = [&](uint32_t reg) -> uint32_t
            {
                setRegU32(env.ctx, 4, reg);
                ps2_stubs::sceSifGetReg(env.rdram.data(), &env.ctx, &env.runtime);
                return ::getRegU32(&env.ctx, 2);
            };

            t.Equals(getReg(0x4u), 0x00020000u, "SIF boot status register should expose ready bit by default");
            t.Equals(getReg(0x80000000u), 0u, "SIF IOP command address should default to zero");
            t.Equals(getReg(0x80000001u), 0u, "SIF EE command-data address should default to zero");
            t.Equals(getReg(0x80000002u), 0u, "SIF RPC-init marker should default to zero");
        });

        tc.Run("sceSifExitCmd restores default boot-ready SIF registers", [](TestCase &t)
        {
            TestEnv env;

            setRegU32(env.ctx, 4, 0x4u);
            setRegU32(env.ctx, 5, 0x12340000u);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);

            setRegU32(env.ctx, 4, 0x80000002u);
            setRegU32(env.ctx, 5, 0x89ABCDEFu);
            ps2_stubs::sceSifSetReg(env.rdram.data(), &env.ctx, &env.runtime);

            ps2_stubs::sceSifExitCmd(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), 0, "sceSifExitCmd should succeed");

            auto getReg = [&](uint32_t reg) -> uint32_t
            {
                setRegU32(env.ctx, 4, reg);
                ps2_stubs::sceSifGetReg(env.rdram.data(), &env.ctx, &env.runtime);
                return ::getRegU32(&env.ctx, 2);
            };

            t.Equals(getReg(0x4u), 0x00020000u, "sceSifExitCmd should restore the boot-ready status bit");
            t.Equals(getReg(0x80000002u), 0u, "sceSifExitCmd should clear transient mscom state");
        });

        tc.Run("sceSifSetDma rejects invalid descriptors without partial writes", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kDescAddr = 0x00021000u;
            constexpr uint32_t kSrcA = 0x00021100u;
            constexpr uint32_t kDstA = 0x00021200u;
            constexpr uint32_t kSrcB = 0x00021300u;
            constexpr uint32_t kInvalidDstB = 0xE0000100u; // unsupported guest segment

            std::array<uint8_t, 8> payloadA{};
            for (size_t i = 0; i < payloadA.size(); ++i)
            {
                payloadA[i] = static_cast<uint8_t>(0x70u + i);
            }
            std::array<uint8_t, 8> payloadB{};
            for (size_t i = 0; i < payloadB.size(); ++i)
            {
                payloadB[i] = static_cast<uint8_t>(0x90u + i);
            }

            std::memcpy(env.rdram.data() + kSrcA, payloadA.data(), payloadA.size());
            std::memcpy(env.rdram.data() + kSrcB, payloadB.data(), payloadB.size());
            std::memset(env.rdram.data() + kDstA, 0x5Au, payloadA.size());

            const Ps2SifDmaTransfer descs[2] = {
                {kSrcA, kDstA, static_cast<int32_t>(payloadA.size()), 0},
                {kSrcB, kInvalidDstB, static_cast<int32_t>(payloadB.size()), 0}};
            std::memcpy(env.rdram.data() + kDescAddr, descs, sizeof(descs));

            setRegU32(env.ctx, 4, kDescAddr);
            setRegU32(env.ctx, 5, 2u);
            ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), 0, "sceSifSetDma should fail when any descriptor is invalid");

            const std::array<uint8_t, 8> expectedUnchanged{
                0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A, 0x5A};
            t.IsTrue(std::memcmp(env.rdram.data() + kDstA, expectedUnchanged.data(), expectedUnchanged.size()) == 0,
                     "failed multi-descriptor sceSifSetDma should not partially write earlier descriptors");
        });

        tc.Run("sceSifSetDma enforces descriptor count limit", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kDescAddr = 0x00022000u;

            setRegU32(env.ctx, 4, kDescAddr);
            setRegU32(env.ctx, 5, 33u);
            ps2_stubs::sceSifSetDma(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), 0, "sceSifSetDma should reject count > 32");
        });

        tc.Run("sceSifGetOtherData copies payload and writes receive metadata", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kRdAddr = 0x00023000u;
            constexpr uint32_t kSrcAddr = 0x00023100u;
            constexpr uint32_t kDstAddr = 0x00023200u;
            constexpr uint32_t kSize = 20u;

            std::array<uint8_t, kSize> payload{};
            for (size_t i = 0; i < payload.size(); ++i)
            {
                payload[i] = static_cast<uint8_t>((i * 7u) & 0xFFu);
            }
            t.IsTrue(env.runtime.writeIopMemory(kSrcAddr, payload.data(), payload.size()),
                     "test setup should populate physical IOP RAM");
            std::memset(env.rdram.data() + kDstAddr, 0, payload.size());
            std::memset(env.rdram.data() + kRdAddr, 0, sizeof(SifRpcReceiveData));

            setRegU32(env.ctx, 4, kRdAddr);
            setRegU32(env.ctx, 5, kSrcAddr);
            setRegU32(env.ctx, 6, kDstAddr);
            setRegU32(env.ctx, 7, kSize);
            ps2_stubs::sceSifGetOtherData(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), 0, "sceSifGetOtherData should succeed for valid transfer");

            t.IsTrue(std::memcmp(env.rdram.data() + kDstAddr, payload.data(), payload.size()) == 0,
                     "sceSifGetOtherData should copy payload");

            const SifRpcReceiveData rd = *reinterpret_cast<const SifRpcReceiveData *>(env.rdram.data() + kRdAddr);
            t.Equals(rd.src, kSrcAddr, "receive metadata src should be populated");
            t.Equals(rd.dest, kDstAddr, "receive metadata dest should be populated");
            t.Equals(static_cast<uint32_t>(rd.size), kSize, "receive metadata size should be populated");
        });

        tc.Run("sceSifGetOtherData rejects unsupported guest segments", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kRdAddr = 0x00024000u;
            constexpr uint32_t kDstAddr = 0x00024100u;
            constexpr uint32_t kInvalidSrcAddr = 0xE0000200u;
            constexpr uint32_t kSize = 16u;

            std::memset(env.rdram.data() + kDstAddr, 0xA5, kSize);
            writeGuestU32(env.rdram.data(), kRdAddr + 0x10u, 0x11111111u);
            writeGuestU32(env.rdram.data(), kRdAddr + 0x14u, 0x22222222u);
            writeGuestU32(env.rdram.data(), kRdAddr + 0x18u, 0x33333333u);

            setRegU32(env.ctx, 4, kRdAddr);
            setRegU32(env.ctx, 5, kInvalidSrcAddr);
            setRegU32(env.ctx, 6, kDstAddr);
            setRegU32(env.ctx, 7, kSize);
            ps2_stubs::sceSifGetOtherData(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), -1, "sceSifGetOtherData should fail for unsupported source segment");

            std::array<uint8_t, kSize> expected{};
            expected.fill(0xA5u);
            t.IsTrue(std::memcmp(env.rdram.data() + kDstAddr, expected.data(), expected.size()) == 0,
                     "failed sceSifGetOtherData should not modify destination");
            t.Equals(readGuestU32(env.rdram.data(), kRdAddr + 0x10u), 0x11111111u,
                     "failed sceSifGetOtherData should not overwrite rd metadata");
        });
    });
}

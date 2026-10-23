#include "System.h"
#include "Common.h"
#include "ps2_runtime.h"
#include "runtime/ee_scheduler.h"

namespace
{
    struct Deci2Session
    {
        uint16_t protocol = 0;
        uint32_t opt = 0;
        uint32_t handler = 0;
        uint32_t userArea = 0;
        bool locked = false;
        bool pending = false;
        bool dispatching = false;
        bool accepted = false;
        uint32_t gp = 0;
        PS2Runtime *owner = nullptr;
    };

    std::mutex g_deci2Mutex;
    std::unordered_map<int32_t, Deci2Session> g_deci2Sessions;
    int32_t g_nextDeci2Socket = 1;
    std::atomic<uint32_t> g_deci2LogCount{0};

    static bool readDeci2U32(uint8_t *rdram, uint32_t guestAddr, uint32_t &value)
    {
        value = 0;

        const uint32_t physical = guestAddr & 0x1FFFFFFFu;
        if (!rdram || physical > PS2_RAM_SIZE - sizeof(value)) return false;
        const uint8_t *ptr = rdram + physical;
        if (!ptr)
        {
            return false;
        }

        std::memcpy(&value, ptr, sizeof(value));
        return true;
    }

    static bool readDeci2Args(uint8_t *rdram, uint32_t argsAddr, uint32_t args[4], uint32_t count)
    {
        for (uint32_t argIndex = 0; argIndex < count; argIndex++)
        {
            uint32_t value = 0;
            if (!readDeci2U32(rdram, argsAddr + (argIndex * sizeof(uint32_t)), value)) return false;
            args[argIndex] = value;
        }
        return true;
    }

    static std::string sanitizeDeci2Text(std::string text)
    {
        for (char &ch : text)
        {
            const unsigned char value = static_cast<unsigned char>(ch);
            if (ch == '\r')
            {
                ch = '\n';
                continue;
            }

            if (ch != '\n' && ch != '\t' && !std::isprint(value))
            {
                ch = '.';
            }
        }

        return text;
    }

    static void logDeci2Text(const char *prefix, const std::string &text)
    {
        constexpr uint32_t kMaxDeci2TextLogs = 256u;
        const uint32_t logIndex = g_deci2LogCount.fetch_add(1u, std::memory_order_relaxed);
        if (logIndex >= kMaxDeci2TextLogs)
        {
            return;
        }

        const std::string safeText = sanitizeDeci2Text(text);
        std::cerr << prefix << safeText;
        if (safeText.empty() || safeText.back() != '\n')
        {
            std::cerr << std::endl;
        }
    }

    static int32_t allocateDeci2Socket(uint16_t protocol, uint32_t opt, uint32_t handler, uint32_t userArea, uint32_t gp, PS2Runtime *owner)
    {
        std::lock_guard<std::mutex> lock(g_deci2Mutex);

        if (g_nextDeci2Socket <= 0)
        {
            g_nextDeci2Socket = 1;
        }

        const int32_t socket = g_nextDeci2Socket++;
        Deci2Session session;
        session.protocol = protocol;
        session.opt = opt;
        session.handler = handler;
        session.userArea = userArea;
        session.locked = false;
        session.gp = gp;
        session.owner = owner;

        g_deci2Sessions[socket] = session;
        return socket;
    }

    static bool updateDeci2LockState(int32_t socket, bool locked, PS2Runtime *owner)
    {
        std::lock_guard<std::mutex> lock(g_deci2Mutex);

        auto sessionIt = g_deci2Sessions.find(socket);
        if (sessionIt == g_deci2Sessions.end() || sessionIt->second.owner != owner)
        {
            return false;
        }

        sessionIt->second.locked = locked;
        return true;
    }

    static bool closeDeci2Socket(int32_t socket, PS2Runtime *owner)
    {
        std::lock_guard<std::mutex> lock(g_deci2Mutex);
        auto it = g_deci2Sessions.find(socket);
        if (it == g_deci2Sessions.end() || it->second.owner != owner) return false;
        g_deci2Sessions.erase(it);
        return true;
    }
}

namespace ps2_syscalls
{
    void resetDeci2State(PS2Runtime *runtime)
    {
        std::lock_guard lock(g_deci2Mutex);
        std::erase_if(g_deci2Sessions, [runtime](const auto &item) { return item.second.owner == runtime; });
    }

    void Deci2Call(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {

        const int32_t code = static_cast<int32_t>(getRegU32(ctx, 4));
        const uint32_t argsAddr = getRegU32(ctx, 5);

        uint32_t args[4] = {};
        const uint32_t count = code == 1 ? 4u : (code == -5 || code == -6 ? 3u : (code == 3 || code == -7 ? 2u : 1u));
        if (!readDeci2Args(rdram, argsAddr, args, count))
        { setReturnS32(ctx, -5); return; }

        switch (code)
        {
        case 1: // sceDeci2Open(protocol, opt, handler)
        {
            const uint16_t protocol = static_cast<uint16_t>(args[0] & 0xFFFFu);
            const uint32_t opt = args[1];
            const uint32_t handler = args[2];
            const uint32_t userArea = args[3];

            const int32_t socket = allocateDeci2Socket(protocol, opt, handler, userArea, getRegU32(ctx, 28), runtime);
            setReturnS32(ctx, socket);
            return;
        }
        case 2: // sceDeci2Close(socket)
        {
            const int32_t socket = static_cast<int32_t>(args[0]);
            setReturnS32(ctx, closeDeci2Socket(socket, runtime) ? KE_OK : KE_ERROR);
            return;
        }
        case 3: // ReqSend
        case -7: // ExReqSend
        {
            std::lock_guard lock(g_deci2Mutex);
            auto it = g_deci2Sessions.find(static_cast<int32_t>(args[0]));
            if (it == g_deci2Sessions.end() || it->second.owner != runtime)
                setReturnS32(ctx, -2);
            else if (it->second.pending)
                setReturnS32(ctx, -7);
            else
            {
                it->second.pending = true;
                it->second.accepted = false;
                setReturnS32(ctx, KE_OK);
            }
            return;
        }
        case 4: // Poll: service a pending write through the guest's handler.
        {
            const int32_t socket = static_cast<int32_t>(args[0]);
            Deci2Session session;
            {
                std::lock_guard lock(g_deci2Mutex);
                auto it = g_deci2Sessions.find(socket);
                if (it == g_deci2Sessions.end() || it->second.owner != runtime)
                { setReturnS32(ctx, -2); return; }
                if (!it->second.pending || it->second.dispatching)
                { setReturnS32(ctx, KE_OK); return; }
                session = it->second;
                if (!runtime || !runtime->hasFunction(session.handler))
                { setReturnS32(ctx, -5); return; }
                it->second.dispatching = true;
            }
            GuestInvocation write{};
            write.kind = GuestInvocationKind::HleCall;
            write.context = *ctx;
            write.context.pc = session.handler;
            SET_GPR_U32(&write.context, 4, 3u); // DECI2_WRITE
            SET_GPR_U32(&write.context, 5, 0u);
            SET_GPR_U32(&write.context, 6, session.opt);
            SET_GPR_U32(&write.context, 28, session.gp);
            SET_GPR_U32(&write.context, 29, 0u);
            SET_GPR_U32(&write.context, 31, 0u);
            write.onComplete = [runtime, socket, session](const R5900Context &, R5900Context &)
            {
                {
                    std::lock_guard lock(g_deci2Mutex);
                    auto it = g_deci2Sessions.find(socket);
                    if (it == g_deci2Sessions.end() || it->second.owner != runtime) return;
                    it->second.dispatching = false;
                    if (!it->second.accepted) return;
                    it->second.pending = false;
                }
                GuestInvocation done{};
                done.kind = GuestInvocationKind::HleCall;
                done.context.pc = session.handler;
                SET_GPR_U32(&done.context, 4, 4u); // DECI2_WRITE_DONE
                SET_GPR_U32(&done.context, 6, session.opt);
                SET_GPR_U32(&done.context, 28, session.gp);
                runtime->eeScheduler().queueInvocation(std::move(done));
            };
            runtime->eeScheduler().queueInvocation(std::move(write));
            setReturnS32(ctx, KE_OK);
            return;
        }
        case -5: // sceDeci2ExRecv(socket, buf, len)
        {
            // No host debugger channel is attached, so report "no bytes available".
            setReturnS32(ctx, 0);
            return;
        }
        case -6: // sceDeci2ExSend(socket, buf, len)
        {
            const uint32_t bufferAddr = args[1];
            const uint32_t length = args[2] & 0xFFFFu;
            uint32_t physical = bufferAddr & 0x1FFFFFFFu;
            if (physical >= PS2_RAM_SIZE || length > PS2_RAM_SIZE - physical)
            { setReturnS32(ctx, -5); return; }
            {
                std::lock_guard lock(g_deci2Mutex);
                auto it = g_deci2Sessions.find(static_cast<int32_t>(args[0]));
                if (it == g_deci2Sessions.end() || it->second.owner != runtime)
                { setReturnS32(ctx, -2); return; }
                it->second.accepted = true;
            }
            logDeci2Text("[Deci2Call:send] ", std::string(reinterpret_cast<char *>(rdram + physical), length));
            setReturnS32(ctx, static_cast<int32_t>(length));
            return;
        }
        case -8: // sceDeci2ExLock(socket)
        {
            const int32_t socket = static_cast<int32_t>(args[0]);
            setReturnS32(ctx, updateDeci2LockState(socket, true, runtime) ? KE_OK : KE_ERROR);
            return;
        }
        case -9: // sceDeci2ExUnLock(socket)
        {
            const int32_t socket = static_cast<int32_t>(args[0]);
            setReturnS32(ctx, updateDeci2LockState(socket, false, runtime) ? KE_OK : KE_ERROR);
            return;
        }
        case 16: // kputs(char *s)
        {
            constexpr size_t kMaxDeci2KputsBytes = 4096u;
            const uint32_t textAddr = args[0];
            const std::string text = readGuestCStringBounded(rdram, textAddr, kMaxDeci2KputsBytes);

            logDeci2Text("[Deci2Call:kputs] ", text);
            setReturnS32(ctx, static_cast<int32_t>(text.size()));
            return;
        }
        default:
        {
            static std::atomic<uint32_t> s_unknownDeci2Logs{0u};
            constexpr uint32_t kMaxUnknownDeci2Logs = 64u;
            const uint32_t logIndex = s_unknownDeci2Logs.fetch_add(1u, std::memory_order_relaxed);
            if (logIndex < kMaxUnknownDeci2Logs)
            {
                std::cerr << "[Deci2Call:unknown]"
                          << " code=" << code
                          << " args=0x" << std::hex << argsAddr
                          << " a0=0x" << args[0]
                          << " a1=0x" << args[1]
                          << " a2=0x" << args[2]
                          << " a3=0x" << args[3]
                          << " pc=0x" << ctx->pc
                          << std::dec << std::endl;
            }

            setReturnS32(ctx, KE_OK);
            return;
        }
        }
    }
}

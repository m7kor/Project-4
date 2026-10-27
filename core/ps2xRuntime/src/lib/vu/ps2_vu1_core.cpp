#include <string>
#include <bit>
#include "runtime/ps2_vu1.h"
#include "runtime/gs/ps2_gif_arbiter.h"
#include "runtime/gs/gs_frontend.h"
#include "runtime/ps2_memory.h"
#include "ps2_vu1_detail.h"

static const VU1Interpreter::CompiledPairFn *vu1FindCompiledProgram(uint64_t hash);
extern uint64_t g_vu1QueueCounts[7];
extern thread_local bool g_vu1CommandGifCollect;
extern thread_local uint64_t g_vu1CommandGifHash, g_vu1CommandGifPackets;
uint64_t g_vu1CompiledBlockEntries = 0, g_vu1CompiledBlockSteps = 0;
uint64_t g_vu1CompiledDeadFmac = 0;

#include <algorithm>
#if defined(_WIN32) && (defined(_M_X64) || defined(__x86_64__))
#include <xmmintrin.h>
#endif
#include <cfenv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <limits>
#include <ps2_log.h>

#if defined(_M_X64) || defined(__x86_64__) || defined(__SSE2__)
#include <emmintrin.h>
#define PS2X_FMAC_CLASSIFY_SSE2 1
#endif

// Batch ONLY the existing exponent2..253 shortcut. No arithmetic or rounding.
// Boundary exponents and any exceptional selected lane use the original path.
bool ps2Vu1ClassifyNormalFmac(const float *value, uint8_t dest, uint8_t laneFlags[4])
{
    dest &= 15u;
    if (!dest) { std::memset(laneFlags, 0, 4); return true; }
#if defined(PS2X_FMAC_CLASSIFY_SSE2)
    static constexpr uint8_t reversed[16] = {0,8,4,12,2,10,6,14,1,9,5,13,3,11,7,15};
    static constexpr uint32_t signFlags[16] = {0x00000000u, 0x00000002u, 0x00000200u, 0x00000202u, 0x00020000u, 0x00020002u, 0x00020200u, 0x00020202u, 0x02000000u, 0x02000002u, 0x02000200u, 0x02000202u, 0x02020000u, 0x02020002u, 0x02020200u, 0x02020202u};
    const uint32_t selected = reversed[dest];
    const __m128 bits = _mm_loadu_ps(value);
    const __m128i magnitude = _mm_and_si128(_mm_castps_si128(bits), _mm_set1_epi32(0x7fffffff));
    const __m128i lower = _mm_cmpgt_epi32(magnitude, _mm_set1_epi32(0x00ffffff));
    const __m128i upper = _mm_cmpgt_epi32(_mm_set1_epi32(0x7f000000), magnitude);
    const uint32_t normal = static_cast<uint32_t>(_mm_movemask_ps(_mm_castsi128_ps(_mm_and_si128(lower, upper))));
    if ((normal & selected) != selected) return false;
    const uint32_t packed = signFlags[static_cast<uint32_t>(_mm_movemask_ps(bits)) & selected];
    std::memcpy(laneFlags, &packed, 4);
    return true;
#else
    uint8_t flags[4]{};
    for (uint32_t component = 0; component < 4; ++component)
    {
        if (!(dest & (8u >> component))) continue;
        uint32_t bits;std::memcpy(&bits, value + component, sizeof(bits));
        const uint32_t exponent=(bits >> 23)&255u;
        if (exponent < 2u || exponent > 253u) return false;
        flags[component]=static_cast<uint8_t>((bits >> 30)&2u);
    }
    std::memcpy(laneFlags,flags,4);return true;
#endif
}
static const bool fmacClassifyEnabled = [] {
    const char *value = std::getenv("PS2X_VU1_FMAC_CLASSIFY");
    return value && *value == '1';
}();

// Internal algebra shared with an exhaustive unit witness; no public header.
// Read only selected lanes and preserve all status bits from the old path.
uint64_t ps2Vu1PackFmacFlags(const uint8_t laneFlags[4], uint8_t dest)
{
    static constexpr uint16_t spread[16] = {
        0x0000, 0x0001, 0x0010, 0x0011, 0x0100, 0x0101, 0x0110, 0x0111,
        0x1000, 0x1001, 0x1010, 0x1011, 0x1100, 0x1101, 0x1110, 0x1111};
    const uint32_t x = dest & 8u ? laneFlags[0] : 0u;
    const uint32_t y = dest & 4u ? laneFlags[1] : 0u;
    const uint32_t z = dest & 2u ? laneFlags[2] : 0u;
    const uint32_t w = dest & 1u ? laneFlags[3] : 0u;
    const uint32_t mac = (uint32_t(spread[x & 15u]) << 3) |
                         (uint32_t(spread[y & 15u]) << 2) |
                         (uint32_t(spread[z & 15u]) << 1) | spread[w & 15u];
    return mac | (uint64_t(x | y | z | w) << 32);
}

namespace
{
    const bool scanAllocationSlots = [] {
        const char *value = std::getenv("PS2X_VU1_ALLOC_SCAN");
        return value && *value == '1';
    }();

    template <typename Entry, size_t Count>
    Entry *firstFreePipelineSlot(std::array<Entry, Count> &slots, uint32_t pending)
    {
        static_assert(Count > 0 && Count <= 32);
        if (scanAllocationSlots)
        {
            for (Entry &entry : slots)
                if (!entry.valid) return &entry;
            return nullptr;
        }
        constexpr uint32_t mask = UINT32_MAX >> (32u - Count);
        const uint32_t free = ~pending & mask;
        return free ? &slots[std::countr_zero(free)] : nullptr;
    }

    constexpr uint8_t laneForComponent(uint32_t component)
    {
        return static_cast<uint8_t>(1u << (3u - component));
    }
}

void VU1Interpreter::addVfRead(InstructionUsage &usage, uint8_t reg, uint8_t lanes)
{
    if (lanes == 0u)
        return;
    for (uint32_t index = 0; index < usage.vfReadCount; ++index)
    {
        if (usage.vfRead[index].reg == reg)
        {
            usage.vfRead[index].lanes |= lanes;
            return;
        }
    }
    if (usage.vfReadCount < usage.vfRead.size())
        usage.vfRead[usage.vfReadCount++] = {reg, lanes};
}

void VU1Interpreter::addVfWrite(InstructionUsage &usage, uint8_t reg, uint8_t lanes)
{
    if (reg == 0u || lanes == 0u)
        return;
    if (usage.vfWrite.reg == 0u)
        usage.vfWrite = {reg, lanes};
    else if (usage.vfWrite.reg == reg)
        usage.vfWrite.lanes |= lanes;
}

uint8_t VU1Interpreter::vfReadLanes(const InstructionUsage &usage, uint8_t reg)
{
    for (uint32_t index = 0; index < usage.vfReadCount; ++index)
    {
        if (usage.vfRead[index].reg == reg)
            return usage.vfRead[index].lanes;
    }
    return 0u;
}

VU1Interpreter::VU1Interpreter(Unit unit)
    : m_unit(unit)
{
    reset();
}

void VU1Interpreter::resetScheduler()
{
    m_flagPipeline = {};
    m_fdiv = {};
    m_efu = {};
    m_storePipeline = {};
    m_vfWritePipeline = {};
    m_viWritePipeline = {};
    m_accWritePipeline = {};
    m_flagPending = m_efuPending = m_storePending = m_vfPending = m_viPending = m_accPending = 0u;
    m_nextCommitCycle = 0u;
    m_maxPendingReady = 0u;
    m_xgkick.resetTransfer();
    m_vfReady = {};
    m_viReady = {};
    m_accReady = {};
    m_vfLatestWrite = {};
    m_viLatestWrite = {};
    m_accLatestWrite = {};
    m_nextWriteSequence = 0;
    m_efuResourceReady = 0;
    m_workingClip = m_state.clip;
    m_viBranchBackupValue = 0;
    m_viBranchBackupReg = 0;
    m_viBranchBackupValid = false;
    m_stopRequested = false;
    m_pendingHaltD = false;
    m_pendingHaltT = false;
}

void VU1Interpreter::reset()
{
    std::memset(&m_state, 0, sizeof(m_state));
    m_state.vf[0][3] = 1.0f;
    m_state.q = 1.0f;
    m_state.r = 0x3F800000u;
    m_cycle = 0;
    resetScheduler();
}

void VU1Interpreter::controlReset()
{
    resetScheduler();
    m_state.ebit = false;
    m_state.haltAfterDelaySlot = false;
    m_state.branchPending = false;
    m_state.branchTarget = 0;
    m_state.branchDelay = 0;
    m_state.stoppedByD = false;
    m_state.stoppedByT = false;
    m_state.dBitEnabled = false;
    m_state.tBitEnabled = false;
}

float VU1Interpreter::broadcast(const float *vf, uint8_t bc)
{
    return normalizeOperand(vf[bc & 3u]);
}


float VU1Interpreter::normalizeResult(float value, uint32_t &laneFlags) const
{
    uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    const uint32_t sign = bits & 0x80000000u;
    const uint32_t magnitude = bits & 0x7FFFFFFFu;
    const uint32_t exponent = (bits >> 23) & 0xFFu;

    laneFlags = sign != 0u ? 0x2u : 0u;
    if (magnitude == 0u)
    {
        laneFlags |= 0x1u;
    }
    else if (exponent == 0u)
    {
        laneFlags |= 0x5u;
        bits = sign;
    }
    else if (exponent == 0xFFu)
    {
        laneFlags |= 0x8u;
        bits = sign | 0x7F7FFFFFu;
    }

    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

uint32_t VU1Interpreter::microAddressMask() const
{
    return m_unit == Unit::VU1 ? 0x3FFFu : 0x0FFFu;
}

int32_t VU1Interpreter::readBranchVi(uint8_t reg) const
{
    if (reg == 0u)
        return 0;
    if (m_viBranchBackupValid &&
        m_viBranchBackupReg == reg)
    {
        return m_viBranchBackupValue;
    }
    return m_state.vi[reg];
}

void VU1Interpreter::recordViWriteForBranch(uint8_t reg, int32_t oldValue)
{
    if (reg == 0u)
        return;
    m_viBranchBackupValue = oldValue;
    m_viBranchBackupReg = reg;
    m_viBranchBackupValid = true;
}

void VU1Interpreter::applyDest(float *dst, const float *result, uint8_t dest)
{
    if (dest & 0x8u)
        dst[0] = result[0];
    if (dest & 0x4u)
        dst[1] = result[1];
    if (dest & 0x2u)
        dst[2] = result[2];
    if (dest & 0x1u)
        dst[3] = result[3];
}

void VU1Interpreter::applyDestAcc(const float *result, uint8_t dest)
{
    applyDest(m_state.acc, result, dest);
}

void VU1Interpreter::normalizeFmacResult(float *result, uint8_t dest,
                                         uint8_t laneFlags[4])
{
    if (fmacClassifyEnabled && ps2Vu1ClassifyNormalFmac(result, dest, laneFlags))
        return;
    for (uint32_t component = 0; component < 4u; ++component)
    {
        laneFlags[component] = 0u;
        if ((dest & laneForComponent(component)) == 0u)
            continue;

        // A rounded result that is a normal float well inside the range cannot
        // come from an exact zero, overflow or underflow, and keeps the sign of
        // the exact result: its flags are just S, with no exact recomputation.
        uint32_t resultBits;
        std::memcpy(&resultBits, &result[component], sizeof(resultBits));
        const uint32_t resultExponent = (resultBits >> 23) & 0xFFu;
        if (resultExponent >= 2u && resultExponent <= 253u)
        {
            laneFlags[component] = (resultBits & 0x80000000u) ? 0x2u : 0u;
            continue;
        }

        long double exactResult = 0.0L;
        if (m_pairFlagsLive && m_flagsObservable && calculateFmacExactResult(component, exactResult))
        {
            laneFlags[component] = normalizeFmacExactResult(result[component], exactResult);
            continue;
        }

        uint32_t flags = 0u;
        result[component] = normalizeResult(result[component], flags);
        laneFlags[component] = static_cast<uint8_t>(flags);
    }
}

bool VU1Interpreter::calculateFmacExactResult(uint32_t component,
                                               long double &result) const
{
    const uint32_t upper = m_currentUpperInstruction;
    const uint8_t op = static_cast<uint8_t>(upper & 0x3Fu);
    const uint8_t special = op >= 0x3Cu
                                ? static_cast<uint8_t>((upper & 3u) | ((upper >> 4) & 0x7Cu))
                                : 0xFFu;
    const uint8_t fs = FS(upper);
    const uint8_t ft = FT(upper);

    const auto operand = [this](float value)
    {
        return static_cast<long double>(normalizeOperand(value));
    };
    const auto vs = [&](uint32_t lane)
    {
        return operand(m_state.vf[fs][lane]);
    };
    const auto vt = [&](uint32_t lane)
    {
        return operand(m_state.vf[ft][lane]);
    };
    const auto acc = [&](uint32_t lane)
    {
        return operand(m_state.acc[lane]);
    };

    const long double q = operand(m_state.q);
    const long double i = operand(m_state.i);

    if (op < 0x3Cu)
    {
        if (op <= 0x03u)
            result = vs(component) + vt(op & 3u);
        else if (op <= 0x07u)
            result = vs(component) - vt(op & 3u);
        else if (op <= 0x0Bu)
            result = acc(component) + vs(component) * vt(op & 3u);
        else if (op <= 0x0Fu)
            result = acc(component) - vs(component) * vt(op & 3u);
        else if (op >= 0x18u && op <= 0x1Bu)
            result = vs(component) * vt(op & 3u);
        else
        {
            switch (op)
            {
            case 0x1Cu:
                result = vs(component) * q;
                break;
            case 0x1Eu:
                result = vs(component) * i;
                break;
            case 0x20u:
                result = vs(component) + q;
                break;
            case 0x21u:
                result = acc(component) + vs(component) * q;
                break;
            case 0x22u:
                result = vs(component) + i;
                break;
            case 0x23u:
                result = acc(component) + vs(component) * i;
                break;
            case 0x24u:
                result = vs(component) - q;
                break;
            case 0x25u:
                result = acc(component) - vs(component) * q;
                break;
            case 0x26u:
                result = vs(component) - i;
                break;
            case 0x27u:
                result = acc(component) - vs(component) * i;
                break;
            case 0x28u:
                result = vs(component) + vt(component);
                break;
            case 0x29u:
                result = acc(component) + vs(component) * vt(component);
                break;
            case 0x2Au:
                result = vs(component) * vt(component);
                break;
            case 0x2Cu:
                result = vs(component) - vt(component);
                break;
            case 0x2Du:
                result = acc(component) - vs(component) * vt(component);
                break;
            case 0x2Eu:
            {
                static constexpr uint8_t left[4] = {1u, 2u, 0u, 3u};
                static constexpr uint8_t right[4] = {2u, 0u, 1u, 3u};
                result = component == 3u
                             ? 0.0L
                             : acc(component) - vs(left[component]) * vt(right[component]);
                break;
            }
            default:
                return false;
            }
        }
        return true;
    }

    if (special <= 0x03u)
        result = vs(component) + vt(special & 3u);
    else if (special <= 0x07u)
        result = vs(component) - vt(special & 3u);
    else if (special <= 0x0Bu)
        result = acc(component) + vs(component) * vt(special & 3u);
    else if (special <= 0x0Fu)
        result = acc(component) - vs(component) * vt(special & 3u);
    else if (special >= 0x18u && special <= 0x1Bu)
        result = vs(component) * vt(special & 3u);
    else
    {
        switch (special)
        {
        case 0x1Cu:
            result = vs(component) * q;
            break;
        case 0x1Eu:
            result = vs(component) * i;
            break;
        case 0x20u:
            result = vs(component) + q;
            break;
        case 0x21u:
            result = acc(component) + vs(component) * q;
            break;
        case 0x22u:
            result = vs(component) + i;
            break;
        case 0x23u:
            result = acc(component) + vs(component) * i;
            break;
        case 0x24u:
            result = vs(component) - q;
            break;
        case 0x25u:
            result = acc(component) - vs(component) * q;
            break;
        case 0x26u:
            result = vs(component) - i;
            break;
        case 0x27u:
            result = acc(component) - vs(component) * i;
            break;
        case 0x28u:
            result = vs(component) + vt(component);
            break;
        case 0x29u:
            result = acc(component) + vs(component) * vt(component);
            break;
        case 0x2Au:
            result = vs(component) * vt(component);
            break;
        case 0x2Cu:
            result = vs(component) - vt(component);
            break;
        case 0x2Du:
            result = acc(component) - vs(component) * vt(component);
            break;
        case 0x2Eu:
        {
            static constexpr uint8_t left[4] = {1u, 2u, 0u, 3u};
            static constexpr uint8_t right[4] = {2u, 0u, 1u, 3u};
            result = component == 3u
                         ? 0.0L
                         : vs(left[component]) * vt(right[component]);
            break;
        }
        default:
            return false;
        }
    }
    return true;
}

uint8_t VU1Interpreter::normalizeFmacExactResult(float &value,
                                                  long double exactResult) const
{
    const bool negative = std::signbit(exactResult);
    const long double magnitude = std::fabs(exactResult);
    const long double maximum = static_cast<long double>(std::numeric_limits<float>::max());
    const long double minimum = static_cast<long double>(std::numeric_limits<float>::min());
    uint8_t flags = negative ? 0x2u : 0u;

    uint32_t bits = negative ? 0x80000000u : 0u;
    if (magnitude == 0.0L)
    {
        flags |= 0x1u;
        std::memcpy(&value, &bits, sizeof(value));
    }
    else if (magnitude > maximum)
    {
        flags |= 0x8u;
        bits |= 0x7F7FFFFFu;
        std::memcpy(&value, &bits, sizeof(value));
    }
    else if (magnitude < minimum)
    {
        flags |= 0x5u;
        std::memcpy(&value, &bits, sizeof(value));
    }

    return flags;
}

uint32_t VU1Interpreter::calculateFmacProductSticky(uint8_t dest) const
{
    if (!m_flagsObservable || !m_statusObservable)
        return 0u;
    uint32_t extraSticky = 0u;
    const uint32_t upper = m_currentUpperInstruction;
    const uint8_t op = static_cast<uint8_t>(upper & 0x3Fu);
    const uint8_t special = op >= 0x3Cu ? static_cast<uint8_t>((upper & 3u) | ((upper >> 4) & 0x7Cu)) : 0xFFu;
    const bool productSum =
        (op >= 0x08u && op <= 0x0Fu) ||
        op == 0x21u || op == 0x23u || op == 0x25u || op == 0x27u ||
        op == 0x29u || op == 0x2Du || op == 0x2Eu ||
        (special >= 0x08u && special <= 0x0Fu) ||
        special == 0x21u || special == 0x23u || special == 0x25u ||
        special == 0x27u || special == 0x29u || special == 0x2Du;
    if (!productSum)
        return 0u;

    const uint8_t fs = FS(upper);
    const uint8_t ft = FT(upper);
    for (uint32_t component = 0; component < 4u; ++component)
    {
        if ((dest & laneForComponent(component)) == 0u)
            continue;
        static constexpr uint8_t crossLeft[4] = {1u, 2u, 0u, 3u};
        static constexpr uint8_t crossRight[4] = {2u, 0u, 1u, 3u};
        const uint8_t leftComponent = op == 0x2Eu ? crossLeft[component] : static_cast<uint8_t>(component);
        const float left = normalizeOperand(m_state.vf[fs][leftComponent]);
        float right = 0.0f;
        if ((op >= 0x08u && op <= 0x0Fu) || (special >= 0x08u && special <= 0x0Fu))
        {
            right = normalizeOperand(m_state.vf[ft][(op >= 0x08u && op <= 0x0Fu ? op : special) & 3u]);
        }
        else if (op == 0x21u || op == 0x25u || special == 0x21u || special == 0x25u)
        {
            right = normalizeOperand(m_state.q);
        }
        else if (op == 0x23u || op == 0x27u || special == 0x23u || special == 0x27u)
        {
            right = normalizeOperand(m_state.i);
        }
        else if (op == 0x2Eu)
        {
            right = normalizeOperand(m_state.vf[ft][crossRight[component]]);
        }
        else
        {
            right = normalizeOperand(m_state.vf[ft][component]);
        }

        float product = left * right;
        uint32_t productBits;
        std::memcpy(&productBits, &product, sizeof(productBits));
        const uint32_t productExponent = (productBits >> 23) & 0xFFu;
        if (productExponent >= 2u && productExponent <= 253u)
        {
            extraSticky |= (productBits & 0x80000000u) ? 0x2u : 0u;
            continue;
        }
        const long double exactProduct = static_cast<long double>(left) * static_cast<long double>(right);
        const uint8_t productFlags = normalizeFmacExactResult(product, exactProduct);
        // Product-sum instructions report Z/S/U/O from the add/subtract result
        // as current flags, while every product condition accumulates into the
        // corresponding sticky flag.
        extraSticky |= productFlags & 0xFu;
    }
    return extraSticky;
}

void VU1Interpreter::updateFmacFlags(const uint8_t laneFlags[4], uint8_t dest,
                                     uint32_t extraSticky)
{
    if (dest == 0u)
        return;

    const uint64_t packed = ps2Vu1PackFmacFlags(laneFlags, dest);
    const uint32_t mac = static_cast<uint32_t>(packed);
    const uint32_t status = static_cast<uint32_t>(packed >> 32);

    if (m_pairFlagsDirect)
    {
        // Older FMAC flag entries are still in flight (4-cycle latency). No
        // reader sits between them and this pair's own visibility, so this
        // newer MAC/status supersedes theirs; their sticky contributions are
        // kept. An older FSSET would rewrite the sticky bits later: keep the
        // pipeline then.
        bool supersede = true;
        for (uint32_t pending = m_flagPending; pending != 0u && supersede; pending &= pending - 1u)
        {
            const FlagPipelineEntry &older = m_flagPipeline[static_cast<uint32_t>(std::countr_zero(pending))];
            if (older.valid && older.writesSticky)
                supersede = false;
        }
        if (supersede)
        {
            uint32_t inheritedSticky = 0u;
            for (uint32_t pending = m_flagPending; pending != 0u; pending &= pending - 1u)
            {
                FlagPipelineEntry &older = m_flagPipeline[static_cast<uint32_t>(std::countr_zero(pending))];
                if (!older.valid)
                    continue;
                if (older.writesStatus)
                    inheritedSticky |= ((older.status & 0xFu) | older.extraSticky) << 6;
                older.writesStatus = false;
                older.writesMac = false;
            }
            m_state.mac = mac;
            const uint32_t current = status & 0xFu;
            m_state.status = (m_state.status & 0xFF0u) | current | ((current | extraSticky) << 6) | inheritedSticky;
            return;
        }
    }

    FlagPipelineEntry *entry = nullptr;
    for (FlagPipelineEntry &candidate : m_flagPipeline)
    {
        if (!candidate.valid)
        {
            entry = &candidate;
            break;
        }
    }
    if (!entry)
    {
        reportReservedInstruction(true, 0xFFFFFFFFu);
        return;
    }

    *entry = {};
    ++g_vu1QueueCounts[0];
            m_flagPending |= 1u << static_cast<uint32_t>(entry - m_flagPipeline.data());
    entry->valid = true;
    entry->issueCycle = m_cycle;
    entry->readyCycle = m_cycle + kFmacLatency;
    m_nextCommitCycle = std::min(m_nextCommitCycle, entry->readyCycle);
    entry->mac = mac;
    entry->status = status;
    entry->extraSticky = extraSticky;
    entry->writesMac = true;
    entry->writesStatus = true;
}

void VU1Interpreter::applyFmacDest(float *dst, float *result, uint8_t dest)
{
    uint8_t laneFlags[4]{};
    normalizeFmacResult(result, dest, laneFlags);
    if (m_pairFlagsLive)
        updateFmacFlags(laneFlags, dest, m_pairProductSum ? calculateFmacProductSticky(dest) : 0u);
    applyDest(dst, result, dest);
}

void VU1Interpreter::applyFmacDestAcc(float *result, uint8_t dest)
{
    uint8_t laneFlags[4]{};
    normalizeFmacResult(result, dest, laneFlags);
    if (m_pairFlagsLive)
        updateFmacFlags(laneFlags, dest, m_pairProductSum ? calculateFmacProductSticky(dest) : 0u);
    applyDestAcc(result, dest);
}

void VU1Interpreter::queueFsset(uint16_t immediate)
{
    for (FlagPipelineEntry &entry : m_flagPipeline)
    {
        if (entry.valid && entry.issueCycle == m_cycle)
            entry.writesStatus = false;
    }

    for (FlagPipelineEntry &entry : m_flagPipeline)
    {
        if (!entry.valid)
        {
            entry = {};
            ++g_vu1QueueCounts[0];
            m_flagPending |= 1u << static_cast<uint32_t>(&entry - m_flagPipeline.data());
            entry.valid = true;
            entry.issueCycle = m_cycle;
            entry.readyCycle = m_cycle + kFmacLatency;
            m_nextCommitCycle = std::min(m_nextCommitCycle, entry.readyCycle);
            entry.status = static_cast<uint32_t>(immediate) & 0xFC0u;
            entry.writesSticky = true;
            return;
        }
    }
    reportReservedInstruction(false, 0xFFFFFFFEu);
}

void VU1Interpreter::queueClip(uint32_t clip)
{
    m_workingClip = ((m_workingClip << 6) | (clip & 0x3Fu)) & 0xFFFFFFu;
    for (FlagPipelineEntry &entry : m_flagPipeline)
    {
        if (!entry.valid)
        {
            entry = {};
            ++g_vu1QueueCounts[0];
            m_flagPending |= 1u << static_cast<uint32_t>(&entry - m_flagPipeline.data());
            entry.valid = true;
            entry.issueCycle = m_cycle;
            entry.readyCycle = m_cycle + kFmacLatency;
            m_nextCommitCycle = std::min(m_nextCommitCycle, entry.readyCycle);
            entry.clip = m_workingClip;
            entry.writesClip = true;
            return;
        }
    }
    reportReservedInstruction(true, 0xFFFFFFFDu);
}

void VU1Interpreter::queueFcset(uint32_t clip)
{
    m_workingClip = clip & 0xFFFFFFu;
    for (FlagPipelineEntry &entry : m_flagPipeline)
    {
        if (entry.valid && entry.issueCycle == m_cycle)
            entry.writesClip = false;
    }
    for (FlagPipelineEntry &entry : m_flagPipeline)
    {
        if (!entry.valid)
        {
            entry = {};
            ++g_vu1QueueCounts[0];
            m_flagPending |= 1u << static_cast<uint32_t>(&entry - m_flagPipeline.data());
            entry.valid = true;
            entry.issueCycle = m_cycle;
            entry.readyCycle = m_cycle + kFmacLatency;
            m_nextCommitCycle = std::min(m_nextCommitCycle, entry.readyCycle);
            entry.clip = m_workingClip;
            entry.writesClip = true;
            return;
        }
    }
    reportReservedInstruction(false, 0xFFFFFFFAu);
}

void VU1Interpreter::queueQ(float value, uint32_t latency, uint32_t statusDi)
{
    uint32_t ignoredFlags = 0u;
    value = normalizeResult(value, ignoredFlags);
    m_fdiv.valid = true;
    m_fdiv.readyCycle = m_cycle + latency;
    m_nextCommitCycle = std::min(m_nextCommitCycle, m_fdiv.readyCycle);
    m_fdiv.value = value;
    m_fdiv.statusDi = statusDi & 0x30u;
}

void VU1Interpreter::queueP(float value, uint32_t latency)
{
    uint32_t ignoredFlags = 0u;
    value = normalizeResult(value, ignoredFlags);
    for (ScalarPipelineEntry &entry : m_efu)
    {
        if (!entry.valid)
        {
            ++g_vu1QueueCounts[1];
            m_efuPending |= 1u << static_cast<uint32_t>(&entry - m_efu.data());
            entry.valid = true;
            entry.readyCycle = m_cycle + latency;
            m_nextCommitCycle = std::min(m_nextCommitCycle, entry.readyCycle);
            entry.value = value;
            // EFU throughput is one cycle shorter than result visibility.
            m_efuResourceReady = m_cycle + (latency > 0u ? latency - 1u : 0u);
            return;
        }
    }
    reportReservedInstruction(false, 0xFFFFFFF9u);
}

void VU1Interpreter::queueStore(uint32_t address, const uint32_t words[4], uint8_t laneMask)
{
    if (m_pairStoreDirect && m_storePending == 0u)
    {
        // Same as the commit one cycle later: every later reader of VU memory
        // (the next pair, XGKICK after the next commit) runs after that.
        if (m_activeVuData && address + 16u <= m_activeVuDataSize)
        {
            uint32_t oldWords[4]{};
            std::memcpy(oldWords, m_activeVuData + address, sizeof(oldWords));
            for (uint32_t component = 0; component < 4u; ++component)
                if ((laneMask & laneForComponent(component)) != 0u)
                    oldWords[component] = words[component];
            std::memcpy(m_activeVuData + address, oldWords, sizeof(oldWords));
        }
        return;
    }
    for (PendingStore &store : m_storePipeline)
    {
        if (!store.valid)
        {
            ++g_vu1QueueCounts[2];
            m_storePending |= 1u << static_cast<uint32_t>(&store - m_storePipeline.data());
            store.valid = true;
            store.readyCycle = m_cycle + 1u;
            m_nextCommitCycle = std::min(m_nextCommitCycle, store.readyCycle);
            store.address = address;
            store.laneMask = laneMask;
            std::copy(words, words + 4, store.words.begin());
            return;
        }
    }
    reportReservedInstruction(false, 0xFFFFFFFCu);
}

void VU1Interpreter::queueVfWrite(uint8_t reg, uint8_t laneMask,
                                  const float value[4], uint32_t latency)
{
    if (reg == 0u || laneMask == 0u)
        return;
    if (PendingVfWrite *available = firstFreePipelineSlot(m_vfWritePipeline, m_vfPending))
    {
        PendingVfWrite &write = *available;
        if (!write.valid)
        {
            write = {};
            ++g_vu1QueueCounts[3];
            m_vfPending |= 1u << static_cast<uint32_t>(&write - m_vfWritePipeline.data());
            write.valid = true;
            write.readyCycle = m_cycle + latency;
            m_nextCommitCycle = std::min(m_nextCommitCycle, write.readyCycle);
            write.sequence = ++m_nextWriteSequence;
            write.reg = reg;
            write.laneMask = laneMask;
            std::copy(value, value + 4, write.value.begin());
            for (uint32_t component = 0; component < 4u; ++component)
            {
                if ((laneMask & laneForComponent(component)) != 0u)
                    m_vfLatestWrite[reg][component] = write.sequence;
            }
            return;
        }
    }
    reportReservedInstruction(false, 0xFFFFFFF7u);
}

void VU1Interpreter::queueViWrite(uint8_t reg, int32_t value, uint32_t latency)
{
    if (reg == 0u)
        return;
    if (PendingViWrite *available = firstFreePipelineSlot(m_viWritePipeline, m_viPending))
    {
        PendingViWrite &write = *available;
        if (!write.valid)
        {
            write = {};
            ++g_vu1QueueCounts[4];
            m_viPending |= 1u << static_cast<uint32_t>(&write - m_viWritePipeline.data());
            write.valid = true;
            write.readyCycle = m_cycle + latency;
            m_nextCommitCycle = std::min(m_nextCommitCycle, write.readyCycle);
            write.sequence = ++m_nextWriteSequence;
            write.reg = reg;
            write.value = value;
            m_viLatestWrite[reg] = write.sequence;
            return;
        }
    }
    reportReservedInstruction(false, 0xFFFFFFF6u);
}

void VU1Interpreter::queueAccWrite(uint8_t laneMask, const float value[4], uint32_t latency)
{
    if (laneMask == 0u)
        return;
    if (PendingAccWrite *available = firstFreePipelineSlot(m_accWritePipeline, m_accPending))
    {
        PendingAccWrite &write = *available;
        if (!write.valid)
        {
            write = {};
            ++g_vu1QueueCounts[5];
            m_accPending |= 1u << static_cast<uint32_t>(&write - m_accWritePipeline.data());
            write.valid = true;
            write.readyCycle = m_cycle + latency;
            m_nextCommitCycle = std::min(m_nextCommitCycle, write.readyCycle);
            write.sequence = ++m_nextWriteSequence;
            write.laneMask = laneMask;
            std::copy(value, value + 4, write.value.begin());
            for (uint32_t component = 0; component < 4u; ++component)
            {
                if ((laneMask & laneForComponent(component)) != 0u)
                    m_accLatestWrite[component] = write.sequence;
            }
            return;
        }
    }
    reportReservedInstruction(true, 0xFFFFFFF5u);
}

// Bisect switch PS2X_VU1_SCAN_ALL, read once at startup: a function-local
// static here cost a guard check on every commit.
static const bool g_vu1ScanAll = [] { const char *v = std::getenv("PS2X_VU1_SCAN_ALL"); return v && *v == '1'; }();
static inline bool vu1ScanAll() { return g_vu1ScanAll; }

void VU1Interpreter::commitReadyPipelines()
{
    if (m_cycle < m_nextCommitCycle && !vu1ScanAll())
        return;
    ++g_vu1QueueCounts[6];
    uint64_t next = UINT64_MAX;
    if (vu1ScanAll())
    {
        // Bisect switch: visit every slot as before the pending masks.
        m_flagPending = (1u << kMaxFlagEntries) - 1u;
        m_efuPending = 3u;
        m_storePending = (1u << kMaxPendingStores) - 1u;
        m_vfPending = (1u << kMaxPendingVfWrites) - 1u;
        m_viPending = (1u << kMaxPendingViWrites) - 1u;
        m_accPending = (1u << kMaxPendingAccWrites) - 1u;
    }
    // Visit only occupied slots (set bits); a slot keeps its bit until it
    // retires, so entries that are not ready yet stay pending.
    // Flags, P and stores retire oldest-ready first: a stall that skips
    // several cycles at once must apply them in the order they would have
    // become visible (VF/VI/ACC writes are ordered by sequence numbers).
    {
        // One pass: collect the ready entries, then apply them oldest first.
        uint8_t ready[kMaxFlagEntries];
        uint32_t readyCount = 0;
        for (uint32_t pending = m_flagPending; pending != 0u; pending &= pending - 1u)
        {
            const uint32_t index = static_cast<uint32_t>(std::countr_zero(pending));
            const FlagPipelineEntry &entry = m_flagPipeline[index];
            if (!entry.valid)
            {
                m_flagPending &= ~(1u << index);
                continue;
            }
            if (entry.readyCycle > m_cycle)
            {
                next = std::min(next, entry.readyCycle);
                continue;
            }
            uint32_t slot = readyCount++;
            while (slot > 0u && m_flagPipeline[ready[slot - 1u]].readyCycle > entry.readyCycle)
            {
                ready[slot] = ready[slot - 1u];
                --slot;
            }
            ready[slot] = static_cast<uint8_t>(index);
        }
        for (uint32_t r = 0; r < readyCount; ++r)
        {
            FlagPipelineEntry &entry = m_flagPipeline[ready[r]];
            if (entry.writesMac)
                m_state.mac = entry.mac;
            if (entry.writesStatus)
            {
                const uint32_t current = entry.status & 0xFu;
                m_state.status = (m_state.status & 0xFF0u) | current | ((current | entry.extraSticky) << 6);
            }
            if (entry.writesSticky)
            {
                m_state.status = (m_state.status & 0x03Fu) | (entry.status & 0xFC0u);
            }
            if (entry.writesClip)
                m_state.clip = entry.clip;
            // Retired payload is private and all readers test valid first.
            // Allocation initializes the next entry; clearing it here as well
            // adds stores on every retirement without changing visibility.
            entry.valid = false;
            m_flagPending &= ~(1u << ready[r]);
        }
    }

    if (m_fdiv.valid && m_fdiv.readyCycle > m_cycle)
        next = std::min(next, m_fdiv.readyCycle);
    if (m_fdiv.valid && m_fdiv.readyCycle <= m_cycle)
    {
        m_state.q = m_fdiv.value;
        const uint32_t currentDi = m_fdiv.statusDi & 0x30u;
        m_state.status = (m_state.status & 0xFCFu) | currentDi | (currentDi << 6);
        m_fdiv.valid = false;
    }

    for (;;)
    {
        int best = -1;
        for (uint32_t pending = m_efuPending; pending != 0u; pending &= pending - 1u)
        {
            const uint32_t index = static_cast<uint32_t>(std::countr_zero(pending));
            ScalarPipelineEntry &entry = m_efu[index];
            if (!entry.valid)
            {
                m_efuPending &= ~(1u << index);
                continue;
            }
            if (entry.readyCycle > m_cycle)
            {
                next = std::min(next, entry.readyCycle);
                continue;
            }
            if (best < 0 || entry.readyCycle < m_efu[static_cast<uint32_t>(best)].readyCycle)
                best = static_cast<int>(index);
        }
        if (best < 0)
            break;
        m_state.p = m_efu[static_cast<uint32_t>(best)].value;
        m_efu[static_cast<uint32_t>(best)].valid = false;
        m_efuPending &= ~(1u << static_cast<uint32_t>(best));
    }

    for (;;)
    {
        int best = -1;
        for (uint32_t pending = m_storePending; pending != 0u; pending &= pending - 1u)
        {
            const uint32_t index = static_cast<uint32_t>(std::countr_zero(pending));
            PendingStore &store = m_storePipeline[index];
            if (!store.valid)
            {
                m_storePending &= ~(1u << index);
                continue;
            }
            if (store.readyCycle > m_cycle)
            {
                next = std::min(next, store.readyCycle);
                continue;
            }
            if (best < 0 || store.readyCycle < m_storePipeline[static_cast<uint32_t>(best)].readyCycle)
                best = static_cast<int>(index);
        }
        if (best < 0)
            break;
        PendingStore &store = m_storePipeline[static_cast<uint32_t>(best)];
        if (m_activeVuData && store.address + 16u <= m_activeVuDataSize)
        {
            uint32_t oldWords[4]{};
            std::memcpy(oldWords, m_activeVuData + store.address, sizeof(oldWords));
            for (uint32_t component = 0; component < 4u; ++component)
            {
                if ((store.laneMask & laneForComponent(component)) != 0u)
                    oldWords[component] = store.words[component];
            }
            std::memcpy(m_activeVuData + store.address, oldWords, sizeof(oldWords));
        }
        store.valid = false;
        m_storePending &= ~(1u << static_cast<uint32_t>(best));
    }

    for (uint32_t pending = m_vfPending; pending != 0u; pending &= pending - 1u)
    {
        const uint32_t index = static_cast<uint32_t>(std::countr_zero(pending));
        PendingVfWrite &write = m_vfWritePipeline[index];
        if (write.valid && write.readyCycle > m_cycle)
        {
            next = std::min(next, write.readyCycle);
            continue;
        }
        if (write.valid)
        {
            for (uint32_t component = 0; component < 4u; ++component)
            {
                if ((write.laneMask & laneForComponent(component)) != 0u &&
                    m_vfLatestWrite[write.reg][component] == write.sequence)
                {
                    m_state.vf[write.reg][component] = write.value[component];
                }
            }
        }
        write.valid = false;
        m_vfPending &= ~(1u << index);
    }

    for (uint32_t pending = m_viPending; pending != 0u; pending &= pending - 1u)
    {
        const uint32_t index = static_cast<uint32_t>(std::countr_zero(pending));
        PendingViWrite &write = m_viWritePipeline[index];
        if (write.valid && write.readyCycle > m_cycle)
        {
            next = std::min(next, write.readyCycle);
            continue;
        }
        if (write.valid && m_viLatestWrite[write.reg] == write.sequence)
            m_state.vi[write.reg] = static_cast<int16_t>(write.value);
        write.valid = false;
        m_viPending &= ~(1u << index);
    }

    for (uint32_t pending = m_accPending; pending != 0u; pending &= pending - 1u)
    {
        const uint32_t index = static_cast<uint32_t>(std::countr_zero(pending));
        PendingAccWrite &write = m_accWritePipeline[index];
        if (write.valid && write.readyCycle > m_cycle)
        {
            next = std::min(next, write.readyCycle);
            continue;
        }
        if (write.valid)
        {
            for (uint32_t component = 0; component < 4u; ++component)
            {
                if ((write.laneMask & laneForComponent(component)) != 0u &&
                    m_accLatestWrite[component] == write.sequence)
                {
                    m_state.acc[component] = write.value[component];
                }
            }
        }
        write.valid = false;
        m_accPending &= ~(1u << index);
    }
    m_nextCommitCycle = next;
}

void VU1Interpreter::progressXgkick()
{
    if (!m_xgkick.active || !m_activeVuData || m_activeVuDataSize == 0u)
        return;

    ++m_xgkick.cycleCredit;
    while (m_xgkick.active && m_xgkick.cycleCredit >= 2u)
    {
        m_xgkick.cycleCredit -= 2u;
        if (m_xgkick.copiedBytes > XgkickPipeline::kBufferSize - 16u)
        {
            reportReservedInstruction(false, 0xFFFFFFFBu);
            m_xgkick.active = false;
            return;
        }

        const uint32_t qwordOffset = m_xgkick.copiedBytes;
        const uint32_t source = (m_xgkick.sourceAddress + qwordOffset) % m_activeVuDataSize;
        if (m_activeVuDataSize - source >= 16u)
        {
            std::memcpy(m_xgkick.packet.data() + qwordOffset, m_activeVuData + source, 16u);
        }
        else
        {
            for (uint32_t i = 0; i < 16u; ++i)
                m_xgkick.packet[qwordOffset + i] = m_activeVuData[(source + i) % m_activeVuDataSize];
        }
        m_xgkick.copiedBytes += 16u;

        if (m_xgkick.currentTagEnd == 0u)
        {
            uint64_t tagLo = 0;
            std::memcpy(&tagLo, m_xgkick.packet.data() + qwordOffset, sizeof(tagLo));
            const uint32_t nloop = static_cast<uint32_t>(tagLo & 0x7FFFu);
            const uint32_t format = static_cast<uint32_t>((tagLo >> 58) & 0x3u);
            uint32_t nreg = static_cast<uint32_t>((tagLo >> 60) & 0xFu);
            if (nreg == 0u)
                nreg = 16u;

            uint64_t tagBytes = 16u;
            if (format == 0u)
                tagBytes += static_cast<uint64_t>(nloop) * nreg * 16u;
            else if (format == 1u)
                tagBytes += ((static_cast<uint64_t>(nloop) * nreg + 1u) & ~1ull) * 8u;
            else if (format == 2u)
                tagBytes += static_cast<uint64_t>(nloop) * 16u;
            else
            {
                reportReservedInstruction(false, 0xFFFFFFF8u);
                m_xgkick.active = false;
                return;
            }

            if (tagBytes > XgkickPipeline::kBufferSize - qwordOffset)
            {
                reportReservedInstruction(false, 0xFFFFFFFBu);
                m_xgkick.active = false;
                return;
            }
            m_xgkick.currentTagEnd = qwordOffset + static_cast<uint32_t>(tagBytes);
            m_xgkick.currentTagEop = ((tagLo >> 15) & 1u) != 0u;
            if (m_xgkick.currentTagEop)
                m_xgkick.totalBytes = m_xgkick.currentTagEnd;
        }

        if (m_xgkick.copiedBytes >= m_xgkick.currentTagEnd)
        {
            if (m_xgkick.currentTagEop)
                finishXgkick();
            else
            {
                // The next transferred qword is another GIFtag.
                m_xgkick.currentTagEnd = 0u;
                m_xgkick.currentTagEop = false;
            }
        }
    }
}

// PS2X_TRACE_VU1 counters, read by the per-vsync summary in ps2_runtime.cpp.
uint64_t g_vu1XgkickPackets = 0;
uint64_t g_vu1Cycles = 0;
// Enqueue counts per pipeline (flag, efu, store, vf, vi, acc) and commit calls, for ps2x_vu1_bench.
uint64_t g_vu1QueueCounts[7] = {}; // VU1 cycles executed by run() (PS2X_TRACE_VU1)
uint64_t g_vu1Runs = 0;
uint64_t g_vu1XgkickBytes = 0;

void VU1Interpreter::finishXgkick()
{
    if (!m_xgkick.active)
        return;
    ++g_vu1XgkickPackets;
    g_vu1XgkickBytes += m_xgkick.totalBytes;

    if (g_vu1CommandGifCollect)
    {
        // Framed PATH1 bytes, before any external GIF arbitration or renderer.
        // Used only by bounded command capture and its replay acceptance.
        for (uint32_t byte = 0; byte < 4; ++byte)
            g_vu1CommandGifHash = (g_vu1CommandGifHash ^ ((m_xgkick.totalBytes >> (8u * byte)) & 0xFFu)) * 0x100000001B3ull;
        for (uint32_t byte = 0; byte < m_xgkick.totalBytes; ++byte)
            g_vu1CommandGifHash = (g_vu1CommandGifHash ^ m_xgkick.packet[byte]) * 0x100000001B3ull;
        ++g_vu1CommandGifPackets;
    }

    if (m_activeMemory)
        m_activeMemory->submitGifPacket(GifPathId::Path1, m_xgkick.packet.data(), m_xgkick.totalBytes);
    else if (m_activeGs)
        m_activeGs->processGIFPacket(m_xgkick.packet.data(), m_xgkick.totalBytes);
    m_xgkick.active = false;
}

void VU1Interpreter::startXgkick(uint32_t qwordAddress)
{
    if (m_unit != Unit::VU1 || !m_activeVuData || m_activeVuDataSize < 16u)
        return;

    const uint32_t sourceAddress = (qwordAddress * 16u) % m_activeVuDataSize;
    m_xgkick.resetTransfer();
    m_xgkick.active = true;
    m_xgkick.sourceAddress = sourceAddress;
    m_xgkick.cycleCredit = 1u; // XGKICK's issue cycle counts toward PATH1.
    m_xgkick.issueCycle = m_cycle;
}

PS2X_VU1_STEP_INLINE void VU1Interpreter::advanceOneCycle()
{
    ++m_cycle;
    m_state.cycles = m_cycle;
    // LSU commits become visible at the cycle boundary before PATH1 consumes
    // its next qword from VU memory. The early-outs are tested here so the
    // common cycle with nothing due makes no call.
    if (m_cycle >= m_nextCommitCycle || vu1ScanAll())
        commitReadyPipelines();
    if (m_xgkick.active)
        progressXgkick();
}

void VU1Interpreter::advanceTo(uint64_t targetCycle)
{
    // A stall executes nothing until targetCycle: without an XGKICK in flight
    // the skipped cycles only retire pipeline entries, which the commit
    // applies in ready-cycle order, so jump straight to the last one.
    if (targetCycle > m_cycle + 1u && !m_xgkick.active && !vu1ScanAll())
    {
        m_cycle = targetCycle - 1u;
        advanceOneCycle();
        return;
    }
    while (m_cycle < targetCycle)
        advanceOneCycle();
}

bool VU1Interpreter::pipelinesPending() const
{
    return m_fdiv.valid || m_xgkick.active ||
           (m_flagPending | m_efuPending | m_storePending | m_vfPending | m_viPending | m_accPending) != 0u;
}

void VU1Interpreter::flushPipelines()
{
    while (pipelinesPending())
        advanceOneCycle();
}

PS2X_VU1_STEP_INLINE uint64_t VU1Interpreter::calculatePairReadyCycle(const DecodedInstructionPair &decoded) const
{
    uint64_t ready = m_cycle;
    const InstructionUsage *usages[2] = {
        &decoded.upperUsage,
        &decoded.lowerUsage};
    for (const InstructionUsage *usage : usages)
    {
        if (!usage)
            continue;
        // Lane bit 3 is x (component 0) ... bit 0 is w (component 3).
        for (uint32_t index = 0; index < usage->vfReadCount; ++index)
        {
            const VfAccess &access = usage->vfRead[index];
            for (uint32_t lanes = access.lanes & 0xFu; lanes != 0u; lanes &= lanes - 1u)
                ready = std::max(ready, m_vfReady[access.reg][3u - std::countr_zero(lanes)]);
        }
        for (uint32_t regs = usage->viRead & 0xFFFEu; regs != 0u; regs &= regs - 1u)
            ready = std::max(ready, m_viReady[std::countr_zero(regs)]);
        for (uint32_t lanes = usage->accRead & 0xFu; lanes != 0u; lanes &= lanes - 1u)
            ready = std::max(ready, m_accReady[3u - std::countr_zero(lanes)]);
    }

    if (decoded.lowerUsage.pipeline == PipelineFdiv && m_fdiv.valid)
        ready = std::max(ready, m_fdiv.readyCycle);
    if (decoded.lowerUsage.pipeline == PipelineEfu)
        ready = std::max(ready, m_efuResourceReady);
    if (decoded.lowerUsage.waitQ && m_fdiv.valid)
        ready = std::max(ready, m_fdiv.readyCycle);
    if (decoded.lowerUsage.waitP)
    {
        for (const ScalarPipelineEntry &entry : m_efu)
            if (entry.valid)
                ready = std::max(ready, entry.readyCycle);
    }
    if (decoded.lowerUsage.pipeline == PipelineXgkick && m_xgkick.active)
        ready = std::max(ready, m_cycle + 1u);
    return ready;
}

PS2X_VU1_STEP_INLINE void VU1Interpreter::markPairWrites(const DecodedInstructionPair &decoded)
{
    const VfAccess lowerWrite = decoded.lowerUsage.vfWrite;
    if (lowerWrite.reg != 0u &&
        decoded.suppressedLowerVf != lowerWrite.reg)
    {
        const uint32_t latency = decoded.lowerUsage.vfLatency != 0u
                                     ? decoded.lowerUsage.vfLatency
                                     : decoded.lowerUsage.latency;
        for (uint32_t component = 0; component < 4u; ++component)
        {
            if ((lowerWrite.lanes & laneForComponent(component)) != 0u)
                m_vfReady[lowerWrite.reg][component] = m_cycle + latency;
        }
    }

    const VfAccess upperWrite = decoded.upperUsage.vfWrite;
    if (upperWrite.reg != 0u)
    {
        const uint32_t latency = decoded.upperUsage.vfLatency != 0u
                                     ? decoded.upperUsage.vfLatency
                                     : decoded.upperUsage.latency;
        for (uint32_t component = 0; component < 4u; ++component)
        {
            if ((upperWrite.lanes & laneForComponent(component)) != 0u)
                m_vfReady[upperWrite.reg][component] = m_cycle + latency;
        }
    }

    for (uint32_t reg = 1; reg < m_viReady.size(); ++reg)
    {
        if ((decoded.lowerUsage.viWrite & (1u << reg)) != 0u)
            m_viReady[reg] = m_cycle + (decoded.lowerUsage.viLatency != 0u ? decoded.lowerUsage.viLatency : decoded.lowerUsage.latency);
    }
    for (uint32_t component = 0; component < 4u; ++component)
    {
        if ((decoded.upperUsage.accWrite & laneForComponent(component)) != 0u)
            m_accReady[component] = m_cycle + kAccForwardLatency;
    }
}

VU1Interpreter::InstructionUsage VU1Interpreter::decodeUpperUsage(uint32_t upper) const
{
    InstructionUsage usage;
    usage.pipeline = PipelineFmac;
    usage.latency = kFmacLatency;

    const uint8_t op = static_cast<uint8_t>(upper & 0x3Fu);
    const uint8_t dest = DEST(upper);
    const uint8_t fs = FS(upper);
    const uint8_t ft = FT(upper);
    const uint8_t fd = FD(upper);

    if (op <= 0x2Fu)
    {
        addVfRead(usage, fs, dest);
        addVfWrite(usage, fd, dest);
        if (op <= 0x1Bu)
            addVfRead(usage, ft, laneForComponent(op & 3u));
        else if (op >= 0x28u)
            addVfRead(usage, ft, op == 0x2Eu ? 0xEu : dest);
        if (op == 0x08u || op == 0x09u || op == 0x0Au || op == 0x0Bu ||
            op == 0x0Cu || op == 0x0Du || op == 0x0Eu || op == 0x0Fu ||
            op == 0x21u || op == 0x23u || op == 0x25u || op == 0x27u ||
            op == 0x29u || op == 0x2Du || op == 0x2Eu)
        {
            usage.accRead = dest;
        }
        return usage;
    }

    if (op >= 0x3Cu)
    {
        const uint8_t special = static_cast<uint8_t>((upper & 3u) | ((upper >> 4) & 0x7Cu));
        const bool writesAcc =
            special <= 0x0Fu ||
            (special >= 0x18u && special <= 0x1Cu) ||
            special == 0x1Eu ||
            (special >= 0x20u && special <= 0x2Au) ||
            (special >= 0x2Cu && special <= 0x2Eu);
        if (writesAcc)
        {
            addVfRead(usage, fs, dest);
            if (special <= 0x1Bu)
                addVfRead(usage, ft, laneForComponent(special & 3u));
            else if ((special >= 0x28u && special <= 0x2Eu))
                addVfRead(usage, ft, special == 0x2Eu ? 0xEu : dest);
            usage.accWrite = dest;
            if ((special >= 0x08u && special <= 0x0Fu) ||
                special == 0x21u || special == 0x23u || special == 0x25u ||
                special == 0x27u || special == 0x29u || special == 0x2Du)
            {
                usage.accRead = dest;
            }
        }
        else if (special >= 0x10u && special <= 0x17u)
        {
            addVfRead(usage, fs, dest);
            addVfWrite(usage, ft, dest);
        }
        else if (special == 0x1Du)
        {
            addVfRead(usage, fs, dest);
            addVfWrite(usage, ft, dest);
        }
        else if (special == 0x1Fu)
        {
            addVfRead(usage, fs, 0xEu);
            addVfRead(usage, ft, 0x1u);
            usage.writesClip = true;
        }
        else if (special != 0x2Fu && special != 0x30u)
        {
            usage.reserved = true;
        }
        return usage;
    }

    usage.reserved = true;
    return usage;
}

VU1Interpreter::InstructionUsage VU1Interpreter::decodeLowerUsage(uint32_t lower) const
{
    InstructionUsage usage;
    if (lower == 0u || lower == 0x8000033Cu)
        return usage;

    const uint8_t opHi = static_cast<uint8_t>((lower >> 25) & 0x7Fu);
    const uint8_t vfT = FT(lower);
    const uint8_t vfS = FS(lower);
    const uint8_t viT = VIT(lower);
    const uint8_t viS = VIS(lower);
    const uint8_t viD = VID(lower);
    const uint8_t dest = DEST(lower);
    auto readVi = [&](uint8_t reg)
    {
        if (reg != 0u)
            usage.viRead |= static_cast<uint16_t>(1u << reg);
    };
    auto writeVi = [&](uint8_t reg)
    {
        if (reg != 0u)
            usage.viWrite |= static_cast<uint16_t>(1u << reg);
    };

    switch (opHi)
    {
    case 0x00:
        usage.pipeline = PipelineLsu;
        usage.latency = 4u;
        readVi(viS);
        addVfWrite(usage, vfT, dest);
        return usage;
    case 0x01:
        usage.pipeline = PipelineLsu;
        usage.latency = 1u;
        readVi(viT);
        addVfRead(usage, vfS, dest);
        return usage;
    case 0x04:
        usage.pipeline = PipelineLsu;
        usage.latency = 4u;
        readVi(viS);
        writeVi(viT);
        return usage;
    case 0x05:
        usage.pipeline = PipelineLsu;
        usage.latency = 1u;
        readVi(viS);
        readVi(viT);
        return usage;
    case 0x08:
    case 0x09:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        usage.delaysNextBranchRead = true;
        readVi(viS);
        writeVi(viT);
        return usage;
    case 0x10:
    case 0x12:
    case 0x13:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        usage.readsClip = true;
        writeVi(1u);
        return usage;
    case 0x11:
        usage.pipeline = PipelineFmac;
        usage.latency = kFmacLatency;
        usage.writesClip = true;
        return usage;
    case 0x14:
    case 0x16:
    case 0x17:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        writeVi(viT);
        return usage;
    case 0x15:
        usage.pipeline = PipelineFmac;
        usage.latency = kFmacLatency;
        return usage;
    case 0x18:
    case 0x1A:
    case 0x1B:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        readVi(viS);
        writeVi(viT);
        return usage;
    case 0x1C:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        usage.readsClip = true;
        writeVi(viT);
        return usage;
    case 0x20:
        usage.pipeline = PipelineBranch;
        return usage;
    case 0x21:
        usage.pipeline = PipelineBranch;
        usage.latency = 1u;
        writeVi(viT);
        return usage;
    case 0x24:
        usage.pipeline = PipelineBranch;
        readVi(viS);
        return usage;
    case 0x25:
        usage.pipeline = PipelineBranch;
        usage.latency = 1u;
        readVi(viS);
        writeVi(viT);
        return usage;
    case 0x28:
    case 0x29:
        usage.pipeline = PipelineBranch;
        readVi(viS);
        readVi(viT);
        return usage;
    case 0x2C:
    case 0x2D:
    case 0x2E:
    case 0x2F:
        usage.pipeline = PipelineBranch;
        readVi(viS);
        return usage;
    case 0x40:
        break;
    default:
        usage.reserved = true;
        return usage;
    }

    const uint8_t direct = static_cast<uint8_t>(lower & 0x3Fu);
    if (direct == 0x30u || direct == 0x31u || direct == 0x34u || direct == 0x35u)
    {
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        usage.delaysNextBranchRead = true;
        readVi(viS);
        readVi(viT);
        writeVi(viD);
        return usage;
    }
    if (direct == 0x32u)
    {
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        usage.delaysNextBranchRead = true;
        readVi(viS);
        writeVi(viT);
        return usage;
    }
    if (direct < 0x3Cu)
    {
        usage.reserved = true;
        return usage;
    }

    const uint8_t special = static_cast<uint8_t>((lower & 3u) | ((lower >> 4) & 0x7Cu));
    switch (special)
    {
    case 0x30:
    case 0x31:
        usage.pipeline = PipelineFmac;
        usage.latency = 4u;
        addVfRead(usage, vfS, special == 0x31u ? 0xFu : dest);
        addVfWrite(usage, vfT, dest);
        break;
    case 0x34:
    case 0x36:
        usage.pipeline = PipelineLsu;
        usage.latency = 4u;
        usage.viLatency = 1u;
        usage.delaysNextBranchRead = true;
        readVi(viS);
        writeVi(viS);
        addVfWrite(usage, vfT, dest);
        break;
    case 0x35:
    case 0x37:
        usage.pipeline = PipelineLsu;
        usage.latency = 1u;
        usage.delaysNextBranchRead = true;
        readVi(viT);
        writeVi(viT);
        addVfRead(usage, vfS, dest);
        break;
    case 0x38:
        usage.pipeline = PipelineFdiv;
        usage.latency = 7u;
        addVfRead(usage, vfS, laneForComponent((lower >> 21) & 3u));
        addVfRead(usage, vfT, laneForComponent((lower >> 23) & 3u));
        break;
    case 0x39:
        usage.pipeline = PipelineFdiv;
        usage.latency = 7u;
        addVfRead(usage, vfT, laneForComponent((lower >> 23) & 3u));
        break;
    case 0x3A:
        usage.pipeline = PipelineFdiv;
        usage.latency = 13u;
        addVfRead(usage, vfS, laneForComponent((lower >> 21) & 3u));
        addVfRead(usage, vfT, laneForComponent((lower >> 23) & 3u));
        break;
    case 0x3B:
        usage.pipeline = PipelineFdiv;
        usage.waitQ = true;
        break;
    case 0x3C:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        usage.delaysNextBranchRead = true;
        addVfRead(usage, vfS, laneForComponent((lower >> 21) & 3u));
        writeVi(viT);
        break;
    case 0x3D:
        usage.pipeline = PipelineFmac;
        usage.latency = 4u;
        readVi(viS);
        addVfWrite(usage, vfT, dest);
        break;
    case 0x3E:
        usage.pipeline = PipelineLsu;
        usage.latency = 4u;
        readVi(viS);
        writeVi(viT);
        break;
    case 0x3F:
        usage.pipeline = PipelineLsu;
        usage.latency = 1u;
        readVi(viS);
        readVi(viT);
        break;
    case 0x40:
    case 0x41:
        usage.pipeline = PipelineFmac;
        usage.latency = 4u;
        addVfWrite(usage, vfT, dest);
        break;
    case 0x42:
    case 0x43:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        addVfRead(usage, vfS, laneForComponent((lower >> 21) & 3u));
        break;
    case 0x64:
        if (m_unit == Unit::VU0)
        {
            usage.reserved = true;
            break;
        }
        usage.pipeline = PipelineFmac;
        usage.latency = 4u;
        addVfWrite(usage, vfT, dest);
        break;
    case 0x68:
    case 0x69:
        usage.pipeline = PipelineIalu;
        usage.latency = 1u;
        writeVi(viT);
        break;
    case 0x6C:
        if (m_unit == Unit::VU0)
        {
            usage.reserved = true;
            break;
        }
        usage.pipeline = PipelineXgkick;
        usage.latency = 2u;
        readVi(viS);
        break;
    case 0x70:
    case 0x71:
    case 0x72:
    case 0x73:
    case 0x74:
    case 0x75:
    case 0x76:
    case 0x77:
    case 0x78:
    case 0x79:
    case 0x7A:
    case 0x7C:
    case 0x7D:
        if (m_unit == Unit::VU0)
        {
            usage.reserved = true;
            break;
        }
        usage.pipeline = PipelineEfu;
        switch (special)
        {
        case 0x70:
            usage.latency = 11u;
            break;
        case 0x71:
        case 0x72:
        case 0x77:
            usage.latency = 18u;
            break;
        case 0x73:
            usage.latency = 24u;
            break;
        case 0x74:
        case 0x75:
        case 0x7C:
            usage.latency = 54u;
            break;
        case 0x76:
        case 0x78:
        case 0x7A:
            usage.latency = 12u;
            break;
        case 0x79:
            usage.latency = 29u;
            break;
        case 0x7D:
            usage.latency = 44u;
            break;
        default:
            break;
        }
        if (special >= 0x70u && special <= 0x73u)
            addVfRead(usage, vfS, 0xEu);
        else if (special == 0x74u)
            addVfRead(usage, vfS, 0xCu);
        else if (special == 0x75u)
            addVfRead(usage, vfS, 0xAu);
        else if (special == 0x76u)
            addVfRead(usage, vfS, 0xFu);
        else
            addVfRead(usage, vfS, laneForComponent((lower >> 21) & 3u));
        break;
    case 0x7B:
        if (m_unit == Unit::VU0)
        {
            usage.reserved = true;
            break;
        }
        usage.pipeline = PipelineEfu;
        usage.waitP = true;
        break;
    default:
        usage.reserved = true;
        break;
    }
    return usage;
}

VU1Interpreter::DecodedInstructionPair VU1Interpreter::decodeInstructionPair(const uint8_t *vuCode, uint32_t pc) const
{
    DecodedInstructionPair decoded;
    std::memcpy(&decoded.lower, vuCode + pc, sizeof(decoded.lower));
    std::memcpy(&decoded.upper, vuCode + pc + sizeof(decoded.lower), sizeof(decoded.upper));
    decoded.iBit = (decoded.upper & 0x80000000u) != 0u;
    decoded.eBit = (decoded.upper & 0x40000000u) != 0u;
    decoded.mBit = (decoded.upper & 0x20000000u) != 0u;
    decoded.dBit = (decoded.upper & 0x10000000u) != 0u;
    decoded.tBit = (decoded.upper & 0x08000000u) != 0u;
    decoded.upperUsage = decodeUpperUsage(decoded.upper);
    if (!decoded.iBit)
        decoded.lowerUsage = decodeLowerUsage(decoded.lower);

    const uint8_t upperWriteReg = decoded.upperUsage.vfWrite.reg;
    if (upperWriteReg != 0u && (vfReadLanes(decoded.lowerUsage, upperWriteReg) != 0u || decoded.lowerUsage.vfWrite.reg == upperWriteReg))
    {
        decoded.upperVfShadowReg = upperWriteReg;
        if (decoded.lowerUsage.vfWrite.reg == upperWriteReg)
            decoded.suppressedLowerVf = upperWriteReg;
    }
    return decoded;
}

void VU1Interpreter::rebuildDecodedCodeCache(const uint8_t *vuCode, uint32_t codeSize,
                                             const PS2Memory *memory, uint64_t generation)
{
    const uint32_t pairCount = std::min<uint32_t>(codeSize / 8u, kMaxDecodedPairs);
    static const bool exactFlags = [] { const char *v = std::getenv("PS2X_VU1_EXACT_FLAGS"); return v && *v == '1'; }();
    bool flagReader = exactFlags;
    for (uint32_t i = 0; i < pairCount; ++i)
    {
        m_decodedCodeCache[i] = decodeInstructionPair(vuCode, i * 8u);
        const DecodedInstructionPair &pair = m_decodedCodeCache[i];
        if (!pair.iBit)
        {
            // FSEQ 0x14, FSAND 0x16, FSOR 0x17, FMEQ 0x18, FMAND 0x1A, FMOR 0x1B.
            const uint32_t opHi = (pair.lower >> 25) & 0x7Fu;
            if (opHi == 0x14u || opHi == 0x16u || opHi == 0x17u || opHi == 0x18u || opHi == 0x1Au || opHi == 0x1Bu)
                flagReader = true;
        }
    }
    // VU0 flags are also read by the EE (CFC2 VI16/VI17); only VU1's are
    // private to its microprograms.
    m_flagsObservable = flagReader || m_unit != Unit::VU1;
    bool statusReader = exactFlags;
    for (uint32_t i = 0; i < pairCount && !statusReader; ++i)
    {
        const DecodedInstructionPair &pair = m_decodedCodeCache[i];
        const uint32_t opHi = (pair.lower >> 25) & 0x7Fu;
        statusReader = !pair.iBit && (opHi == 0x14u || opHi == 0x16u || opHi == 0x17u);
    }
    m_statusObservable = statusReader || m_unit != Unit::VU1;

    // Direct-write analysis (VU1 only; VU0 registers are also read by the EE).
    static const bool directWrites = [] { const char *v = std::getenv("PS2X_VU1_DIRECT"); return !(v && *v == '0'); }();
    const auto breaksFlow = [](const DecodedInstructionPair &pair)
    {
        return pair.eBit || pair.dBit || pair.tBit || pair.upperUsage.reserved ||
               (!pair.iBit && (pair.lowerUsage.reserved || pair.lowerUsage.pipeline == PipelineBranch));
    };
    for (uint32_t i = 0; i < pairCount; ++i)
    {
        DecodedInstructionPair &pair = m_decodedCodeCache[i];
        pair.upperVfDirect = false;
        pair.lowerVfDirect = false;
        pair.accDirect = false;
        pair.viDirect = false;
        pair.storeDirect = false;
        if (m_unit != Unit::VU1 || !directWrites)
            continue;
        // The lower result lands after the upper op of this pair already ran;
        // later readers stall on m_vfReady as for the upper write.
        pair.lowerVfDirect = !pair.iBit && pair.upperVfShadowReg == 0u && pair.lowerUsage.vfWrite.reg != 0u &&
                             pair.lowerUsage.vfWrite.reg != pair.upperUsage.vfWrite.reg && !breaksFlow(pair);
        const uint32_t viLatency = pair.lowerUsage.viLatency != 0u ? pair.lowerUsage.viLatency : pair.lowerUsage.latency;
        pair.viDirect = !pair.iBit && (pair.lowerUsage.viWrite & 0xFFFEu) != 0u && viLatency <= 1u && !breaksFlow(pair);
        pair.storeDirect = !pair.iBit && !breaksFlow(pair);
        // ACC is forwarded after one cycle, i.e. to the very next pair.
        pair.accDirect = pair.upperUsage.accWrite != 0u && kAccForwardLatency <= 1u;

        const VfAccess write = pair.upperUsage.vfWrite;
        if (write.reg == 0u || pair.upperVfShadowReg != 0u || breaksFlow(pair))
            continue;
        if (!pair.iBit && (pair.lowerUsage.vfWrite.reg == write.reg || vfReadLanes(pair.lowerUsage, write.reg) != 0u))
            continue;
        const uint32_t latency = pair.upperUsage.vfLatency != 0u ? pair.upperUsage.vfLatency : pair.upperUsage.latency;
        if (latency == 0u || i + latency > pairCount)
            continue;
        // Every later read of these lanes stalls on m_vfReady until the result
        // would have landed, so none can observe the value early; a later write
        // supersedes through the sequence numbers. Only the pair itself (its
        // lower op sees the pre-pair state) needs the pipeline.
        (void)latency;
        pair.upperVfDirect = true;
    }

    // productSum and flagsDirect (FMAC MAC/status not read within latency).
    const auto isProductSum = [](uint32_t upper)
    {
        const uint8_t op = static_cast<uint8_t>(upper & 0x3Fu);
        const uint8_t special = op >= 0x3Cu ? static_cast<uint8_t>((upper & 3u) | ((upper >> 4) & 0x7Cu)) : 0xFFu;
        return (op >= 0x08u && op <= 0x0Fu) || op == 0x21u || op == 0x23u || op == 0x25u || op == 0x27u ||
               op == 0x29u || op == 0x2Du || op == 0x2Eu || (special >= 0x08u && special <= 0x0Fu) ||
               special == 0x21u || special == 0x23u || special == 0x25u || special == 0x27u ||
               special == 0x29u || special == 0x2Du;
    };
    const auto readsFlags = [](const DecodedInstructionPair &pair)
    {
        if (pair.iBit)
            return false;
        const uint32_t opHi = (pair.lower >> 25) & 0x7Fu;
        return opHi == 0x14u || opHi == 0x15u || opHi == 0x16u || opHi == 0x17u || opHi == 0x18u ||
               opHi == 0x1Au || opHi == 0x1Bu;
    };
    for (uint32_t i = 0; i < pairCount; ++i)
    {
        DecodedInstructionPair &pair = m_decodedCodeCache[i];
        pair.productSum = isProductSum(pair.upper);
        pair.flagsDirect = false;
        if (m_unit != Unit::VU1 || !directWrites || readsFlags(pair) || breaksFlow(pair) ||
            i + kFmacLatency > pairCount)
            continue;
        bool direct = true;
        for (uint32_t j = 1; j < kFmacLatency && direct; ++j)
        {
            const DecodedInstructionPair &later = m_decodedCodeCache[i + j];
            if (readsFlags(later) || (j + 1u < kFmacLatency && breaksFlow(later)))
                direct = false;
        }
        pair.flagsDirect = direct;
    }

    // flagsLive: with no status reader in the image (sticky bits unobservable),
    // the MAC/status of an FMAC pair is dead when a later FMAC pair in the same
    // straight-line run rewrites the whole MAC before any flag reader could see
    // it (MAC lanes outside dest are cleared, so any dest != 0 rewrites all 16
    // bits). Readers issued at least kFmacLatency pairs after that later pair
    // see the later write even with stalls, since stalls delay issue in order.
    const auto writesFmacFlags = [](const DecodedInstructionPair &pair)
    {
        if (((pair.upper >> 21) & 0xFu) == 0u)
            return false;
        uint8_t op = static_cast<uint8_t>(pair.upper & 0x3Fu);
        if (op >= 0x3Cu)
            op = static_cast<uint8_t>((pair.upper & 3u) | ((pair.upper >> 4) & 0x7Cu));
        return op <= 0x0Fu || (op >= 0x18u && op <= 0x1Cu) || op == 0x1Eu || (op >= 0x20u && op <= 0x2Au) ||
               (op >= 0x2Cu && op <= 0x2Eu);
    };
    // The search follows the control flow: a branch's delay slot runs, then
    // the target (and the fall-through for a conditional one). JR/JALR, the
    // end of the program, D/T stops and reserved code count as reads.
    struct FlowNode
    {
        uint32_t pc;
        int32_t pendingTarget; // set while pc is a branch delay slot
        bool pendingFallThrough;
        uint32_t window;       // >0: reader check after an overwriting pair
    };
    const auto branchInfo = [&](uint32_t pc, int32_t &target, bool &conditional)
    {
        // 0 = no branch, 1 = static branch, -1 = indirect
        const DecodedInstructionPair &pair = m_decodedCodeCache[pc];
        if (pair.iBit)
            return 0;
        const uint32_t opHi = (pair.lower >> 25) & 0x7Fu;
        if (opHi == 0x24u || opHi == 0x25u)
            return -1;
        if (opHi != 0x20u && opHi != 0x21u && (opHi < 0x28u || opHi > 0x2Fu || opHi == 0x2Au || opHi == 0x2Bu))
            return 0;
        const int32_t imm = static_cast<int32_t>(pair.lower << 21) >> 21;
        target = static_cast<int32_t>(pc) + 1 + imm;
        conditional = opHi >= 0x28u;
        return 1;
    };
    std::vector<uint32_t> visitedEpoch(pairCount, 0u);
    std::vector<FlowNode> work;
    uint32_t epoch = 0;
    // window 0: is the MAC of the pair at start dead? window n: is there no
    // flag reader in the n pairs that follow start on any path?
    const auto macDead = [&](uint32_t start, uint32_t initialWindow) -> bool
    {
        ++epoch;
        work.clear();
        work.push_back({start + 1u, -1, false, initialWindow});
        uint32_t budget = 1024u;
        while (!work.empty())
        {
            if (--budget == 0u)
                return false;
            const FlowNode node = work.back();
            work.pop_back();
            if (node.pc >= pairCount)
                return false;
            const DecodedInstructionPair &pair = m_decodedCodeCache[node.pc];
            if (readsFlags(pair) || pair.eBit || pair.dBit || pair.tBit || pair.upperUsage.reserved ||
                (!pair.iBit && pair.lowerUsage.reserved))
                return false;
            if (node.pendingTarget < 0 && node.window == 0u)
            {
                uint32_t &seen = visitedEpoch[node.pc];
                if (seen == epoch)
                    continue;
                seen = epoch;
            }
            uint32_t window = node.window;
            if (window != 0u)
            {
                if (--window == 0u)
                    continue; // no reader in the whole latency window
            }
            else if (writesFmacFlags(pair))
            {
                // This pair rewrites the whole MAC; readers in its next
                // kFmacLatency - 1 pairs may still see the older value.
                window = kFmacLatency - 1u;
                if (window == 0u)
                    continue;
            }
            if (node.pendingTarget >= 0)
            {
                // Delay slot: a branch here is not followed.
                int32_t t = 0;
                bool c = false;
                if (branchInfo(node.pc, t, c) != 0)
                    return false;
                if (node.pendingTarget >= static_cast<int32_t>(pairCount))
                    return false;
                work.push_back({static_cast<uint32_t>(node.pendingTarget), -1, false, window});
                if (node.pendingFallThrough)
                    work.push_back({node.pc + 1u, -1, false, window});
                continue;
            }
            int32_t target = 0;
            bool conditional = false;
            const int kind = branchInfo(node.pc, target, conditional);
            if (kind < 0 || (kind > 0 && target < 0))
                return false;
            if (kind > 0)
                work.push_back({node.pc + 1u, target, conditional, window});
            else
                work.push_back({node.pc + 1u, -1, false, window});
        }
        return true;
    };
    for (uint32_t i = 0; i < pairCount; ++i)
    {
        DecodedInstructionPair &pair = m_decodedCodeCache[i];
        pair.flagsLive = true;
        if (m_unit != Unit::VU1 || !directWrites || !writesFmacFlags(pair) || breaksFlow(pair))
            continue;
        int32_t previousTarget = 0;
        bool previousConditional = false;
        if (i > 0u && branchInfo(i - 1u, previousTarget, previousConditional) != 0)
            continue; // a delay slot: its successor is not i + 1
        if (!m_statusObservable)
            pair.flagsLive = !macDead(i, 0u);
        // Direct flags across branches: no reader within the latency window
        // on any path (the straight-line test above stops at a branch).
        if (pair.flagsLive && !pair.flagsDirect && !readsFlags(pair))
            pair.flagsDirect = macDead(i, kFmacLatency - 1u);
    }

    // PS2X_VU1_CAPTURE=<dir>: write each distinct VU1 microcode image once as
    // vu1_<fnv1a64>.bin, input for the VU1 code generator (game data: never
    // publish these files).
    m_compiledTable = nullptr;
    static const bool compiledEnabled = [] { const char *v = std::getenv("PS2X_VU1_COMPILED"); return !(v && *v == '0'); }();
    static const char *const captureDir = std::getenv("PS2X_VU1_CAPTURE");
    uint64_t hash = 0xCBF29CE484222325ull;
    if (m_unit == Unit::VU1 && vuCode && codeSize && (compiledEnabled || (captureDir && *captureDir)))
        for (uint32_t i = 0; i < codeSize; ++i)
            hash = (hash ^ vuCode[i]) * 0x100000001B3ull;
    // Generated pairs embed flag-liveness decisions from the default analysis.
    // Exact-flags mode must use the pairs rebuilt above, rather than a table
    // that can discard MAC/status writes even when they are now observable.
    if (m_unit == Unit::VU1 && compiledEnabled && !exactFlags && codeSize == 0x4000u && directWrites)
        m_compiledTable = vu1FindCompiledProgram(hash);
    if (captureDir && *captureDir && m_unit == Unit::VU1 && vuCode && codeSize)
    {
        char name[64];
        std::snprintf(name, sizeof(name), "vu1_%016llx.bin", static_cast<unsigned long long>(hash));
        const std::string path = std::string(captureDir) + "/" + name;
        if (std::FILE *existing = std::fopen(path.c_str(), "rb"))
            std::fclose(existing);
        else if (std::FILE *out = std::fopen(path.c_str(), "wb"))
        {
            std::fwrite(vuCode, 1, codeSize, out);
            std::fclose(out);
        }
    }

    m_cachedVuCode = vuCode;
    m_cachedMemory = memory;
    m_cachedCodeSize = codeSize;
    m_cachedCodeGeneration = generation;
    m_decodedCodeCacheValid = true;
}

void VU1Interpreter::exportDecodedPairs(const uint8_t *code, uint32_t size, std::vector<DecodedInstructionPair> &out)
{
    rebuildDecodedCodeCache(code, size, nullptr, 0);
    const uint32_t pairs = std::min<uint32_t>(size / 8u, kMaxDecodedPairs);
    out.assign(m_decodedCodeCache.begin(), m_decodedCodeCache.begin() + pairs);
    m_decodedCodeCacheValid = false;
    m_compiledTable = nullptr;
}

VU1Interpreter::DecodedInstructionPair VU1Interpreter::getDecodedInstructionPairForPc(
    const uint8_t *vuCode, uint32_t codeSize, PS2Memory *memory, uint32_t pc)
{
    if ((pc & 7u) != 0u)
        return decodeInstructionPair(vuCode, pc);

    const bool trackedVu1Code = memory != nullptr &&
                                ((m_unit == Unit::VU1 && vuCode == memory->getVU1Code()) ||
                                 (m_unit == Unit::VU0 && vuCode == memory->getVU0Code()));
    if (!trackedVu1Code)
        return decodeInstructionPair(vuCode, pc);

    const uint64_t generation = m_unit == Unit::VU1 ? memory->getVU1CodeGeneration() : memory->getVU0CodeGeneration();
    if (!m_decodedCodeCacheValid ||
        m_cachedVuCode != vuCode ||
        m_cachedMemory != memory ||
        m_cachedCodeSize != codeSize ||
        m_cachedCodeGeneration != generation)
    {
        rebuildDecodedCodeCache(vuCode, codeSize, memory, generation);
    }
    const uint32_t pairIndex = pc / 8u;
    if (pairIndex >= kMaxDecodedPairs)
        return decodeInstructionPair(vuCode, pc);
    return m_decodedCodeCache[pairIndex];
}

void VU1Interpreter::reportReservedInstruction(bool upper, uint32_t instruction)
{
    RUNTIME_ERROR(
        "[VU" << (m_unit == Unit::VU1 ? "1" : "0")
              << " reserved " << (upper ? "upper" : "lower")
              << "] cycle=" << m_cycle
              << " pc=0x" << std::hex << m_state.pc
              << " instruction=0x" << instruction
              << std::dec << '\n');
    m_stopRequested = true;
}

void VU1Interpreter::execute(uint8_t *vuCode, uint32_t codeSize,
                             uint8_t *vuData, uint32_t dataSize,
                             GS &gs, PS2Memory *memory,
                             uint32_t startPC, uint32_t top, uint32_t itop,
                             uint32_t maxCycles)
{
    resetScheduler();
    m_state.pc = startPC & microAddressMask();
    m_state.ebit = false;
    m_state.haltAfterDelaySlot = false;
    m_state.stoppedByD = false;
    m_state.stoppedByT = false;
    m_state.top = top;
    m_state.itop = itop;
    m_state.branchPending = false;
    m_state.branchTarget = 0;
    m_state.branchDelay = 0;
    m_state.vf[0][0] = 0.0f;
    m_state.vf[0][1] = 0.0f;
    m_state.vf[0][2] = 0.0f;
    m_state.vf[0][3] = 1.0f;
    run(vuCode, codeSize, vuData, dataSize, gs, memory, maxCycles);
}

void VU1Interpreter::resume(uint8_t *vuCode, uint32_t codeSize,
                            uint8_t *vuData, uint32_t dataSize,
                            GS &gs, PS2Memory *memory,
                            uint32_t top, uint32_t itop, uint32_t maxCycles)
{
    m_state.top = top;
    m_state.itop = itop;
    m_state.stoppedByD = false;
    m_state.stoppedByT = false;
    run(vuCode, codeSize, vuData, dataSize, gs, memory, maxCycles);
}

#include "ps2_vu1_step.inl"

void VU1Interpreter::run(uint8_t *vuCode, uint32_t codeSize,
                         uint8_t *vuData, uint32_t dataSize,
                         GS &gs, PS2Memory *memory, uint32_t maxCycles)
{
    m_activeVuData = vuData;
    m_activeVuDataSize = dataSize;
    m_activeGs = &gs;
    m_activeMemory = memory;

    // Preserve the CRT path as the default/reference until replay acceptance.
    // Restore only rounding bits: restoring all of MXCSR would discard accrued
    // exception flags. This optimization has been audited only on Windows x64.
#if defined(_WIN32) && (defined(_M_X64) || defined(__x86_64__))
    static const bool useMxcsrRounding = [] {
        const char *value = std::getenv("PS2X_VU1_MXCSR_ROUNDING");
        return value && *value == '1';
    }();
    const unsigned previousCsr = useMxcsrRounding ? _mm_getcsr() : 0u;
#else
    constexpr bool useMxcsrRounding = false;
#endif
    const int previousRoundingMode = useMxcsrRounding ? -1 : std::fegetround();
    const bool useVuRounding = !useMxcsrRounding && std::fesetround(FE_TOWARDZERO) == 0;
#if defined(_WIN32) && (defined(_M_X64) || defined(__x86_64__))
    if (useMxcsrRounding)
        _mm_setcsr((previousCsr & ~0x6000u) | 0x6000u);
#endif
    const uint64_t budgetEnd = m_cycle + maxCycles;
    const uint64_t runStartCycle = m_cycle;
    bool programEnded = false;
    // Set once getDecodedInstructionPairForPc has validated the cache against
    // the code generation for this run (code memory is fixed while VU1 runs).
    bool cacheChecked = false;
    bool compiledCacheChecked = false;
    static const bool dispatchReference = [] {
        const char *value = std::getenv("PS2X_VU1_DISPATCH_REFERENCE");
        return value && *value == '1';
    }();
    while (m_cycle < budgetEnd && !m_stopRequested)
    {
        if (m_cycle >= m_nextCommitCycle || vu1ScanAll())
            commitReadyPipelines();
        if (m_state.pc + 8u > codeSize)
            break;

        // Validate the code generation through the existing decoded lookup on
        // the first pair of each run/resume. Code memory is fixed within run;
        // compiled steps already install the four per-pair analysis flags.
        // Avoid loading the large decoded pair and setting those flags twice.
        // Unaligned PCs retain the original lookup/decoding behavior.
        if (compiledCacheChecked && (m_state.pc & 7u) == 0u)
        {
            if (m_compiledTable[m_state.pc / 8u](*this, vuData, dataSize, gs, memory,
                                               codeSize, budgetEnd, programEnded))
                break;
            continue;
        }

        // The decoded cache holds every aligned pair of the current microcode;
        // use the entry in place instead of copying the (large) struct.
        DecodedInstructionPair decodedCopy;
        const DecodedInstructionPair *decodedEntry = nullptr;
        if ((m_state.pc & 7u) == 0u && m_decodedCodeCacheValid && m_cachedVuCode == vuCode &&
            m_cachedCodeSize == codeSize && m_state.pc / 8u < kMaxDecodedPairs && cacheChecked)
            decodedEntry = &m_decodedCodeCache[m_state.pc / 8u];
        else
        {
            decodedCopy = getDecodedInstructionPairForPc(vuCode, codeSize, memory, m_state.pc);
            decodedEntry = &decodedCopy;
            cacheChecked = m_decodedCodeCacheValid && m_cachedVuCode == vuCode;
        }
        const DecodedInstructionPair &decoded = *decodedEntry;
        compiledCacheChecked = !dispatchReference && m_compiledTable && decodedEntry != &decodedCopy;
        m_pairFlagsDirect = decodedEntry != &decodedCopy && decoded.flagsDirect;
        m_pairStoreDirect = decodedEntry != &decodedCopy && decoded.storeDirect;
        m_pairFlagsLive = decodedEntry == &decodedCopy || decoded.flagsLive;
        m_pairProductSum = decodedEntry == &decodedCopy || decoded.productSum;
        const int leave = (m_compiledTable && decodedEntry != &decodedCopy)
                              ? m_compiledTable[m_state.pc / 8u](*this, vuData, dataSize, gs, memory, codeSize,
                                                                 budgetEnd, programEnded)
                              : stepPairBody(decoded, vuData, dataSize, gs, memory, codeSize, budgetEnd, programEnded);
        if (leave)
            break;
    }

    if (programEnded)
    {
        flushPipelines();
        m_state.ebit = false;
        m_state.haltAfterDelaySlot = false;
        m_pendingHaltD = false;
        m_pendingHaltT = false;
    }
    m_state.cycles = m_cycle;
    if (m_unit == Unit::VU1)
    {
        g_vu1Cycles += m_cycle - runStartCycle;
        ++g_vu1Runs;
    }
#if defined(_WIN32) && (defined(_M_X64) || defined(__x86_64__))
    if (useMxcsrRounding)
        _mm_setcsr((_mm_getcsr() & ~0x6000u) | (previousCsr & 0x6000u));
#endif
    if (useVuRounding && previousRoundingMode != -1)
        std::fesetround(previousRoundingMode);
}

// One translation unit for the whole interpreter: the per-pair step, the
// upper/lower executors and compiled microprograms can then be inlined into
// each other and constant-folded.
#include "ps2_vu1_upper.cpp"
#include "ps2_vu1_lower.cpp"
#include "generated/vu1_compiled_programs.inc"

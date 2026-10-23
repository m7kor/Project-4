// Shared scheduling body: deliberately no include guard.
// The caller supplies decoded, vu, PS2X_VU1_ISSUE_UPPER and the original run arguments.

    if (decoded.upperUsage.reserved || decoded.lowerUsage.reserved)
    {
        vu.reportReservedInstruction(decoded.upperUsage.reserved, decoded.upperUsage.reserved ? decoded.upper : decoded.lower);
        return 1;
    }

    uint64_t readyCycle = vu.calculatePairReadyCycle(decoded);
    while (readyCycle > vu.m_cycle)
    {
        if (readyCycle >= budgetEnd)
        {
            vu.advanceTo(budgetEnd);
            break;
        }
        vu.advanceTo(readyCycle);
        readyCycle = vu.calculatePairReadyCycle(decoded);
    }
    if (vu.m_cycle >= budgetEnd)
        return 1;

    uint8_t writtenVi = 0u;
    int32_t oldVi = 0;
    if (const uint32_t viWrites = decoded.lowerUsage.viWrite & 0xFFFEu)
    {
        writtenVi = static_cast<uint8_t>(std::countr_zero(viWrites));
        oldVi = vu.m_state.vi[writtenVi];
    }

    const VU1Interpreter::VfAccess upperWrite = decoded.upperUsage.vfWrite;
    const VU1Interpreter::VfAccess lowerWrite = decoded.lowerUsage.vfWrite;
    const bool hasUpperWrite = upperWrite.reg != 0u;
    const bool hasLowerWrite = lowerWrite.reg != 0u && decoded.suppressedLowerVf != lowerWrite.reg;
    const bool hasDistinctLowerWrite = hasLowerWrite && (!hasUpperWrite || lowerWrite.reg != upperWrite.reg);
    float oldUpperVf[4]{};
    float newUpperVf[4]{};
    float oldLowerVf[4]{};
    float newLowerVf[4]{};
    float oldAcc[4]{};
    float newAcc[4]{};
    if (hasUpperWrite && !decoded.upperVfDirect)
        std::memcpy(oldUpperVf, vu.m_state.vf[upperWrite.reg], sizeof(oldUpperVf));
    if (hasDistinctLowerWrite && !decoded.lowerVfDirect)
        std::memcpy(oldLowerVf, vu.m_state.vf[lowerWrite.reg], sizeof(oldLowerVf));
    if (decoded.upperUsage.accWrite != 0u && !decoded.accDirect)
        std::memcpy(oldAcc, vu.m_state.acc, sizeof(oldAcc));

    if (decoded.iBit)
    {
        PS2X_VU1_ISSUE_UPPER(decoded.upper);
        float immediate = 0.0f;
        std::memcpy(&immediate, &decoded.lower, sizeof(immediate));
        vu.m_state.i = vu.normalizeOperand(immediate);
    }
    else if (decoded.upperVfShadowReg != 0u)
    {
        float oldVf[4]{};
        float upperVf[4]{};
        std::memcpy(oldVf,
                    vu.m_state.vf[decoded.upperVfShadowReg],
                    sizeof(oldVf));
        PS2X_VU1_ISSUE_UPPER(decoded.upper);
        std::memcpy(upperVf,
                    vu.m_state.vf[decoded.upperVfShadowReg],
                    sizeof(upperVf));
        std::memcpy(vu.m_state.vf[decoded.upperVfShadowReg],
                    oldVf,
                    sizeof(oldVf));
        vu.execLower(decoded.lower, vuData, dataSize, gs, memory, decoded.upper);
        std::memcpy(vu.m_state.vf[decoded.upperVfShadowReg],
                    upperVf,
                    sizeof(upperVf));
    }
    else
    {
        PS2X_VU1_ISSUE_UPPER(decoded.upper);
        vu.execLower(decoded.lower, vuData, dataSize, gs, memory, decoded.upper);
    }

    vu.m_viBranchBackupValid = false;

    if (hasUpperWrite && decoded.upperVfDirect)
    {
        // Keep the value written by execUpper; supersede any older pending
        // write to these lanes so it cannot land later.
        const uint64_t sequence = ++vu.m_nextWriteSequence;
        for (uint32_t component = 0; component < 4u; ++component)
            if ((upperWrite.lanes & laneForComponent(component)) != 0u)
                vu.m_vfLatestWrite[upperWrite.reg][component] = sequence;
    }
    else if (hasUpperWrite)
    {
        std::memcpy(newUpperVf, vu.m_state.vf[upperWrite.reg], sizeof(newUpperVf));
        std::memcpy(vu.m_state.vf[upperWrite.reg], oldUpperVf, sizeof(oldUpperVf));
        const uint32_t latency =
            decoded.upperUsage.vfLatency != 0u
                ? decoded.upperUsage.vfLatency
                : decoded.upperUsage.latency;
        vu.queueVfWrite(upperWrite.reg, upperWrite.lanes, newUpperVf, latency);
    }
    if (hasDistinctLowerWrite && decoded.lowerVfDirect)
    {
        const uint64_t sequence = ++vu.m_nextWriteSequence;
        for (uint32_t component = 0; component < 4u; ++component)
            if ((lowerWrite.lanes & laneForComponent(component)) != 0u)
                vu.m_vfLatestWrite[lowerWrite.reg][component] = sequence;
    }
    else if (hasDistinctLowerWrite)
    {
        std::memcpy(newLowerVf, vu.m_state.vf[lowerWrite.reg], sizeof(newLowerVf));
        std::memcpy(vu.m_state.vf[lowerWrite.reg], oldLowerVf, sizeof(oldLowerVf));
        const uint32_t latency = decoded.lowerUsage.vfLatency != 0u
                                     ? decoded.lowerUsage.vfLatency
                                     : decoded.lowerUsage.latency;
        vu.queueVfWrite(lowerWrite.reg, lowerWrite.lanes, newLowerVf, latency);
    }
    if (decoded.upperUsage.accWrite != 0u && decoded.accDirect)
    {
        const uint64_t sequence = ++vu.m_nextWriteSequence;
        for (uint32_t component = 0; component < 4u; ++component)
            if ((decoded.upperUsage.accWrite & laneForComponent(component)) != 0u)
                vu.m_accLatestWrite[component] = sequence;
    }
    else if (decoded.upperUsage.accWrite != 0u)
    {
        std::memcpy(newAcc, vu.m_state.acc, sizeof(newAcc));
        std::memcpy(vu.m_state.acc, oldAcc, sizeof(oldAcc));
        // ACC is forwarded to the next upper instruction. Its arithmetic
        // flags still use the normal four-cycle FMAC timeline.
        vu.queueAccWrite(decoded.upperUsage.accWrite, newAcc,
                      VU1Interpreter::kAccForwardLatency);
    }
    if (writtenVi != 0u && decoded.viDirect)
    {
        vu.m_viLatestWrite[writtenVi] = ++vu.m_nextWriteSequence;
    }
    else if (writtenVi != 0u)
    {
        const int32_t newVi = vu.m_state.vi[writtenVi];
        vu.m_state.vi[writtenVi] = oldVi;
        const uint32_t latency =
            decoded.lowerUsage.viLatency != 0u
                ? decoded.lowerUsage.viLatency
                : decoded.lowerUsage.latency;
        vu.queueViWrite(writtenVi, newVi, latency);
    }

    vu.markPairWrites(decoded);
    if (writtenVi != 0u && decoded.lowerUsage.delaysNextBranchRead)
        vu.recordViWriteForBranch(writtenVi, oldVi);

    vu.m_state.vf[0][0] = 0.0f;
    vu.m_state.vf[0][1] = 0.0f;
    vu.m_state.vf[0][2] = 0.0f;
    vu.m_state.vf[0][3] = 1.0f;
    vu.m_state.vi[0] = 0;

    uint32_t nextPc = vu.m_state.pc + 8u;
    if (nextPc >= codeSize)
        nextPc = 0u;
    vu.m_state.pc = nextPc;

    if (vu.m_state.branchPending)
    {
        if (vu.m_state.branchDelay == 0u)
        {
            vu.m_state.pc = vu.m_state.branchTarget & vu.microAddressMask();
            vu.m_state.branchPending = false;
        }
        else
        {
            --vu.m_state.branchDelay;
        }
    }

    const bool dHalt = decoded.dBit && vu.m_state.dBitEnabled;
    const bool tHalt = decoded.tBit && vu.m_state.tBitEnabled;
    const bool haltBit = dHalt || tHalt;
    const bool haltBranch = haltBit && decoded.lowerUsage.pipeline == VU1Interpreter::PipelineBranch;

    if (vu.m_state.haltAfterDelaySlot)
    {
        vu.m_state.stoppedByD = vu.m_pendingHaltD;
        vu.m_state.stoppedByT = vu.m_pendingHaltT;
        programEnded = true;
    }
    else if (vu.m_state.ebit)
        programEnded = true;
    else if (haltBit && !haltBranch)
    {
        vu.m_state.stoppedByD = dHalt;
        vu.m_state.stoppedByT = tHalt;
        programEnded = true;
    }
    else if (decoded.eBit)
        vu.m_state.ebit = true;
    else if (haltBranch)
    {
        vu.m_state.haltAfterDelaySlot = true;
        vu.m_pendingHaltD = dHalt;
        vu.m_pendingHaltT = tHalt;
    }

    vu.advanceOneCycle();
    if (programEnded)
        return 1;
    return 0;

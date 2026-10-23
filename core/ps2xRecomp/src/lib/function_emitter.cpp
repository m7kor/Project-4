#include "ps2recomp/Emitters/function_emitter.h"
#include "ps2recomp/code_generator.h"
#include "ps2recomp/gif_dma_kick_analyzer.h"
#include "ps2recomp/instructions.h"
#include "ps2recomp/r5900_decoder.h"
#include "ps2recomp/recompiler_reporter.h"
#include "ps2recomp/types.h"

#include <algorithm>
#include <cstring>
#include <sstream>
#include <stdexcept>
#include <unordered_set>

namespace ps2recomp
{
    namespace
    {
        // LODESTONE PATCH 15 - the delay slot of a branch is a real instruction
        // and it used to be replaced by a NOP whenever it fell outside the
        // decoded function body.
        //
        // A function body is decoded half-open, [start, end). When a branch is
        // the LAST decoded instruction of a function, the word at pc+4 is
        // outside the body, so `makeSyntheticDelaySlot()` fabricated
        // `sll $zero,$zero,0` and the real instruction never ran. That is not a
        // cosmetic omission: on RE4 the delay slot of the final `jr $ra` at
        // 0x2A1CC0 is `daddu $v0, $a0, $zero` at 0x2A1CC4 - the instruction
        // that returns the FOUND ADDRESS in $v0 from FUN_002A1C88 - and the
        // caller FUN_002A1CE0 merges on exactly that address. With the slot
        // dropped the handler returned the loop predicate (1), both cursors
        // collapsed to 1 and the boot loop could never converge.
        //
        // The function map is DATA and can be wrong; the ELF bytes are ground
        // truth. So read the word instead of inventing it, and only fall back
        // to a NOP when the address is not mapped at all.
        // dead_ends.jsonl#0085.
        Instruction decodeDelaySlot(const std::vector<Section> &sections, uint32_t address)
        {
            for (const auto &section : sections)
            {
                if (address < section.address || section.size < sizeof(uint32_t) || section.data == nullptr)
                {
                    continue;
                }

                const uint32_t offset = address - section.address;
                if (offset > section.size - static_cast<uint32_t>(sizeof(uint32_t)))
                {
                    continue;
                }

                uint32_t raw = 0;
                std::memcpy(&raw, section.data + offset, sizeof(raw));

                R5900Decoder decoder;
                return decoder.decodeInstruction(address, raw, /*includeDisassembly=*/false);
            }

            Instruction inst{};
            inst.address = address;
            inst.raw = 0;
            inst.opcode = OPCODE_SPECIAL;
            inst.function = SPECIAL_SLL;
            return inst;
        }
    }

    FunctionEmitter::FunctionEmitter(CodeGenerator &codeGenerator)
        : m_codeGenerator(codeGenerator)
    {
    }

    std::string FunctionEmitter::emit(
        const Function &function,
        const std::vector<Instruction> &instructions,
        bool useHeaders)
    {
        CodeGenerator &cg = m_codeGenerator;
        std::stringstream ss;
        cg.m_currentFunctionName = function.name;

        if (useHeaders)
        {
            ss << "#include <stdexcept>\n";
            ss << "#include \"ps2_runtime_macros.h\"\n";
            ss << "#include \"ps2_runtime.h\"\n";
            // Delay slots outside the original range may write FBRST too.
            ss << "#include \"runtime/ps2_vu_control.h\"\n";
            // Direct transfers declare only the target they use. Depending on
            // the entire function map here rebuilds every body for one new entry.
            ss << "#include <ps2_recompiled_stubs.h>\n\n";
            ss << "#include \"ps2_syscalls.h\"\n";
            ss << "#include \"ps2_stubs.h\"\n\n";
            ss << "#ifdef PS2_FUNCTION_LOG_TRACKER\n";
            ss << "#include \"ps2_log.h\"\n";
            ss << "#endif\n\n";
        }

        CodeGenerator::AnalysisResult analysisResult = cg.collectInternalBranchTargets(function, instructions);
        std::vector<uint32_t> resumeTargets(analysisResult.resumeEntryPoints.begin(),
                                            analysisResult.resumeEntryPoints.end());
        auto resumeIt = cg.m_resumeEntryTargetsByOwner.find(function.start);
        if (resumeIt != cg.m_resumeEntryTargetsByOwner.end())
        {
            resumeTargets.insert(resumeTargets.end(), resumeIt->second.begin(), resumeIt->second.end());
        }
        std::sort(resumeTargets.begin(), resumeTargets.end());
        resumeTargets.erase(std::unique(resumeTargets.begin(), resumeTargets.end()), resumeTargets.end());
        for (uint32_t target : resumeTargets)
        {
            analysisResult.entryPoints.insert(target);
        }

        const std::unordered_set<uint32_t> &internalTargets = analysisResult.entryPoints;
        ConstantRegisterState constantRegisters;
        // Static address folding and GIF kick recognition cannot consume the
        // pre-relocation LUI/LO constants of a dynamically patched image.
        const bool dynamicOperands = !cg.m_runtimeInstructionRelocations.empty() || cg.hasRelocatableCodeRange();
        GifDmaKickPlan gifDmaKickPlan{};
        ss << "// Function: " << function.name << "\n";
        ss << "// Address: 0x" << std::hex << function.start << " - 0x" << function.end << std::dec << "\n";

        std::string sanitizedName = cg.getFunctionName(function.start);
        if (sanitizedName.empty())
        {
            std::stringstream nameBuilder;
            nameBuilder << "Errorfunc_" << std::hex << function.start;
            sanitizedName = nameBuilder.str();
        }

        ss << "void " << sanitizedName << "(uint8_t* rdram, R5900Context* ctx, PS2Runtime *runtime";
        if (cg.hasRelocatableCodeRange())
            ss << ", uint32_t ps2_module_base";
        ss << ") {\n";
        ss << "#ifdef PS2_FUNCTION_LOG_TRACKER\n";
        ss << "    PS_LOG_ENTRY(\"" << sanitizedName << "\");\n";
        ss << "#endif\n";
        ss << "\n";
        if (cg.hasRelocatableCodeRange())
        {
            if (function.start < cg.m_relocatableVirtualStart || function.end <= function.start ||
                static_cast<uint64_t>(function.start) >= static_cast<uint64_t>(cg.m_relocatableVirtualStart) + cg.m_relocatableSize ||
                static_cast<uint64_t>(function.end) > static_cast<uint64_t>(cg.m_relocatableVirtualStart) + cg.m_relocatableSize)
                throw std::invalid_argument("Function lies outside relocatable code range");
            ss << "    if ((ps2_module_base & 3u) != 0u || ps2_module_base > 0x"
               << std::hex << (0xFFFFFFFFu - cg.m_relocatableSize) << "u) { throw std::invalid_argument(\"Invalid module load base\"); }\n" << std::dec;
        }
        if (!resumeTargets.empty())
        {
            if (cg.hasRelocatableCodeRange())
                ss << "    switch (ctx->pc - ps2_module_base + 0x" << std::hex << cg.m_relocatableVirtualStart << "u) {\n" << std::dec;
            else
                ss << "    switch (ctx->pc) {\n";
            for (uint32_t target : resumeTargets)
            {
                ss << "        case 0x" << std::hex << target << "u: goto label_" << target << ";\n"
                   << std::dec;
            }
            ss << "        default: break;\n";
            ss << "    }\n\n";
        }
        if (cg.hasRelocatableCodeRange())
            ss << "    ctx->pc = " << cg.codeAddressExpression(function.start) << ";\n";
        else
            ss << "    ctx->pc = 0x" << std::hex << function.start << "u;\n" << std::dec;
        ss << "\n";

        bool lastInstructionWasControlFlow = false;

        for (size_t i = 0; i < instructions.size(); ++i)
        {
            const Instruction &inst = instructions[i];
            lastInstructionWasControlFlow = inst.hasDelaySlot;

            if (internalTargets.contains(inst.address))
            {
                constantRegisters.clear();
                ss << "label_" << std::hex << inst.address << std::dec << ":\n";
            }

            if (cg.m_emitInstructionComments)
            {
                ss << "    // 0x" << std::hex << inst.address << ": 0x" << inst.raw << std::dec;
                std::string disassembly = R5900Decoder::disassembleInstruction(inst);
                if (!disassembly.empty())
                {
                    ss << "  " << disassembly;
                }
                ss << "\n";
            }

            try
            {
                if (inst.hasDelaySlot)
                {
                    const bool hasDecodedDelaySlot =
                        i + 1 < instructions.size() &&
                        instructions[i + 1].address == inst.address + 4u;

                    Instruction syntheticDelaySlot{};
                    const Instruction *delaySlot = nullptr;
                    if (hasDecodedDelaySlot)
                    {
                        delaySlot = &instructions[i + 1];
                    }
                    else
                    {
                        syntheticDelaySlot = decodeDelaySlot(cg.m_sections, inst.address + 4u);
                        delaySlot = &syntheticDelaySlot;
                    }

                    if (hasDecodedDelaySlot && internalTargets.contains(delaySlot->address))
                    {
                        ss << "label_" << std::hex << delaySlot->address << std::dec << ":\n";
                    }

                    if (gifDmaKickPlan.valid &&
                        gifDmaKickPlan.completesInDelaySlot &&
                        gifDmaKickPlan.branchIndex == i &&
                        hasDecodedDelaySlot)
                    {
                        ss << cg.handleBranchDelaySlots(
                            inst,
                            *delaySlot,
                            function,
                            analysisResult,
                            gifDmaDelaySlotOverride(*delaySlot, gifDmaKickPlan, cg.m_emitInstructionComments));
                        gifDmaKickPlan = {};
                    }
                    else
                    {
                        ss << cg.handleBranchDelaySlots(inst, *delaySlot, function, analysisResult);
                    }

                    if (hasDecodedDelaySlot)
                    {
                        ++i; // Skip delay slot instruction (handled inside branch logic)
                    }
                    constantRegisters.clear();
                }
                else
                {
                    if (!dynamicOperands && !gifDmaKickPlan.valid)
                    {
                        gifDmaKickPlan = tryBuildGifDmaKickPlan(instructions, i, constantRegisters, internalTargets);
                    }

                    if (gifDmaKickPlan.suppresses(i))
                    {
                        const size_t slot = gifDmaKickPlan.slotFor(i);
                        emitGifDmaCapture(ss, gifDmaKickPlan, slot, "    ");

                        if (gifDmaKickPlan.completesAt(i))
                        {
                            ss << "    ctx->pc = 0x" << std::hex << inst.address << "u;\n"
                               << std::dec;
                            ss << "    " << gifDmaKickCall(gifDmaKickPlan) << "\n";
                            gifDmaKickPlan = {};
                        }

                        updateConstantRegisters(inst, constantRegisters);
                        continue;
                    }

                    if (cg.hasRelocatableCodeRange())
                        ss << "    ctx->pc = " << cg.codeAddressExpression(inst.address) << ";\n";
                    else
                        ss << "    ctx->pc = 0x" << std::hex << inst.address << "u;\n" << std::dec;
                    const MemoryAccessHint memoryHint = dynamicOperands ? MemoryAccessHint{} : resolveMemoryAccessHint(inst, constantRegisters);
                    ss << "    " << cg.translateInstruction(inst, memoryHint);
                    if (inst.isMmio)
                    {
                        ss << " // MMIO: 0x" << std::hex << inst.mmioAddress << std::dec;
                    }
                    ss << "\n";

                    if (!dynamicOperands)
                        updateConstantRegisters(inst, constantRegisters);
                }
            }
            catch (const std::exception &e)
            {
                if (cg.m_reporter)
                {
                    std::ostringstream msg;
                    msg << "translation failed: " << e.what() << " raw=0x" << std::hex << inst.raw;
                    cg.m_reporter->errorAt("codegen", function.name, inst.address, msg.str());
                }

                throw;
            }
        }

        // Fallthrough with no terminating branch: publish the next PC so the EE dispatcher does not re-enter this function.
        if (!instructions.empty() && !lastInstructionWasControlFlow)
        {
            if (cg.hasRelocatableCodeRange())
                ss << "    ctx->pc = " << cg.codeAddressExpression(function.end) << ";\n";
            else
                ss << "    ctx->pc = 0x" << std::hex << function.end << "u;\n" << std::dec;
        }

        ss << "}\n";
        return ss.str();
    }
}

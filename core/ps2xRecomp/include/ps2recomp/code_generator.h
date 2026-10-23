#ifndef PS2RECOMP_CODE_GENERATOR_H
#define PS2RECOMP_CODE_GENERATOR_H

#include <cstdint>
#include <string>
#include <vector>
#include <map>
#include <unordered_map>
#include <unordered_set>
#include "ps2recomp/control_flow_analyzer.h"

namespace ps2recomp
{
	struct JumpTableEntry;
    struct JumpTable;
	struct Instruction;
    struct MemoryAccessHint;
	struct Function;
	struct Symbol;
	struct Section;
    class RecompilerReporter;

	extern const std::unordered_set<std::string> kKeywords;

    class CodeGenerator
    {
    public:
	    explicit CodeGenerator(const std::vector<Symbol> &symbols, const std::vector<Section> &sections);
        ~CodeGenerator();

        struct BootstrapInfo
        {
            bool valid = false;
            uint32_t entry = 0;
            uint32_t bssStart = 0;
            uint32_t bssEnd = 0;
            uint32_t gp = 0;
            std::string entryName;
        };

        using AnalysisResult = ControlFlowAnalysisResult;

        std::string generateFunction(const Function &function, const std::vector<Instruction> &instructions, const bool &useHeaders);
        std::string generateFunctionRegistration(const std::vector<Function> &functions, const std::map<uint32_t, std::string> &stubs);

		// LODESTONE PATCH 18 note: the sparse entry list (entries outside the
		// first dense cluster, e.g. code the game installs at 0x80076000) is a
		// local of FunctionTableEmitter::emit — it is consumed inside that one
		// function and must not be state here. It was declared here, which left
		// function_table_emitter.cpp referencing a member it did not have and
		// therefore never compiled.
        std::string handleBranchDelaySlots(const Instruction &branchInst, const Instruction &delaySlot,
                                           const Function &function, const AnalysisResult &analysisResult);
        std::string handleBranchDelaySlots(const Instruction &branchInst, const Instruction &delaySlot,
                                           const Function &function, const AnalysisResult &analysisResult,
                                           std::string delaySlotOverride);

        void setRenamedFunctions(const std::unordered_map<uint32_t, std::string> &renames);
        void setBootstrapInfo(const BootstrapInfo &info);
        void setRelocationCallNames(const std::unordered_map<uint32_t, std::string> &callNames);
        // AOT instruction bodies remain native; only relocated operands are
        // read from the image already patched by the original guest loader.
        void setRuntimeInstructionRelocations(const std::unordered_map<uint32_t, uint32_t> &types);
        uint32_t runtimeInstructionRelocationType(uint32_t address) const;
        // Relocatable bodies receive a fourth argument, ps2_module_base.
        // Addresses in the declared virtual range become module-relative.
        void setRelocatableCodeRange(uint32_t virtualStart, uint32_t size);
        void clearRelocatableCodeRange();
        bool hasRelocatableCodeRange() const;
        std::string codeAddressExpression(uint32_t address) const;
        void setConfiguredJumpTables(const std::vector<JumpTable> &jumpTables);
        void setResumeEntryTargets(const std::unordered_map<uint32_t, std::vector<uint32_t>> &resumeTargetsByOwner);
        void setEmitInstructionComments(bool emitInstructionComments);
        void setReporter(RecompilerReporter *reporter);

        AnalysisResult collectInternalBranchTargets(const Function &function,
                                                  const std::vector<Instruction> &instructions,
                                                  const std::vector<Function> *allFunctions = nullptr);

    public:
        std::unordered_map<uint32_t, Symbol> m_symbols;
        std::unordered_map<uint32_t, std::string> m_renamedFunctions;
        std::unordered_map<uint32_t, std::string> m_relocationCallNames;
        std::unordered_map<uint32_t, uint32_t> m_runtimeInstructionRelocations;
        bool m_relocatableCode = false;
        uint32_t m_relocatableVirtualStart = 0;
        uint32_t m_relocatableSize = 0;
        std::unordered_map<uint32_t, std::vector<uint32_t>> m_configJumpTableTargetsByAddress;
        std::unordered_map<uint32_t, std::vector<uint32_t>> m_resumeEntryTargetsByOwner;
        // Own section metadata: callers may pass a temporary vector (including
        // an empty one). Section payload storage still belongs to the ELF.
        const std::vector<Section> m_sections;
        BootstrapInfo m_bootstrapInfo;
        bool m_emitInstructionComments = true;
        RecompilerReporter *m_reporter = nullptr;
        std::string m_currentFunctionName;

        std::string translateInstruction(const Instruction &inst);
        std::string translateInstruction(const Instruction &inst, const MemoryAccessHint &memoryHint);
        std::string emitUnhandledInstruction(const Instruction &inst, const std::string &message);
        std::string translateMMIInstruction(const Instruction &inst);
        std::string translateVUInstruction(const Instruction &inst);
        std::string translateFPUInstruction(const Instruction &inst);
        std::string translateCOP0Instruction(const Instruction &inst);
        std::string translateRegimmInstruction(const Instruction &inst);
        std::string translateSpecialInstruction(const Instruction &inst);

        // MMI Translation functions
        std::string translateMMI0Instruction(const Instruction &inst);
        std::string translateMMI1Instruction(const Instruction &inst);
        std::string translateMMI2Instruction(const Instruction &inst);
        std::string translateMMI3Instruction(const Instruction &inst);
        std::string translatePMFHLInstruction(const Instruction &inst);
        std::string translatePMTHLInstruction(const Instruction &inst);

        // Instruction Helpers
        std::string translateQFSRV(const Instruction &inst);
        std::string translatePMADDW(const Instruction &inst);
        std::string translatePMULTW(const Instruction &inst);
        std::string translatePMSUBW(const Instruction &inst);
        std::string translatePEXT5(const Instruction &inst);
        std::string translatePPAC5(const Instruction &inst);
        std::string translatePADSBH(const Instruction &inst);
        std::string translatePMSUBH(const Instruction &inst);
        std::string translatePHMSBH(const Instruction &inst);
        std::string translatePMADDUW(const Instruction &inst);
        std::string translatePDIVW(const Instruction &inst);
        std::string translatePCPYLD(const Instruction &inst);
        std::string translatePMADDH(const Instruction &inst);
        std::string translatePHMADH(const Instruction &inst);
        std::string translatePEXEH(const Instruction &inst);
        std::string translatePREVH(const Instruction &inst);
        std::string translatePMULTH(const Instruction &inst);
        std::string translatePDIVBW(const Instruction &inst);
        std::string translatePEXEW(const Instruction &inst);
        std::string translatePROT3W(const Instruction &inst);
        std::string translatePMULTUW(const Instruction &inst);
        std::string translatePDIVUW(const Instruction &inst);
        std::string translatePCPYUD(const Instruction &inst);
        std::string translatePEXCH(const Instruction &inst);
        std::string translatePCPYH(const Instruction &inst);
        std::string translatePEXCW(const Instruction &inst);
        std::string translatePMTHI(const Instruction &inst);
        std::string translatePMTLO(const Instruction &inst);

        // VU instruction translations
        std::string translateVU_VADD_Field(const Instruction &inst);
        std::string translateVU_VSUB_Field(const Instruction &inst);
        std::string translateVU_VMUL_Field(const Instruction &inst);
        std::string translateVU_VMSUB_Field(const Instruction &inst);
        std::string translateVU_VADDA_Field(const Instruction &inst);
        std::string translateVU_VSUBA_Field(const Instruction &inst);
        std::string translateVU_VMADDA_Field(const Instruction &inst);
        std::string translateVU_VMSUBA_Field(const Instruction &inst);
        std::string translateVU_VMULA_Field(const Instruction &inst);
        std::string translateVU_VADD(const Instruction &inst);
        std::string translateVU_VSUB(const Instruction &inst);
        std::string translateVU_VMUL(const Instruction &inst);
        std::string translateVU_VDIV(const Instruction &inst);
        std::string translateVU_VSQRT(const Instruction &inst);
        std::string translateVU_VRSQRT(const Instruction &inst);
        std::string translateVU_VMTIR(const Instruction &inst);
        std::string translateVU_VMFIR(const Instruction &inst);
        std::string translateVU_VILWR(const Instruction &inst);
        std::string translateVU_VISWR(const Instruction &inst);
        std::string translateVU_VIADD(const Instruction &inst);
        std::string translateVU_VISUB(const Instruction &inst);
        std::string translateVU_VIADDI(const Instruction &inst);
        std::string translateVU_VIAND(const Instruction &inst);
        std::string translateVU_VIOR(const Instruction &inst);
        std::string translateVU_VCALLMS(const Instruction &inst);
        std::string translateVU_VCALLMSR(const Instruction &inst);
        std::string translateVU_VRNEXT(const Instruction &inst);
        std::string translateVU_VRGET(const Instruction &inst);
        std::string translateVU_VRINIT(const Instruction &inst);
        std::string translateVU_VRXOR(const Instruction &inst);
        std::string translateVU_VMADD_Field(const Instruction &inst);
        std::string translateVU_VMINI_Field(const Instruction &inst);
        std::string translateVU_VMAX_Field(const Instruction &inst);
        std::string translateVU_VMADD(const Instruction &inst);
        std::string translateVU_VMADDq(const Instruction &inst);
        std::string translateVU_VMADDi(const Instruction &inst);
        std::string translateVU_VMAX(const Instruction &inst);
        std::string translateVU_VMAXi(const Instruction &inst);
        std::string translateVU_VADDA(const Instruction &inst);
        std::string translateVU_VADDAq(const Instruction &inst);
        std::string translateVU_VADDAi(const Instruction &inst);
        std::string translateVU_VSUBA(const Instruction &inst);
        std::string translateVU_VSUBAq(const Instruction &inst);
        std::string translateVU_VSUBAi(const Instruction &inst);
        std::string translateVU_VMADDA(const Instruction &inst);
        std::string translateVU_VMADDAq(const Instruction &inst);
        std::string translateVU_VMADDAi(const Instruction &inst);
        std::string translateVU_VMSUBA(const Instruction &inst);
        std::string translateVU_VMSUBAq(const Instruction &inst);
        std::string translateVU_VMSUBAi(const Instruction &inst);
        std::string translateVU_VMULA(const Instruction &inst);
        std::string translateVU_VMULAq(const Instruction &inst);
        std::string translateVU_VMULAi(const Instruction &inst);
        std::string translateVU_VOPMULA(const Instruction &inst);
        std::string translateVU_VOPMSUB(const Instruction &inst);
        std::string translateVU_VMINI(const Instruction &inst);
        std::string translateVU_VMINIi(const Instruction &inst);
        std::string translateVU_VMSUB(const Instruction &inst);
        std::string translateVU_VMSUBq(const Instruction &inst);
        std::string translateVU_VMSUBi(const Instruction &inst);
        std::string translateVU_VMULq(const Instruction &inst);
        std::string translateVU_VMULi(const Instruction &inst);
        std::string translateVU_VADDq(const Instruction &inst);
        std::string translateVU_VADDi(const Instruction &inst);
        std::string translateVU_VSUBq(const Instruction &inst);
        std::string translateVU_VSUBi(const Instruction &inst);
        std::string translateVU_VITOF(const Instruction &inst, int shift);
        std::string translateVU_VFTOI(const Instruction &inst, int shift);
        std::string translateVU_VLQI(const Instruction &inst);
        std::string translateVU_VSQI(const Instruction &inst);
        std::string translateVU_VLQD(const Instruction &inst);
        std::string translateVU_VSQD(const Instruction &inst);

        // Jump Table Generation
        std::string generateJumpTableSwitch(const Instruction &inst, uint32_t tableAddress,
                                            const std::vector<JumpTableEntry> &entries);

        const Symbol *findSymbolByAddress(uint32_t address) const;
        std::string getFunctionName(uint32_t address) const;
        std::string sanitizeFunctionName(const std::string& name) const;
    };

}

#endif // PS2RECOMP_CODE_GENERATOR_H

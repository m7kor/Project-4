#include "ps2recomp/Emitters/function_table_emitter.h"
#include "ps2recomp/code_generator.h"
#include "ps2recomp/ps2_recompiler.h"
#include "ps2recomp/recompiler_reporter.h"
#include "ps2recomp/types.h"

#include <algorithm>
#include <cstdint>
#include <sstream>
#include <stdexcept>
#include <unordered_set>
#include <utility>
#include <vector>

namespace ps2recomp
{
    FunctionTableEmitter::FunctionTableEmitter(CodeGenerator &codeGenerator)
        : m_codeGenerator(codeGenerator)
    {
    }

    std::string FunctionTableEmitter::emit(const std::vector<Function> &functions, const std::map<uint32_t, std::string> &stubs)
    {
        if (m_codeGenerator.hasRelocatableCodeRange())
            throw std::logic_error("Relocatable bodies require module-bound registration adapters");
        (void)stubs;

        CodeGenerator &cg = m_codeGenerator;
        std::vector<std::pair<uint32_t, std::string>> entries;
        std::unordered_set<uint32_t> registeredAddresses;

        auto addEntry = [&](uint32_t address, const std::string &name)
        {
            if (name.empty())
            {
                return;
            }
            if ((address & 3u) != 0u)
            {
                std::ostringstream oss;
                oss << "Unaligned function table entry for " << name << " at 0x" << std::hex << address;

                if (cg.m_reporter)
                {
                    cg.m_reporter->errorAt("function-table", name, address, oss.str());
                }

                throw std::runtime_error(oss.str());
            }
            if (!registeredAddresses.insert(address).second)
            {
                return;
            }
            entries.emplace_back(address, name);
        };

        std::vector<std::pair<uint32_t, std::string>> normalFunctions;
        std::vector<std::pair<uint32_t, std::string>> stubFunctions;
        std::vector<std::pair<uint32_t, std::string>> systemCallFunctions;
        std::vector<std::pair<uint32_t, std::string>> libraryFunctions;

        for (const auto &function : functions)
        {
            if (!function.isRecompiled && !function.isStub && !function.isSkipped)
                continue;

            std::string generatedName = cg.getFunctionName(function.start);

            if (function.isSkipped)
            {
                libraryFunctions.emplace_back(function.start, generatedName);
            }
            else if (function.isStub)
            {
                const auto target = PS2Recompiler::resolveStubTarget(function.name);
                if (target == StubTarget::Syscall)
                {
                    systemCallFunctions.emplace_back(function.start, generatedName);
                }
                else
                {
                    stubFunctions.emplace_back(function.start, generatedName);
                }
            }
            else
            {
                normalFunctions.emplace_back(function.start, generatedName);
            }
        }

        if (cg.m_bootstrapInfo.valid)
        {
            std::string entryTarget = cg.m_bootstrapInfo.entryName;
            if (entryTarget.empty())
            {
                entryTarget = cg.getFunctionName(cg.m_bootstrapInfo.entry);
            }
            if (entryTarget.empty())
            {
                throw std::runtime_error("No entry function name available for registration.");
            }
            addEntry(cg.m_bootstrapInfo.entry, entryTarget);
        }

        for (const auto &[address, name] : normalFunctions)
        {
            addEntry(address, name);
        }

        for (const auto &[ownerStart, targets] : cg.m_resumeEntryTargetsByOwner)
        {
            const std::string ownerName = cg.getFunctionName(ownerStart);
            if (ownerName.empty())
            {
                continue;
            }

            for (uint32_t target : targets)
            {
                addEntry(target, ownerName);
            }
        }

        for (const auto &[address, name] : stubFunctions)
        {
            addEntry(address, name);
        }
        for (const auto &[address, name] : systemCallFunctions)
        {
            addEntry(address, name);
        }
        for (const auto &[address, name] : libraryFunctions)
        {
            addEntry(address, name);
        }

        std::sort(entries.begin(), entries.end(), [](const auto &a, const auto &b)
                  { return a.first < b.first; });

        uint32_t tableBase = 0u;
        uint32_t tableEnd = 0u;
        uint32_t slotCount = 0u;
        uint32_t lastDenseEntry = 0u;
        // Declared out here, not inside the `if`: the emitter below reads it to
        // decide whether to emit the sparse tables at all, and a declaration
        // scoped to that block is invisible there.
        std::vector<std::pair<uint32_t, std::string>> sparseEntries;
        if (!entries.empty())
        {
            // LODESTONE PATCH 18: the dense table is indexed directly by address,
            // so its size is the span between the lowest and highest entry. RE4
            // installs code at 0x80076000, and one entry at that address would
            // inflate the table from 4 MB to 268 MB — 33,498,688 pointers, almost
            // all of them null.
            //
            // So the bounds come from the first CLUSTER, not the whole range. A
            // gap larger than kMaxDenseGap starts a new cluster; every entry past
            // the first such gap becomes a sorted sparse list that the runtime
            // binary-searches. With no runtime_code regions there is no such gap
            // and the emitted table is identical to what it was before.
            constexpr uint32_t kMaxDenseGap = 0x10000u;

            uint32_t lastDense = entries.front().first;
            for (const auto &entry : entries)
            {
                if (entry.first - lastDense > kMaxDenseGap)
                {
                    break;
                }
                lastDense = entry.first;
            }

            for (const auto &entry : entries)
            {
                if (entry.first > lastDense)
                {
                    sparseEntries.push_back(entry);
                }
            }

            tableBase = entries.front().first & ~3u;
            tableEnd = (lastDense + 4u + 3u) & ~3u;
            slotCount = (tableEnd - tableBase) >> 2;
            lastDenseEntry = lastDense;
        }

        std::stringstream ss;
        ss << "#include \"ps2_runtime.h\"\n";
        ss << "#include <ps2_recompiled_functions.h>\n";
        ss << "#include \"ps2_stubs.h\"\n";
        ss << "#include <ps2_recompiled_stubs.h>\n";
        ss << "#include \"ps2_syscalls.h\"\n\n";

        ss << "extern const uint32_t g_ps2RecompiledFunctionTableBase = 0x" << std::hex << tableBase << "u;\n";
        ss << "extern const uint32_t g_ps2RecompiledFunctionTableEnd = 0x" << std::hex << tableEnd << "u;\n";
        ss << "extern const uint32_t g_ps2RecompiledFunctionTableSlotCount = " << std::dec << slotCount << "u;\n";
        ss << "PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionTable[" << std::dec << (slotCount == 0u ? 1u : slotCount) << "u] = {};\n\n";

        ss << "namespace {\n";
        ss << "struct GeneratedFunctionTableInitializer {\n";
        ss << "    GeneratedFunctionTableInitializer() {\n";
        for (const auto &[address, name] : entries)
        {
            if (address > lastDenseEntry)
            {
                continue;
            }
            const uint32_t slot = (address - tableBase) >> 2;
            ss << "        g_ps2RecompiledFunctionTable[" << std::dec << slot << "] = " << name
               << "; // 0x" << std::hex << address << std::dec << "\n";
        }
        ss << "    }\n";
        ss << "};\n";
        ss << "static const GeneratedFunctionTableInitializer g_generatedFunctionTableInitializer;\n";
        ss << "}\n";

        if (sparseEntries.empty())
        {
            ss << "\nextern const uint32_t g_ps2RecompiledFunctionSparseCount = 0u;\n";
            // Keep the same link contract when there are no sparse entries.
            // The runtime references the arrays even though count is zero.
            ss << "extern const uint32_t g_ps2RecompiledFunctionSparseAddress[1u] = {0u};\n";
            ss << "extern const PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionSparseTarget[1u] = {nullptr};\n";
        }
        else
        {
            ss << "\n// LODESTONE PATCH 18: entries outside the dense cluster above.\n";
            ss << "// Sorted by address so the runtime can binary-search them.\n";
            ss << "extern const uint32_t g_ps2RecompiledFunctionSparseCount = " << std::dec
               << sparseEntries.size() << "u;\n";
            ss << "extern const uint32_t g_ps2RecompiledFunctionSparseAddress[" << std::dec
               << sparseEntries.size() << "u] = {";
            for (std::size_t i = 0; i < sparseEntries.size(); i++)
            {
                ss << (i == 0 ? "" : ", ") << "0x" << std::hex << sparseEntries[i].first << "u";
            }
            ss << "};\n";
            ss << "extern const PS2Runtime::RecompiledFunction g_ps2RecompiledFunctionSparseTarget["
               << std::dec << sparseEntries.size() << "u] = {";
            for (std::size_t i = 0; i < sparseEntries.size(); i++)
            {
                ss << (i == 0 ? "" : ", ") << sparseEntries[i].second;
            }
            ss << "};\n";
        }

        return ss.str();
    }
}

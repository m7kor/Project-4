// VU1 microprogram code generator.
//
// Reads microcode images captured with PS2X_VU1_CAPTURE (vu1_<fnv1a64>.bin,
// 16 KB each), decodes them with the interpreter itself
// (VU1Interpreter::exportDecodedPairs, including its static analysis) and
// writes vu1_compiled_programs.inc: every instruction pair becomes a
// constexpr DecodedInstructionPair passed to the interpreter's own inline
// step (VU1CompiledPrograms::step<K>), so the compiler folds the decode while
// the semantics stay those of the interpreter. Identical pairs share one
// instantiation. The runtime picks a table by image hash.
//
//   ps2x_vu1_codegen <capture dir> <output .inc>
#include "runtime/ps2_vu1.h"

#include <algorithm>
#include <cstdint>
#include <charconv>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
    using Pair = VU1Interpreter::DecodedInstructionPair;
    using Usage = VU1Interpreter::InstructionUsage;

    std::string b(bool value) { return value ? "true" : "false"; }

    std::string usage(const Usage &u)
    {
        std::ostringstream o;
        o << "{.vfRead = {{{" << unsigned(u.vfRead[0].reg) << ", " << unsigned(u.vfRead[0].lanes) << "}, {"
          << unsigned(u.vfRead[1].reg) << ", " << unsigned(u.vfRead[1].lanes) << "}}}"
          << ", .vfWrite = {" << unsigned(u.vfWrite.reg) << ", " << unsigned(u.vfWrite.lanes) << "}"
          << ", .vfReadCount = " << unsigned(u.vfReadCount) << ", .viRead = " << u.viRead
          << ", .viWrite = " << u.viWrite << ", .accRead = " << unsigned(u.accRead)
          << ", .accWrite = " << unsigned(u.accWrite) << ", .latency = " << unsigned(u.latency)
          << ", .vfLatency = " << unsigned(u.vfLatency) << ", .viLatency = " << unsigned(u.viLatency)
          << ", .pipeline = static_cast<VU1Interpreter::Pipeline>(" << unsigned(u.pipeline) << ")"
          << ", .waitQ = " << b(u.waitQ) << ", .waitP = " << b(u.waitP) << ", .readsClip = " << b(u.readsClip)
          << ", .writesClip = " << b(u.writesClip) << ", .delaysNextBranchRead = " << b(u.delaysNextBranchRead)
          << ", .reserved = " << b(u.reserved) << "}";
        return o.str();
    }

    std::string literal(const Pair &p)
    {
        std::ostringstream o;
        char words[64];
        std::snprintf(words, sizeof(words), "{.lower = 0x%08Xu, .upper = 0x%08Xu", p.lower, p.upper);
        o << words << ", .lowerUsage = " << usage(p.lowerUsage) << ", .upperUsage = " << usage(p.upperUsage)
          << ", .iBit = " << b(p.iBit) << ", .eBit = " << b(p.eBit) << ", .mBit = " << b(p.mBit)
          << ", .dBit = " << b(p.dBit) << ", .tBit = " << b(p.tBit)
          << ", .upperVfShadowReg = " << unsigned(p.upperVfShadowReg)
          << ", .suppressedLowerVf = " << unsigned(p.suppressedLowerVf)
          << ", .upperVfDirect = " << b(p.upperVfDirect) << ", .lowerVfDirect = " << b(p.lowerVfDirect)
          << ", .accDirect = " << b(p.accDirect) << ", .viDirect = " << b(p.viDirect)
          << ", .storeDirect = " << b(p.storeDirect) << ", .flagsLive = " << b(p.flagsLive)
          << ", .flagsDirect = " << b(p.flagsDirect) << ", .productSum = " << b(p.productSum) << "}";
        return o.str();
    }
}

int generate(int argc, char **argv)
{
    if (argc != 3 && argc != 5)
    {
        std::cerr << "usage: ps2x_vu1_codegen <capture dir> <output .inc> [--block-size 2|4|8]\n";
        return 2;
    }
    uint32_t blockSize = 0; // Normal regeneration is byte-identical to the per-pair output.
    if (argc == 5)
    {
        const std::string input = argv[4];
        const auto parsed = std::from_chars(input.data(), input.data() + input.size(), blockSize);
        if (std::string(argv[3]) != "--block-size" || parsed.ec != std::errc{} ||
            parsed.ptr != input.data() + input.size() || (blockSize != 2 && blockSize != 4 && blockSize != 8))
            throw std::runtime_error("block size must be 2, 4 or 8");
    }
    std::vector<std::filesystem::path> images;
    for (const auto &entry : std::filesystem::directory_iterator(argv[1]))
    {
        const std::string name = entry.path().filename().string();
        if (entry.is_regular_file() && name.rfind("vu1_", 0) == 0 && entry.path().extension() == ".bin")
        {
            if (entry.file_size() != 0x4000u)
                throw std::runtime_error("invalid VU1 image size: " + entry.path().string());
            images.push_back(entry.path());
        }
    }
    std::sort(images.begin(), images.end());
    if (images.empty())
        throw std::runtime_error("no VU1 microcode images; existing output left untouched");

    VU1Interpreter vu1(VU1Interpreter::Unit::VU1);
    std::map<std::string, size_t> constants; // literal -> constant index
    std::vector<std::string> constantOrder;
    struct Table { std::string hash; std::vector<size_t> entries; };
    std::vector<Table> tables;
    for (const auto &path : images)
    {
        std::vector<uint8_t> code(0x4000u);
        if (!std::ifstream(path, std::ios::binary).read(reinterpret_cast<char *>(code.data()), code.size()))
            throw std::runtime_error("cannot read VU1 image: " + path.string());
        std::vector<Pair> pairs;
        vu1.exportDecodedPairs(code.data(), static_cast<uint32_t>(code.size()), pairs);
        Table table;
        // Dispatch identity belongs to the bytes, not the filename. A renamed
        // capture must never select compiled instructions for another image.
        uint64_t hash = 0xCBF29CE484222325ull;
        for (uint8_t byte : code)
            hash = (hash ^ byte) * 0x100000001B3ull;
        char hashText[17];
        std::snprintf(hashText, sizeof(hashText), "%016llx", static_cast<unsigned long long>(hash));
        table.hash = hashText;
        if (std::any_of(tables.begin(), tables.end(), [&](const Table &existing) { return existing.hash == table.hash; }))
            continue;
        for (const Pair &pair : pairs)
        {
            const std::string text = literal(pair);
            auto found = constants.find(text);
            if (found == constants.end())
            {
                found = constants.emplace(text, constantOrder.size()).first;
                constantOrder.push_back(text);
            }
            table.entries.push_back(found->second);
        }
        tables.push_back(std::move(table));
    }

    std::ofstream out(argv[2]);
    if (!out)
        throw std::runtime_error("cannot open output: " + std::string(argv[2]));
    out << "// Generated by ps2x_vu1_codegen from " << images.size()
        << " captured VU1 microcode images. Do not edit.\n";
    if (blockSize)
        out << "static const bool g_vu1TraceBlocks = [] { const char *v = std::getenv(\"PS2X_VU1_TRACE_BLOCKS\"); return v && *v == '1'; }();\n";
    out << "struct VU1CompiledPrograms\n{\n"
        << "    using P = VU1Interpreter::DecodedInstructionPair;\n"
        << "    template <const P &K>\n"
        << "    static " << (blockSize ? "PS2X_VU1_STEP_INLINE " : "")
        << "int step(VU1Interpreter &vu, uint8_t *data, uint32_t dataSize, GS &gs, PS2Memory *memory,\n"
        << "                    uint32_t codeSize, uint64_t budgetEnd, bool &programEnded)\n    {\n"
        << "        vu.m_pairFlagsDirect = K.flagsDirect;\n"
        << "        vu.m_pairProductSum = K.productSum;\n"
        << "        vu.m_pairStoreDirect = K.storeDirect;\n"
        << "        vu.m_pairFlagsLive = K.flagsLive;\n"
        << "        return vu.stepPairBody(K, data, dataSize, gs, memory, codeSize, budgetEnd, programEnded);\n"
        << "    }\n";
    if (blockSize)
        out
        // Keep the exact per-pair issue path. Only the dispatch of sequential
        // pairs is combined; branches, cycle budgets and stop reasons exit.
        << "    template <const P &K, const P &... Rest>\n"
        << "    static PS2X_VU1_STEP_INLINE int blockBody(VU1Interpreter &vu, uint8_t *data, uint32_t dataSize, GS &gs, PS2Memory *memory,\n"
        << "                     uint32_t codeSize, uint64_t budgetEnd, bool &programEnded)\n    {\n"
        << "        if (g_vu1TraceBlocks) ++g_vu1CompiledBlockSteps;\n"
        << "        [[maybe_unused]] const uint32_t sequentialPc = vu.m_state.pc + 8u;\n"
        << "        const int leave = step<K>(vu, data, dataSize, gs, memory, codeSize, budgetEnd, programEnded);\n"
        << "        if (leave) return leave;\n"
        << "        if constexpr (sizeof...(Rest) != 0)\n        {\n"
        << "            if (vu.m_state.pc != sequentialPc || vu.m_cycle >= budgetEnd || vu.m_stopRequested ||\n"
        << "                vu.m_state.pc + 8u > codeSize) return 0;\n"
        << "            if (vu.m_cycle >= vu.m_nextCommitCycle || vu1ScanAll()) vu.commitReadyPipelines();\n"
        << "            return blockBody<Rest...>(vu, data, dataSize, gs, memory, codeSize, budgetEnd, programEnded);\n"
        << "        }\n"
        << "        return 0;\n"
        << "    }\n"
        << "    template <const P &... Pairs>\n"
        << "    static int block(VU1Interpreter &vu, uint8_t *data, uint32_t dataSize, GS &gs, PS2Memory *memory,\n"
        << "                     uint32_t codeSize, uint64_t budgetEnd, bool &programEnded)\n    {\n"
        << "        if (g_vu1TraceBlocks) ++g_vu1CompiledBlockEntries;\n"
        << "        return blockBody<Pairs...>(vu, data, dataSize, gs, memory, codeSize, budgetEnd, programEnded);\n"
        << "    }\n";
    for (size_t i = 0; i < constantOrder.size(); ++i)
        out << "    static constexpr P k" << i << " = " << constantOrder[i] << ";\n";
    for (const Table &table : tables)
    {
        out << "    static constexpr VU1Interpreter::CompiledPairFn t_" << table.hash << "[" << table.entries.size()
            << "] = {";
        for (size_t i = 0; i < table.entries.size(); ++i)
            out << (i % 8 ? " " : "\n        ") << "&step<k" << table.entries[i] << ">,";
        out << "\n    };\n";
        if (!blockSize) continue;
        out << "    static constexpr VU1Interpreter::CompiledPairFn b_" << table.hash << "[" << table.entries.size()
            << "] = {";
        for (size_t i = 0; i < table.entries.size(); ++i)
        {
            // Every PC has an entry, including resume into a block's middle.
            const size_t end = std::min(table.entries.size(), (i / blockSize + 1u) * blockSize);
            out << (i % 4 ? " " : "\n        ") << "&block<";
            for (size_t j = i; j < end; ++j)
                out << (j == i ? "" : ", ") << "k" << table.entries[j];
            out << ">,";
        }
        out << "\n    };\n";
    }
    out << "};\n\nstatic const VU1Interpreter::CompiledPairFn *vu1FindCompiledProgram(uint64_t hash)\n{\n";
    if (blockSize)
        out << "    // Experimental opt-in; the per-pair table remains the default.\n"
        << "    static const bool blocks = [] { const char *v = std::getenv(\"PS2X_VU1_BLOCKS\"); return v && *v == '1'; }();\n"
        ;
    out << "    switch (hash)\n    {\n";
    for (const Table &table : tables)
    {
        out << "    case 0x" << table.hash << "ull: return ";
        if (blockSize) out << "blocks ? VU1CompiledPrograms::b_" << table.hash << " : ";
        out << "VU1CompiledPrograms::t_" << table.hash << ";\n";
    }
    out << "    default: return nullptr;\n    }\n}\n";
    out.flush();
    if (!out)
        throw std::runtime_error("cannot write output: " + std::string(argv[2]));
    std::cout << "images=" << tables.size() << " distinct pairs=" << constantOrder.size()
              << " block_size=" << blockSize << " experimental_default=off -> " << argv[2] << "\n";
    return 0;
}

int main(int argc, char **argv)
{
    try
    {
        return generate(argc, argv);
    }
    catch (const std::exception &error)
    {
        std::cerr << error.what() << "\n";
        return 1;
    }
}

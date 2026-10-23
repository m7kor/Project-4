#include "ps2recomp/native_module_codegen.h"
#include "ps2recomp/code_generator.h"
#include "ps2recomp/r5900_decoder.h"
#include "ps2recomp/types.h"
#include <algorithm>
#include <iomanip>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>

namespace ps2recomp {
namespace {
uint32_t wordAt(const std::vector<uint8_t>& bytes, uint32_t at)
{
    return uint32_t(bytes[at]) | uint32_t(bytes[at+1]) << 8 |
           uint32_t(bytes[at+2]) << 16 | uint32_t(bytes[at+3]) << 24;
}
bool validIdentifier(const std::string& value)
{
    if (value.empty() || value.size() > 80) return false;
    auto letter = [](char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); };
    if (!letter(value[0])) return false;
    return std::all_of(value.begin(), value.end(), [&](char c) {
        return letter(c) || (c >= '0' && c <= '9') || c == '_';
    });
}
}
std::string generateNativeModule(const NativeModuleCodegenInput& input)
{
    if (!validIdentifier(input.identifier) || input.identity.empty() || input.identity.size() > 512
        || std::any_of(input.identity.begin(), input.identity.end(), [](unsigned char c) { return c < 32 || c > 126; }))
        throw std::invalid_argument("Invalid native module identifier or identity");
    if (input.image.size() < 4 || input.image.size() > 32u*1024u*1024u || input.bodies.empty())
        throw std::invalid_argument("Invalid native module image or empty body list");
    auto bodies = input.bodies;
    std::sort(bodies.begin(), bodies.end(), [](const auto& a, const auto& b) { return a.start < b.start; });
    uint32_t previousEnd = 0;
    for (const auto& body : bodies)
    {
        if ((body.start & 3u) || (body.end & 3u) || body.start >= body.end
            || body.end > input.image.size() || body.start < previousEnd)
            throw std::invalid_argument("Invalid or overlapping native body range");
        previousEnd = body.end;
    }
    for (const auto& [at, type] : input.instructionRelocations)
    {
        if ((at & 3u) || at > input.image.size()-4 || (type != 4 && type != 5 && type != 6)
            || std::none_of(bodies.begin(), bodies.end(), [&](const auto& body) { return at >= body.start && at < body.end; }))
            throw std::invalid_argument("Instruction relocation outside compiled bodies or unsupported type");
    }
    CodeGenerator gen({}, {});
    gen.setRelocatableCodeRange(0, uint32_t(input.image.size()) & ~3u);
    gen.setRuntimeInstructionRelocations(input.instructionRelocations);
    std::unordered_map<uint32_t, std::string> names;
    for (const auto& body : bodies)
        names.emplace(body.start, input.identifier + "_body_" + std::to_string(body.start));
    gen.setRenamedFunctions(names);
    R5900Decoder decoder;
    std::ostringstream output, entries, codeWords;
    output << "#include <stdexcept>\n#include \"ps2_runtime.h\"\n#include \"ps2_runtime_macros.h\"\n"
           << "#include \"runtime/ps2_vu_control.h\"\n"
           << "#include \"runtime/native_module_registry.h\"\n";
    for (const auto& body : bodies)
    {
        Function function{};
        function.name = names.at(body.start);
        function.start = body.start;
        function.end = body.end;
        std::vector<Instruction> instructions;
        for (uint32_t at = body.start; at < body.end; at += 4)
        {
            auto inst = decoder.decodeInstruction(at, wordAt(input.image, at), false);
            if (inst.hasDelaySlot && at + 4 >= body.end)
                throw std::invalid_argument("Native body omits a branch delay slot");
            instructions.push_back(inst);
        }
        auto analysis = gen.collectInternalBranchTargets(function, instructions);
        std::set<uint32_t> resume(analysis.resumeEntryPoints.begin(), analysis.resumeEntryPoints.end());
        resume.insert(body.entries.begin(), body.entries.end());
        for (auto at : resume)
            if ((at & 3u) || at < body.start || at >= body.end)
                throw std::invalid_argument("Native resume entry outside owner body");
        gen.setResumeEntryTargets({{body.start, {resume.begin(), resume.end()}}});
        auto source = gen.generateFunction(function, instructions, false);
        if (source.find("throw std::runtime_error(") != std::string::npos)
            throw std::invalid_argument("Native body contains an unsupported instruction");
        output << source;
        resume.insert(body.start);
        for (uint32_t at : resume)
            entries << "        {" << at << "u, " << body.start << "u, " << body.end << "u, " << function.name << "},\n";
        for (uint32_t at = body.start; at < body.end; at += 4)
        {
            auto reloc = input.instructionRelocations.find(at);
            const uint32_t bits = reloc == input.instructionRelocations.end() ? 0u
                : reloc->second == 4 ? 0x03FFFFFFu : 0xFFFFu;
            codeWords << "        {" << at << "u, " << wordAt(input.image, at) << "u, " << bits << "u},\n";
        }
    }
    output << "const ps2x::NativeModuleDescriptor& " << input.identifier << "_descriptor() {\n"
           << "    static const ps2x::NativeModuleDescriptor descriptor = {\n        " << std::quoted(input.identity)
           << ", " << input.image.size() << "u, {\n" << codeWords.str() << "    }, {\n" << entries.str()
           << "    }};\n    return descriptor;\n}\n";
    return output.str();
}
}

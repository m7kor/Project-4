#include "ps2recomp/code_generator.h"
#include "ps2recomp/r5900_decoder.h"
#include "ps2recomp/types.h"
#include <fstream>
#include <iostream>
#include <string>

int main(int argc, char **argv)
{
    if (argc != 2 && argc != 3) return 2;
    const bool relativePc = argc == 3 && std::string(argv[2]) == "--relative-pc";
    if (argc == 3 && !relativePc) return 2;
    ps2recomp::CodeGenerator gen({}, {});
    if (relativePc)
        gen.setRelocatableCodeRange(0x1000, 0x100);
    gen.setRenamedFunctions({{0x1000, "native_relocation_operand_probe"}});
    gen.setRuntimeInstructionRelocations({{0x1000, 5}, {0x1004, 6}, {0x1008, 6},
                                         {0x100C, 6}, {0x1010, 6}, {0x1014, 6}, {0x1018, 6}});
    ps2recomp::Function function{};
    function.name = "native_relocation_operand_probe";
    function.start = 0x1000;
    function.end = 0x101C;
    // LUI t0; LW v0; SW v0; ADDIU a0; ORI a1; SLTI a2; SLTIU a3.
    const uint32_t words[] = {0x3C080004, 0x8D02AF30, 0xAD02AF34, 0x2504AF38,
                              0x34050000, 0x28060000, 0x2C070000};
    ps2recomp::R5900Decoder decoder;
    std::vector<ps2recomp::Instruction> instructions;
    for (unsigned i = 0; i < 7; ++i)
        instructions.push_back(decoder.decodeInstruction(0x1000 + i * 4, words[i], false));
    std::ofstream output(argv[1]);
    if (!output) return 3;
    output << "#include <stdexcept>\n#include \"ps2_runtime_macros.h\"\n#include \"ps2_runtime.h\"\n";
    output << gen.generateFunction(function, instructions, false);
    if (relativePc)
    {
        gen.setRuntimeInstructionRelocations({});
        gen.setRenamedFunctions({{0x1000, "native_relative_flow_probe"}});
        instructions.clear();
        const uint32_t callWords[] = {0x03E0C82D, 0x24020005, 0x0C000409, 0x24420007,
                                      0x24420003, 0x0320F82D, 0x03E00008, 0x24420002,
                                      0, 0x2442000B, 0x03E00008, 0x2442000D};
        for (unsigned i = 0; i < 12; ++i)
            instructions.push_back(decoder.decodeInstruction(0x1000 + i * 4, callWords[i], false));
        function.name = "native_relative_flow_probe";
        function.end = 0x1030;
        output << gen.generateFunction(function, instructions, false);
        gen.setRenamedFunctions({{0x1000, "native_relative_indirect_flow_probe"}});
        instructions.clear();
        gen.setResumeEntryTargets({{0x1000, {0x1024}}});
        for (unsigned i = 0; i < 12; ++i)
        {
            // JALR ra,ra must capture its target before replacing ra; t9 holds
            // the host's sentinel return address, seeded by the harness.
            const uint32_t word = i == 0 ? 0u : i == 2 ? 0x03E0F809u : callWords[i];
            instructions.push_back(decoder.decodeInstruction(0x1000 + i * 4, word, false));
        }
        function.name = "native_relative_indirect_flow_probe";
        output << gen.generateFunction(function, instructions, false);
        gen.setResumeEntryTargets({});
        gen.setRenamedFunctions({{0x1000, "native_relative_branch_probe"}});
        instructions.clear();
        const uint32_t branchWords[] = {0x24080001, 0x24020005, 0x11080002, 0x24420007,
                                        0x24420064, 0x55080002, 0x244203E8, 0x24420003,
                                        0x03E00008, 0x24420002};
        for (unsigned i = 0; i < 10; ++i)
            instructions.push_back(decoder.decodeInstruction(0x1000 + i * 4, branchWords[i], false));
        function.name = "native_relative_branch_probe";
        function.end = 0x1028;
        output << gen.generateFunction(function, instructions, false);
    }
    if (!output) return 4;
    std::cout << "Generated seven native instructions with runtime relocated operands\n";
    return 0;
}

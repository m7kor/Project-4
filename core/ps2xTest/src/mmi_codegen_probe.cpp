#include "ps2recomp/code_generator.h"
#include "ps2recomp/instructions.h"
#include "ps2recomp/types.h"
#include <fstream>

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    std::ofstream out(argv[1]);
    if (!out) return 1;
    out << "#include \"ps2_runtime_macros.h\"\n"
           "extern \"C\" void ps2MmiPermutationProbe(R5900Context *ctx, unsigned op, unsigned mode) {\n"
           "switch (mode * 6 + op) {\n";
    ps2recomp::CodeGenerator gen({}, {});
    const uint8_t functions[] = {ps2recomp::MMI_MMI2, ps2recomp::MMI_MMI2, ps2recomp::MMI_MMI2,
        ps2recomp::MMI_MMI2, ps2recomp::MMI_MMI3, ps2recomp::MMI_MMI3};
    const uint8_t subs[] = {ps2recomp::MMI2_PEXEH, ps2recomp::MMI2_PREVH, ps2recomp::MMI2_PEXEW,
        ps2recomp::MMI2_PROT3W, ps2recomp::MMI3_PEXCH, ps2recomp::MMI3_PEXCW};
    for (unsigned mode = 0; mode < 4; ++mode)
        for (unsigned op = 0; op < 6; ++op) {
            ps2recomp::Instruction inst{};
            inst.opcode = ps2recomp::OPCODE_MMI;
            inst.isMMI = true;
            inst.function = functions[op];
            inst.sa = subs[op];
            inst.rs = 4;
            inst.rt = mode == 3 ? 0 : 5;
            inst.rd = mode == 2 ? 0 : mode == 1 ? 5 : 3;
            out << "case " << mode * 6 + op << ": { " << gen.translateInstruction(inst) << " break; }\n";
        }
    out << "}\n}\n";
    return out ? 0 : 1;
}

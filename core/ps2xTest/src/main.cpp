#include "MiniTest.h"
#include <cstdlib>
#include <iostream>

void register_code_generator_tests();
void register_mmi_permutation_tests();
void register_r5900_decoder_tests();
void register_elf_analyzer_tests();
void register_pad_input_tests();
void register_ps2_runtime_io_tests();
void register_ps2_runtime_kernel_tests();
void register_ps2_runtime_interrupt_tests();
void register_ps2_memory_tests();
void register_ps2_ipu_tests();
void register_ps2_vu1_tests();
void register_ps2_vif_work_queue_tests();
void register_ps2_vu_tests();
void register_ps2_gs_tests();
void register_ps2_iop_tests();
void register_ps2_sif_rpc_tests();
void register_ps2_sif_dma_tests();
void register_ps2_recompiler_tests();
void register_ps2_runtime_expansion_tests();
void registerNativeRelocationRuntimeTests();
void registerNativeModuleCodegenTests();
void reset_ps2_test_function_table();

int main()
{
    // The VU tests check FMAC flags straight from the register state, which
    // the runtime only computes exactly when a microprogram reads them.
#if defined(_WIN32)
    _putenv_s("PS2X_VU1_EXACT_FLAGS", "1");
    _putenv_s("PS2X_VU1_DIRECT", "0"); // tests observe VF/ACC mid-pipeline
#else
    setenv("PS2X_VU1_EXACT_FLAGS", "1", 1);
    setenv("PS2X_VU1_DIRECT", "0", 1);
#endif
    MiniTest::BeforeEach(reset_ps2_test_function_table);

    register_code_generator_tests();
    register_mmi_permutation_tests();
    register_r5900_decoder_tests();
    register_elf_analyzer_tests();
    register_pad_input_tests();
    register_ps2_runtime_io_tests();
    register_ps2_runtime_kernel_tests();
    register_ps2_runtime_interrupt_tests();
    register_ps2_memory_tests();
    register_ps2_ipu_tests();
    register_ps2_vu1_tests();
    register_ps2_vif_work_queue_tests();
    register_ps2_vu_tests();
    register_ps2_gs_tests();
    register_ps2_iop_tests();
    register_ps2_sif_rpc_tests();
    register_ps2_sif_dma_tests();
    register_ps2_recompiler_tests();
    register_ps2_runtime_expansion_tests();
    registerNativeRelocationRuntimeTests();
    registerNativeModuleCodegenTests();
    int res = MiniTest::Run();
    std::cout.flush();
    std::cerr.flush();
    std::_Exit(res);
}

cmake_minimum_required(VERSION 3.21)

project(ps2xTest LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(CTest)
if(BUILD_TESTING)
    add_subdirectory(gs_cache)
endif()

# Static library with test logic (no main), used by ps2xStudio
add_library(ps2_test_function_table OBJECT
    src/test_function_table.cpp
)

target_include_directories(ps2_test_function_table PRIVATE
    ${CMAKE_SOURCE_DIR}/ps2xRuntime/include
    ${CMAKE_SOURCE_DIR}/ps2xIOP/include
)

add_library(ps2_test_lib STATIC
    src/code_generator_tests.cpp
    src/mmi_permutation_tests.cpp
    src/r5900_decoder_tests.cpp
    src/elf_analyzer_tests.cpp
    src/pad_input_tests.cpp
    src/ps2_runtime_io_tests.cpp
    src/ps2_runtime_kernel_tests.cpp
    src/ps2_runtime_interrupt_tests.cpp
    src/ps2_memory_tests.cpp
    src/ps2_ipu_tests.cpp
    src/ps2_vu1_tests.cpp
    src/ps2_vif_work_queue_tests.cpp
    src/ps2_vu_tests.cpp
    src/ps2_gs_tests.cpp
    src/ps2_iop_tests.cpp
    src/ps2_sif_rpc_tests.cpp
    src/ps2_sif_dma_tests.cpp
    src/ps2_recompiler_tests.cpp
    src/ps2_runtime_expansion_tests.cpp
    src/native_relocation_runtime_tests.cpp
    src/native_module_codegen_tests.cpp
)

target_include_directories(ps2_test_lib PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_SOURCE_DIR}/ps2xRecomp/include
    ${CMAKE_SOURCE_DIR}/ps2xAnalyzer/include
    ${CMAKE_SOURCE_DIR}/ps2xRuntime/include
    ${CMAKE_SOURCE_DIR}/ps2xRuntime/src/lib
)

target_link_libraries(ps2_test_lib PRIVATE
    parallel-gs
    ps2_recomp_lib
    ps2_analyzer_lib
    ps2_runtime
    ps2_iop
)

if(UNIX AND NOT APPLE)
    target_link_libraries(ps2_test_lib PRIVATE ${CMAKE_DL_LIBS})
endif()

add_executable(ps2x_tests
    src/main.cpp
    $<TARGET_OBJECTS:ps2_test_function_table>
)

# Generates an independent native operand probe from the production emitter.
add_executable(ps2x_relocation_codegen_probe src/relocation_codegen_probe.cpp)
target_include_directories(ps2x_relocation_codegen_probe PRIVATE
    ${CMAKE_SOURCE_DIR}/ps2xRecomp/include
    ${CMAKE_SOURCE_DIR}/ps2xRuntime/include
    ${CMAKE_SOURCE_DIR}/ps2xIOP/include)
target_link_libraries(ps2x_relocation_codegen_probe PRIVATE ps2_recomp_lib)

set(PS2_RELOCATION_CANARY_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/relocation_canary_generated.cpp")
add_custom_command(OUTPUT "${PS2_RELOCATION_CANARY_SOURCE}"
    COMMAND $<TARGET_FILE:ps2x_relocation_codegen_probe> "${PS2_RELOCATION_CANARY_SOURCE}" --relative-pc
    DEPENDS ps2x_relocation_codegen_probe
    VERBATIM)
target_sources(ps2_test_lib PRIVATE "${PS2_RELOCATION_CANARY_SOURCE}")

add_executable(ps2x_mmi_codegen_probe src/mmi_codegen_probe.cpp)
target_link_libraries(ps2x_mmi_codegen_probe PRIVATE ps2_recomp_lib)
set(PS2_MMI_CANARY_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/mmi_canary_generated.cpp")
add_custom_command(OUTPUT "${PS2_MMI_CANARY_SOURCE}"
    COMMAND $<TARGET_FILE:ps2x_mmi_codegen_probe> "${PS2_MMI_CANARY_SOURCE}"
    DEPENDS ps2x_mmi_codegen_probe VERBATIM)
target_sources(ps2_test_lib PRIVATE "${PS2_MMI_CANARY_SOURCE}")

option(PRINT_GENERATED_CODE "Print generated code in tests" OFF)
if(PRINT_GENERATED_CODE)

    target_compile_definitions(ps2x_tests PRIVATE PRINT_GENERATED_CODE)
    target_compile_definitions(ps2_test_lib PRIVATE PRINT_GENERATED_CODE)
endif()

target_include_directories(ps2x_tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_SOURCE_DIR}/ps2xRecomp/include
    ${CMAKE_SOURCE_DIR}/ps2xAnalyzer/include
    ${CMAKE_SOURCE_DIR}/ps2xRuntime/include
)

target_link_libraries(ps2x_tests PRIVATE
    ps2_test_lib
    ps2_recomp_lib
    ps2_analyzer_lib
    ps2_runtime
)

# Explicit operation benchmarks use procedural inputs and the real runtime.
add_executable(ps2x_runtime_hotpath_bench EXCLUDE_FROM_ALL
    src/runtime_hotpath_bench.cpp $<TARGET_OBJECTS:ps2_test_function_table>)
target_link_libraries(ps2x_runtime_hotpath_bench PRIVATE ps2_runtime)

# Replays VU1 MSCAL snapshots (PS2X_VU1_SNAPSHOT) for speed and equivalence.
add_executable(ps2x_vu1_bench EXCLUDE_FROM_ALL
    src/vu1_bench.cpp $<TARGET_OBJECTS:ps2_test_function_table>)
target_include_directories(ps2x_vu1_bench PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)
target_link_libraries(ps2x_vu1_bench PRIVATE ps2_runtime)
if(MSVC)
    target_link_options(ps2x_vu1_bench PRIVATE /DEBUG) # symbols for hot_thread_sampler --lines
endif()

# Generates ps2xRuntime/src/lib/vu/generated/vu1_compiled_programs.inc from
# captured VU1 microcode (PS2X_VU1_CAPTURE).
add_executable(ps2x_vu1_codegen EXCLUDE_FROM_ALL
    src/vu1_codegen.cpp $<TARGET_OBJECTS:ps2_test_function_table>)
target_include_directories(ps2x_vu1_codegen PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)
target_link_libraries(ps2x_vu1_codegen PRIVATE ps2_runtime)

# Decodes the first I picture of a local SFD movie through the IPU model
# alone; the disc archive is a command-line argument, never a fixture.
add_executable(ps2x_ipu_sfd_probe EXCLUDE_FROM_ALL
    src/ipu_sfd_probe.cpp
    ${CMAKE_SOURCE_DIR}/ps2xRuntime/src/lib/ps2_ipu.cpp)
target_include_directories(ps2x_ipu_sfd_probe PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)

# CSC operation A/B benchmark; source data is procedural, not game content.
add_executable(ps2x_ipu_csc_bench EXCLUDE_FROM_ALL
    src/ipu_csc_bench.cpp
    ${CMAKE_SOURCE_DIR}/ps2xRuntime/src/lib/ps2_ipu.cpp)
target_include_directories(ps2x_ipu_csc_bench PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)

# Real Vulkan readback comparison, including resolution/source changes.
add_executable(ps2x_gs_readback_probe EXCLUDE_FROM_ALL src/gs_readback_probe.cpp)
target_include_directories(ps2x_gs_readback_probe PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)
target_link_libraries(ps2x_gs_readback_probe PRIVATE ps2_runtime)

# Caller-supplied original fence: compare CPU parsing with real Vulkan signals.
add_executable(ps2x_gif_fence_replay EXCLUDE_FROM_ALL src/gif_fence_replay.cpp)
target_include_directories(ps2x_gif_fence_replay PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)
target_link_libraries(ps2x_gif_fence_replay PRIVATE ps2_runtime)

add_executable(ps2x_gif_path_replay EXCLUDE_FROM_ALL src/gif_path_replay.cpp)
target_include_directories(ps2x_gif_path_replay PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)
target_link_libraries(ps2x_gif_path_replay PRIVATE ps2_runtime)

# Local game-byte canaries are supplied explicitly and never shipped as test
# fixtures. Both sources are required; normal tests remain game independent.
set(PS2_NATIVE_MODULE_CANARY_SOURCE "" CACHE FILEPATH "Generated local native module canary")
set(PS2_NATIVE_MODULE_CANARY_HARNESS "" CACHE FILEPATH "Local native module canary harness")
set(PS2_NATIVE_MODULE_CANARY_INCLUDE_DIR "" CACHE PATH "Include directory for local original generated canary support")
if(PS2_NATIVE_MODULE_CANARY_SOURCE AND PS2_NATIVE_MODULE_CANARY_HARNESS)
    add_executable(ps2x_native_module_canary EXCLUDE_FROM_ALL
        "${PS2_NATIVE_MODULE_CANARY_SOURCE}" "${PS2_NATIVE_MODULE_CANARY_HARNESS}"
        $<TARGET_OBJECTS:ps2_test_function_table>)
    target_link_libraries(ps2x_native_module_canary PRIVATE ps2_runtime)
    if(PS2_NATIVE_MODULE_CANARY_INCLUDE_DIR)
        target_include_directories(ps2x_native_module_canary PRIVATE "${PS2_NATIVE_MODULE_CANARY_INCLUDE_DIR}")
    endif()
endif()

# VU/GS tests intentionally instantiate large interpreter state.
# Windows executables default to a much smaller stack than Linux, and
# sanitizer/debug instrumentation can push these test frames over 1 MiB.
if(MSVC)
    target_link_options(ps2x_tests PRIVATE "/STACK:8388608")
elseif(MINGW)
    target_link_options(ps2x_tests PRIVATE "--stack,8388608")
endif()

if(COMMAND ps2x_stage_ffmpeg_runtime_dlls)
    ps2x_stage_ffmpeg_runtime_dlls(ps2x_tests)
endif()

include("${CMAKE_SOURCE_DIR}/ps2xRuntime/cmake/ReleaseMode.cmake")

if(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
    EnableFastReleaseMode(ps2_test_lib)
    EnableFastReleaseMode(ps2x_tests)
endif()

# Procedural source-chain resource regressions; no game data or GPU required.
if(BUILD_TESTING)
    add_executable(ps2x_dma_chain_limits src/dma_chain_limits.cpp
        $<TARGET_OBJECTS:ps2_test_function_table>)
    target_include_directories(ps2x_dma_chain_limits PRIVATE ${CMAKE_SOURCE_DIR}/ps2xRuntime/include)
    target_link_libraries(ps2x_dma_chain_limits PRIVATE ps2_runtime)
    add_test(NAME dma_chain_resource_limits COMMAND ps2x_dma_chain_limits)
    set_tests_properties(dma_chain_resource_limits PROPERTIES TIMEOUT 60)
endif()

# Compile actual integer emitter output under UBSan, independently of the host runtime.
# clang-cl/MSVC CTest environments may not carry the developer-shell LIB/INCLUDE;
# Windows uses the same script manually with clang++ after vcvars64.
if(BUILD_TESTING AND NOT MSVC AND CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_Interpreter_FOUND)
        add_executable(ps2x_integer_emit_probe src/integer_emit_probe.cpp)
        target_link_libraries(ps2x_integer_emit_probe PRIVATE ps2_recomp_lib)
        add_test(NAME emitted_integer_ubsan
            COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/integer_emitted_regression.py"
                --probe "$<TARGET_FILE:ps2x_integer_emit_probe>"
                --runtime-header "${CMAKE_SOURCE_DIR}/ps2xRuntime/include/ps2_runtime_macros.h"
                --cxx "${CMAKE_CXX_COMPILER}"
                --output "${CMAKE_CURRENT_BINARY_DIR}/integer-regressions")
        set_tests_properties(emitted_integer_ubsan PROPERTIES TIMEOUT 120)
    endif()
endif()

# Independent bitwise oracle against the actual runtime helper; no game fixture.
if(BUILD_TESTING)
    add_executable(ps2x_fmac_classify_witness src/fmac_classify_witness.cpp
        $<TARGET_OBJECTS:ps2_test_function_table>)
    target_link_libraries(ps2x_fmac_classify_witness PRIVATE ps2_runtime)
    add_test(NAME vu_fmac_normal_classification COMMAND ps2x_fmac_classify_witness)
    set_tests_properties(vu_fmac_normal_classification PROPERTIES TIMEOUT 30)
endif()

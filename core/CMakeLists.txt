cmake_minimum_required(VERSION 3.21)

if(NOT DEFINED CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{VITASDK})
    set(PS2X_VITA_TOOLCHAIN_FILE "$ENV{VITASDK}/share/vita.toolchain.cmake")
    if(EXISTS "${PS2X_VITA_TOOLCHAIN_FILE}")
        set(CMAKE_TOOLCHAIN_FILE "${PS2X_VITA_TOOLCHAIN_FILE}" CACHE PATH
            "Toolchain file used for cross-compiling" FORCE)
        message(STATUS "Using VitaSDK toolchain from VITASDK: ${CMAKE_TOOLCHAIN_FILE}")
    endif()
endif()

project(PS2RetroX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# LODESTONE PATCH 7 — enable C++ exceptions for every target on an
# MSVC-compatible driver.
#
# clang-cl defaults to `-fno-exceptions` unless /EHsc is passed, while the real
# MSVC driver allows try/throw without it. Upstream therefore builds under
# clang-cl and stops immediately in any file that uses exceptions:
#
#   ps2xIOP/src/emulator/iop_emulator.cpp(510,17): error: cannot use 'throw'
#                                                       with exceptions disabled
#
# This bit targets like ps2_iop, because ReleaseMode.cmake only reaches targets
# that call EnableFastReleaseMode() and ps2_iop is not one of them. Applying it
# here fixes the whole tree at once. Recorded as dead_ends.jsonl#0058.
if(MSVC)
    add_compile_options(/EHsc)
endif()

option(PS2X_BUILD_RECOMP "Build ps2xRecomp" ON)
option(PS2X_BUILD_RUNTIME "Build ps2xRuntime" ON)
option(PS2X_BUILD_ANALYZER "Build ps2xAnalyzer" ON)
option(PS2X_BUILD_TEST "Build ps2xTest" ON)
option(PS2X_BUILD_STUDIO "Build ps2xStudio" ON)

if(ANDROID)
    message(STATUS "Android target detected, building runtime only")
    set(PS2X_BUILD_RECOMP OFF)
    set(PS2X_BUILD_ANALYZER OFF)
    set(PS2X_BUILD_TEST OFF)
    set(PS2X_BUILD_STUDIO OFF)
endif()

set(PS2X_IS_ARM_TARGET OFF)
set(PS2X_IS_AARCH64_TARGET OFF)
if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64|ARM64")
    set(PS2X_IS_ARM_TARGET ON)
    set(PS2X_IS_AARCH64_TARGET ON)
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^arm|^ARM")
    set(PS2X_IS_ARM_TARGET ON)
endif()

if((CMAKE_C_COMPILER MATCHES "arm-vita-eabi") OR
   (CMAKE_CXX_COMPILER MATCHES "arm-vita-eabi"))
    set(PS2X_IS_ARM_TARGET ON)
endif()

if(PS2X_IS_ARM_TARGET)
    message(STATUS "ARM target detected, fetching sse2neon")

    include(FetchContent)
    FetchContent_Declare(
        sse2neon
        GIT_REPOSITORY https://github.com/DLTcollab/sse2neon.git
        GIT_TAG v1.9.1
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(sse2neon)

    include_directories(${sse2neon_SOURCE_DIR})
    add_compile_definitions(USE_SSE2NEON)

    if(PS2X_IS_AARCH64_TARGET AND APPLE)
        # macOS ARM64 already uses optimal defaults
        message(STATUS "macOS ARM64 - using default compiler flags")
    elseif(PS2X_IS_AARCH64_TARGET AND MSVC)
        # Windows ARM64 - MSVC already uses optimal defaults
        message(STATUS "Windows ARM64 (MSVC) - using default compiler flags")
    elseif(PS2X_IS_AARCH64_TARGET)
        # Linux ARM64 - add NEON flags
        message(STATUS "Non-Apple ARM64 - adding NEON compiler flags")
        add_compile_options(-march=armv8-a+fp+simd)

        # Try to enable crypto and CRC extensions if supported
        include(CheckCXXCompilerFlag)
        check_cxx_compiler_flag("-march=armv8-a+fp+simd+crypto+crc" COMPILER_SUPPORTS_CRYPTO_CRC)
        if(COMPILER_SUPPORTS_CRYPTO_CRC)
            set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -march=armv8-a+fp+simd+crypto+crc")
            message(STATUS "Crypto and CRC extensions enabled")
        else()
            add_compile_options(-march=armv8-a+fp+simd)
        endif()
    endif()
endif()

# Instruction set for the runtime and runner: SSE4.1 (floor) or AVX2.
set(PS2X_TARGET_ARCH "SSE4.1" CACHE STRING "x86 target: SSE4.1 or AVX2")
set_property(CACHE PS2X_TARGET_ARCH PROPERTY STRINGS SSE4.1 AVX2)

# Profile-guided optimization (Clang): GENERATE builds an instrumented runner
# that writes LLVM_PROFILE_FILE every 600 vsyncs; merge the .profraw files
# with llvm-profdata and build again with USE. tools/build/pgo_build.ps1 runs
# the whole pipeline in separate build directories.
set(PS2X_PGO "OFF" CACHE STRING "Profile-guided optimization: OFF, GENERATE or USE")
set_property(CACHE PS2X_PGO PROPERTY STRINGS OFF GENERATE USE)
set(PS2X_PGO_PROFILE "" CACHE FILEPATH "Merged .profdata used by PS2X_PGO=USE")
if(NOT PS2X_PGO STREQUAL "OFF")
    if(NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        message(FATAL_ERROR "PS2X_PGO requires Clang")
    endif()
    if(PS2X_PGO STREQUAL "GENERATE")
        add_compile_options(-fprofile-instr-generate)
        add_compile_definitions(PS2X_PGO_GENERATE=1)
        get_filename_component(PS2X_LLVM_ROOT "${CMAKE_CXX_COMPILER}" DIRECTORY)
        file(GLOB PS2X_PROFILE_RUNTIME "${PS2X_LLVM_ROOT}/../lib/clang/*/lib/windows/clang_rt.profile-x86_64.lib")
        if(NOT PS2X_PROFILE_RUNTIME)
            message(FATAL_ERROR "clang_rt.profile-x86_64.lib not found under ${PS2X_LLVM_ROOT}/../lib/clang")
        endif()
        list(GET PS2X_PROFILE_RUNTIME 0 PS2X_PROFILE_RUNTIME)
        add_link_options("${PS2X_PROFILE_RUNTIME}")
        message(STATUS "> PGO: instrumented build (${PS2X_PROFILE_RUNTIME})")
    elseif(PS2X_PGO STREQUAL "USE")
        if(NOT EXISTS "${PS2X_PGO_PROFILE}")
            message(FATAL_ERROR "PS2X_PGO=USE needs PS2X_PGO_PROFILE pointing at a merged .profdata")
        endif()
        add_compile_options("-fprofile-instr-use=${PS2X_PGO_PROFILE}"
                            -Wno-profile-instr-unprofiled -Wno-profile-instr-out-of-date -Wno-profile-instr-missing)
        message(STATUS "> PGO: optimizing with ${PS2X_PGO_PROFILE}")
    else()
        message(FATAL_ERROR "PS2X_PGO must be OFF, GENERATE or USE")
    endif()
endif()

if(PS2X_BUILD_RECOMP)
    add_subdirectory("ps2xRecomp")
endif()

if(PS2X_BUILD_RUNTIME)
    add_subdirectory("ps2xIOP")
    add_subdirectory("ps2xRuntime")
endif()

if(PS2X_BUILD_ANALYZER)
    add_subdirectory("ps2xAnalyzer")
endif()

if(PS2X_BUILD_TEST)
    add_subdirectory("ps2xTest")
endif()

if(PS2X_BUILD_STUDIO)
    add_subdirectory("ps2xStudio")
endif()

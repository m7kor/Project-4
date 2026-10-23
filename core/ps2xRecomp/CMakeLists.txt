cmake_minimum_required(VERSION 3.20)

project(PS2Recomp VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

include(FetchContent)

FetchContent_Declare(
    elfio
    GIT_REPOSITORY https://github.com/serge1/ELFIO.git
    GIT_TAG Release_3.12
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(elfio)

FetchContent_Declare(
    toml11
    GIT_REPOSITORY https://github.com/ToruNiina/toml11.git
    GIT_TAG v4.4.0
)
FetchContent_MakeAvailable(toml11)

FetchContent_Declare(
    fmt
    GIT_REPOSITORY https://github.com/fmtlib/fmt.git
    GIT_TAG 12.1.0
)
FetchContent_MakeAvailable(fmt)
 
FetchContent_Declare(
    libdwarf
    GIT_REPOSITORY https://github.com/davea42/libdwarf-code.git
    GIT_TAG v2.2.0
    GIT_SHALLOW TRUE
)

set(BUILD_DWARFDUMP    OFF CACHE BOOL "" FORCE)
set(BUILD_DWARFEXAMPLE OFF CACHE BOOL "" FORCE)
set(BUILD_DWARFGEN     OFF CACHE BOOL "" FORCE)

set(BUILD_SHARED   OFF CACHE BOOL "" FORCE)
set(BUILD_NON_SHARED ON CACHE BOOL "" FORCE)

FetchContent_MakeAvailable(libdwarf)

set(LIBDWARF_INCLUDE_DIR "${libdwarf_SOURCE_DIR}/src/lib/libdwarf")

FetchContent_Declare(
    rabbitizer
    GIT_REPOSITORY https://github.com/Decompollaborate/rabbitizer.git
    GIT_TAG 1.14.3
)
FetchContent_MakeAvailable(rabbitizer)

if (NOT TARGET rabbitizer)
    file(GLOB_RECURSE RABBITIZER_SOURCES CONFIGURE_DEPENDS
        "${rabbitizer_SOURCE_DIR}/src/analysis/*.c"
        "${rabbitizer_SOURCE_DIR}/src/common/*.c"
        "${rabbitizer_SOURCE_DIR}/src/instructions/*.c"
        "${rabbitizer_SOURCE_DIR}/src/instructions/*/*.c"
    )

    add_library(rabbitizer STATIC ${RABBITIZER_SOURCES})

    target_include_directories(rabbitizer PUBLIC
        "${rabbitizer_SOURCE_DIR}/include"
        "${rabbitizer_SOURCE_DIR}/tables"
        "${rabbitizer_SOURCE_DIR}/tables/tables"
    )
endif()

file(GLOB_RECURSE PS2RECOMP_LIB_SOURCES CONFIGURE_DEPENDS
    src/lib/*.cpp
)

file(GLOB_RECURSE PS2RECOMP_HEADERS CONFIGURE_DEPENDS
    include/*.h
    include/*.hpp
)

add_library(ps2_recomp_lib STATIC ${PS2RECOMP_LIB_SOURCES} ${PS2RECOMP_HEADERS})

target_compile_definitions(ps2_recomp_lib
PUBLIC
    LIBDWARF_STATIC
PRIVATE
    LIBDWARF_STATIC
)

# LODESTONE PATCH 4 — the strict-return option must be visible to the
# RECOMPILER, not only to the runtime.
#
# The option is declared in ps2xRuntime/CMakeLists.txt:16, which is only
# processed when PS2X_BUILD_RUNTIME=ON, and it is applied to the ps2_runtime
# target at line 422-426. But the `#if defined(PS2X_STRICT_RETURN_DIAGNOSTICS)`
# is *emitted into the generated C++* by ControlFlowEmitter
# (control_flow_emitter.cpp:259) — that #if is compiled later, as part of
# whatever target owns the generated sources.
#
# Measured on RE4: configured with -DPS2X_STRICT_RETURN_DIAGNOSTICS=ON, the
# generated tree contained ZERO `GuestBranchKind::Return` occurrences. The flag
# was ON in the cache and had no effect on codegen at all, because the recompiler
# library never saw it.
#
# Consequence of getting this wrong: `jr $ra` emits a bare
#     ctx->pc = target; return;
# with no existence check, so a missing return target is SILENT. The whole point
# of the flag is to make that loud, and the documented way to enable it does not.
#
# Fix: define it for ps2_recomp_lib as well, so the emitted #if is chosen at
# generation time rather than left to whoever compiles the output. Recorded as
# dead_ends.jsonl#0049.
if(PS2X_STRICT_RETURN_DIAGNOSTICS)
    target_compile_definitions(ps2_recomp_lib PRIVATE PS2X_STRICT_RETURN_DIAGNOSTICS=1)
endif()

# The generated sources must agree with whatever compiled the runtime, otherwise
# the #if resolves differently in the two translation units and dispatchGuestBranch
# gets called with a runtime that was not built for it.
if(PS2X_STRICT_RETURN_DIAGNOSTICS)
    message(STATUS "> PS2X_STRICT_RETURN_DIAGNOSTICS=ON: JR \$ra will be routed "
                   "through runtime->dispatchGuestBranch in generated code")
else()
    message(STATUS "> PS2X_STRICT_RETURN_DIAGNOSTICS=OFF (default): JR \$ra is a bare "
                   "'pc = target; return'. A missing return target is SILENT. "
                   "Turn this ON for any new port.")
endif()

target_include_directories(ps2_recomp_lib
PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${elfio_SOURCE_DIR}
    ${LIBDWARF_INCLUDE_DIR}

PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../ps2xRuntime/include
)

target_link_libraries(ps2_recomp_lib
PUBLIC
    fmt::fmt
    toml11::toml11 
    dwarf
    rabbitizer
)

file(GLOB_RECURSE PS2RECOMP_EXE_SOURCES CONFIGURE_DEPENDS
    src/runner/*.cpp
)

add_executable(ps2_recomp ${PS2RECOMP_EXE_SOURCES})
add_executable(ps2_native_module_codegen src/tools/native_module_codegen_main.cpp)
add_executable(ps2_ee_body_codegen src/tools/ee_body_codegen_main.cpp)
target_link_libraries(ps2_native_module_codegen PRIVATE ps2_recomp_lib)
target_link_libraries(ps2_ee_body_codegen PRIVATE ps2_recomp_lib)

target_link_libraries(ps2_recomp
PRIVATE
    ps2_recomp_lib
)

install(TARGETS ps2_recomp ps2_recomp_lib ps2_native_module_codegen ps2_ee_body_codegen
    RUNTIME DESTINATION bin
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)

install(DIRECTORY include/
    DESTINATION include
)

include("${CMAKE_SOURCE_DIR}/ps2xRuntime/cmake/ReleaseMode.cmake")

if(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
    EnableFastReleaseMode(ps2_recomp_lib)
    EnableFastReleaseMode(ps2_recomp)
endif()

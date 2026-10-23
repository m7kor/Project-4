cmake_minimum_required(VERSION 3.20)

if(POLICY CMP0131)
    cmake_policy(SET CMP0131 NEW)
endif()

project(PS2Runtime VERSION 0.1.0 LANGUAGES CXX)

include("${CMAKE_CURRENT_SOURCE_DIR}/DirectXHeaders.cmake")

# Texture coordinates are truncated to texel indices. Fast reciprocal math
# can turn an exact boundary (1.0) into the previous texel in Release builds.
if(MSVC)
    set_property(SOURCE src/lib/gs/gs_cpu_backend.cpp APPEND PROPERTY COMPILE_OPTIONS /fp:precise)
elseif(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    set_property(SOURCE src/lib/gs/gs_cpu_backend.cpp APPEND PROPERTY COMPILE_OPTIONS -fno-fast-math -ffp-contract=off)
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(PS2X_ENABLE_RUNNER_UNITY_BUILD "Build ps2EntryRunner with CMake unity build" ON)
set(PS2X_RUNNER_UNITY_BUILD_BATCH_SIZE 32 CACHE STRING "Unity build batch size for ps2EntryRunner")
option(PS2X_ENABLE_RUNNER_PCH "Precompile the heavy runtime headers for ps2EntryRunner" ON)
option(PS2X_ENABLE_SCCACHE "Use sccache as compiler launcher when available" ON)

option(PS2X_ENABLE_RUNTIME_LOGS "Enable PS2 runtime logs" ON)
option(PS2X_ENABLE_AGRESSIVE_LOGS "Enable very verbose/agressive PS2 runtime logs" ON)
option(PS2X_ENABLE_IOP_RPC_TRACE "Log unhandled IOP/SIF RPC trace suggestions" ON)
option(PS2X_STRICT_RETURN_DIAGNOSTICS "Route generated JR $ra returns through runtime branch diagnostics" OFF)
# LODESTONE: guest PC sampling profile. Compile-time, because EeScheduler::run
# is the hottest loop in the runtime and DC2 measured that env-guarded
# diagnostics in a hot TU cost real frame time (rules 12c/16). OFF links
# exactly as if the feature did not exist.
option(PS2X_GUEST_PC_PROFILE "Sample and report the guest EE PC histogram" OFF)
option(PS2X_SHOW_WINDOWS_CONSOLE "Show a console window for ps2EntryRunner on Windows release builds" ON)
option(PS2X_ENABLE_DEBUG_UI "Build the desktop runtime debug UI" ON)

if(PS2X_ENABLE_SCCACHE)
    find_program(PS2X_SCCACHE_PROGRAM sccache)

    if(PS2X_SCCACHE_PROGRAM)
        if(CMAKE_C_COMPILER)
            set(CMAKE_C_COMPILER_LAUNCHER "${PS2X_SCCACHE_PROGRAM}")
        endif()

        set(CMAKE_CXX_COMPILER_LAUNCHER "${PS2X_SCCACHE_PROGRAM}")
        message(STATUS "Using sccache: ${PS2X_SCCACHE_PROGRAM}")
    else()
        message(STATUS "sccache not found; continuing without compiler launcher")
    endif()
endif()

include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/ReleaseMode.cmake")

set(PS2X_IS_VITA OFF)

if((CMAKE_C_COMPILER MATCHES "arm-vita-eabi") OR
    (CMAKE_CXX_COMPILER MATCHES "arm-vita-eabi"))
    set(PS2X_IS_VITA ON)
endif()

set(PS2X_IS_ANDROID OFF)

if(ANDROID)
    set(PS2X_IS_ANDROID ON)
endif()

option(PS2X_VITA_CREATE_PACKAGE "Create Vita eboot/vpk targets" ON)
set(PS2X_VITA_APP_NAME "PS2 Retro X" CACHE STRING "Display name for the Vita bubble")
set(PS2X_VITA_TITLEID "RANJ00001" CACHE STRING "9-character Vita title id")
set(PS2X_VITA_VERSION "01.00" CACHE STRING "Vita app version")
set(PS2X_DEFAULT_BOOT_ELF "" CACHE STRING "Guest ELF path passed directly to main() when argv is unavailable")

if(PS2X_IS_VITA)
    if(NOT DEFINED ENV{VITASDK})
        message(FATAL_ERROR "VITASDK is not defined. Configure inside the VitaSDK environment or pass the Vita toolchain file.")
    endif()

    set(PS2X_VITASDK "$ENV{VITASDK}")

    if(NOT EXISTS "${PS2X_VITASDK}/share/vita.cmake")
        message(FATAL_ERROR "Could not find vita.cmake under ${PS2X_VITASDK}/share.")
    endif()

    include("${PS2X_VITASDK}/share/vita.cmake" REQUIRED)
else()
    include(FetchContent)
    set(FETCHCONTENT_QUIET FALSE)
    set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(BUILD_GAMES OFF CACHE BOOL "" FORCE)

    if(PS2X_IS_ANDROID)
        set(PLATFORM "Android" CACHE STRING "" FORCE)
    endif()

    FetchContent_Declare(
        raylib
        GIT_REPOSITORY "https://github.com/raysan5/raylib.git"
        GIT_TAG "5.5" # we will migrate to 4.2.0 later, trust me it will be better
        GIT_PROGRESS TRUE
    )
    FetchContent_MakeAvailable(raylib)

    if(PS2X_ENABLE_DEBUG_UI AND NOT PS2X_IS_ANDROID)
        FetchContent_Declare(
            imgui
            GIT_REPOSITORY https://github.com/ocornut/imgui.git
            GIT_TAG "v1.92.7-docking"
            GIT_SHALLOW TRUE
        )
        FetchContent_GetProperties(imgui)

        if(NOT imgui_POPULATED)
            FetchContent_Populate(imgui)
        endif()

        set(PS2X_IMGUI_SOURCE_DIR "${imgui_SOURCE_DIR}")

        add_library(imgui STATIC
            "${PS2X_IMGUI_SOURCE_DIR}/imgui.cpp"
            "${PS2X_IMGUI_SOURCE_DIR}/imgui_draw.cpp"
            "${PS2X_IMGUI_SOURCE_DIR}/imgui_tables.cpp"
            "${PS2X_IMGUI_SOURCE_DIR}/imgui_widgets.cpp"
            "${PS2X_IMGUI_SOURCE_DIR}/imgui_demo.cpp"
        )
        target_include_directories(imgui PUBLIC "${PS2X_IMGUI_SOURCE_DIR}")

        FetchContent_Declare(
            rlImGui
            GIT_REPOSITORY https://github.com/raylib-extras/rlImGui.git
            GIT_TAG "Raylib_5_5"
            GIT_SHALLOW TRUE
        )
        FetchContent_GetProperties(rlImGui)

        if(NOT rlimgui_POPULATED)
            FetchContent_Populate(rlImGui)
        endif()

        set(PS2X_RLIMGUI_SOURCE_DIR "${rlimgui_SOURCE_DIR}")

        add_library(rlImGui STATIC
            "${PS2X_RLIMGUI_SOURCE_DIR}/rlImGui.cpp"
        )
        target_include_directories(rlImGui PUBLIC "${PS2X_RLIMGUI_SOURCE_DIR}")
        target_link_libraries(rlImGui PUBLIC raylib imgui)
    endif()
endif()

add_library(ps2_host_backend INTERFACE)

set(PS2X_DEFAULT_BOOT_ELF_DEFINE "")

if(PS2X_DEFAULT_BOOT_ELF)
    set(PS2X_DEFAULT_BOOT_ELF_DEFINE "${PS2X_DEFAULT_BOOT_ELF}")
    string(REPLACE "\\" "\\\\" PS2X_DEFAULT_BOOT_ELF_DEFINE "${PS2X_DEFAULT_BOOT_ELF_DEFINE}")
    string(REPLACE "\"" "\\\"" PS2X_DEFAULT_BOOT_ELF_DEFINE "${PS2X_DEFAULT_BOOT_ELF_DEFINE}")
endif()

if(PS2X_IS_VITA)
    set(PS2X_VITA_PREFIX "${PS2X_VITASDK}/arm-vita-eabi")
    set(PS2X_VITA_EXTRA_INCLUDE_DIRS "" CACHE STRING "Extra include directories for Vita host dependencies")
    set(PS2X_VITA_LIBRARY_DIR "${PS2X_VITA_PREFIX}/lib")
    set(PS2X_VITA_REQUIRED_LIBRARY_NAMES
        raylib
        SDL2
        OpenSLES
        taihen_stub
        SceAppMgr_stub
        SceCtrl_stub
        SceGxm_stub
        SceCommonDialog_stub
        SceLibKernel_stub
        SceAudio_stub
        SceTouch_stub
        SceHid_stub
        SceMotion_stub
        SceSysmodule_stub
        SceIofilemgr_stub
        SceNetCtl_stub
        SceNet_stub
        SceDisplay_stub
        SceAppUtil_stub
        SceAudioIn_stub
        ScePower_stub
        SceProcessmgr_stub
        SceIme_stub
        libIMGEGL_stub_weak
        libgpu_es4_ext_stub_weak
        libGLESv2_stub_weak
        libGL_stub_weak
        libGLESv1_CM_stub_weak
    )

    set(PS2X_VITA_INCLUDE_DIRS
        "${PS2X_VITA_PREFIX}/include"
    )

    foreach(PS2X_VITA_OPTIONAL_INCLUDE_DIR IN ITEMS
        "${PS2X_VITA_PREFIX}/include/raylib"
        "${PS2X_VITA_PREFIX}/include/SDL2")
        if(EXISTS "${PS2X_VITA_OPTIONAL_INCLUDE_DIR}")
            list(APPEND PS2X_VITA_INCLUDE_DIRS "${PS2X_VITA_OPTIONAL_INCLUDE_DIR}")
        endif()
    endforeach()

    if(PS2X_VITA_EXTRA_INCLUDE_DIRS)
        list(APPEND PS2X_VITA_INCLUDE_DIRS ${PS2X_VITA_EXTRA_INCLUDE_DIRS})
    endif()

    if(NOT EXISTS "${PS2X_VITA_PREFIX}/include/SDL2/SDL.h")
        message(FATAL_ERROR
            "Missing SDL2 headers under ${PS2X_VITA_PREFIX}/include/SDL2. "
            "Quenom/raylib-5.5-vita requires SDL2 with PVR support installed into VitaSDK.")
    endif()

    if(NOT EXISTS "${PS2X_VITA_LIBRARY_DIR}")
        message(FATAL_ERROR "Missing Vita library directory: ${PS2X_VITA_LIBRARY_DIR}")
    endif()

    function(ps2x_find_vita_library out_var library_name)
        string(MAKE_C_IDENTIFIER "${library_name}" library_id)
        set(cache_var "PS2X_VITA_LIB_${library_id}")

        find_library(${cache_var}
            NAMES "${library_name}" "${library_name}.a" "lib${library_name}.a"
            PATHS "${PS2X_VITA_LIBRARY_DIR}"
            NO_DEFAULT_PATH
        )

        if(NOT ${cache_var})
            message(FATAL_ERROR
                "Could not find Vita library '${library_name}' under ${PS2X_VITA_LIBRARY_DIR}. "
                "Install Quenom/raylib-5.5-vita and its SDL2/PVR dependencies into VitaSDK first.")
        endif()

        set(${out_var} "${${cache_var}}" PARENT_SCOPE)
    endfunction()

    set(PS2X_VITA_RESOLVED_LIBRARIES "")

    foreach(PS2X_VITA_LIBRARY_NAME IN LISTS PS2X_VITA_REQUIRED_LIBRARY_NAMES)
        ps2x_find_vita_library(PS2X_VITA_LIBRARY_PATH "${PS2X_VITA_LIBRARY_NAME}")
        list(APPEND PS2X_VITA_RESOLVED_LIBRARIES "${PS2X_VITA_LIBRARY_PATH}")
    endforeach()

    target_compile_definitions(ps2_host_backend INTERFACE PLATFORM_VITA)
    target_include_directories(ps2_host_backend INTERFACE ${PS2X_VITA_INCLUDE_DIRS})
    target_link_libraries(ps2_host_backend INTERFACE
        ${PS2X_VITA_RESOLVED_LIBRARIES}
        m
        c
        pthread
    )
else()
    target_link_libraries(ps2_host_backend INTERFACE raylib)

    if(PS2X_IS_ANDROID)
        target_link_libraries(ps2_host_backend INTERFACE log android)
    endif()
endif()

if(PS2X_IS_ANDROID)
    set(PS2X_ENABLE_FFMPEG_DEFAULT OFF)
else()
    set(PS2X_ENABLE_FFMPEG_DEFAULT ON)
endif()

option(PS2X_ENABLE_FFMPEG "Enable FFmpeg-backed MPEG video decoding" ${PS2X_ENABLE_FFMPEG_DEFAULT})

if(NOT PS2X_ENABLE_FFMPEG)
    message(STATUS "FFmpeg disabled; MPEG video decode falls back to stub frames")
    add_library(ffmpeg INTERFACE)
elseif(WIN32)
    include(ExternalProject)

    set(FFMPEG_PREBUILT_TAG "n7.1-241205")
    set(FFMPEG_PREBUILT_URL
        "https://github.com/System233/ffmpeg-msvc-prebuilt/releases/download/${FFMPEG_PREBUILT_TAG}/ffmpeg-${FFMPEG_PREBUILT_TAG}-lgpl-amd64-shared.zip")

    set(FFMPEG_PREFIX_DIR "${CMAKE_BINARY_DIR}/ThirdParty/ffmpeg-prefix")
    set(PS2X_FFMPEG_ROOT "" CACHE PATH "Installed FFmpeg shared package (include/ and bin/)")
    if(PS2X_FFMPEG_ROOT)
        get_filename_component(FFMPEG_SOURCE_DIR "${PS2X_FFMPEG_ROOT}" ABSOLUTE)
        foreach(component avcodec avformat avutil swresample swscale)
            if(NOT EXISTS "${FFMPEG_SOURCE_DIR}/bin/${component}.lib")
                message(FATAL_ERROR "Missing installed FFmpeg library: ${component}")
            endif()
        endforeach()
        if(NOT EXISTS "${FFMPEG_SOURCE_DIR}/include/libavcodec/avcodec.h")
            message(FATAL_ERROR "Installed FFmpeg headers not found")
        endif()
    else()
        set(FFMPEG_SOURCE_DIR "${FFMPEG_PREFIX_DIR}/src/ffmpeg_external")
    endif()
    set(FFMPEG_INCLUDE_DIR "${FFMPEG_SOURCE_DIR}/include")
    set(FFMPEG_LIB_DIR "${FFMPEG_SOURCE_DIR}/bin")
    set(FFMPEG_BIN_DIR "${FFMPEG_SOURCE_DIR}/bin")

    if(PS2X_FFMPEG_ROOT)
        add_custom_target(ffmpeg_external)
    else()
      ExternalProject_Add(ffmpeg_external
        URL "${FFMPEG_PREBUILT_URL}"
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE
        PREFIX "${FFMPEG_PREFIX_DIR}"
        CONFIGURE_COMMAND ""
        BUILD_COMMAND ""
        INSTALL_COMMAND ""
        BUILD_BYPRODUCTS
        "${FFMPEG_LIB_DIR}/avcodec.lib"
        "${FFMPEG_LIB_DIR}/avformat.lib"
        "${FFMPEG_LIB_DIR}/avutil.lib"
        "${FFMPEG_LIB_DIR}/swresample.lib"
        "${FFMPEG_LIB_DIR}/swscale.lib"
    )

    endif()

    # Link against the import libraries shipped with the Windows DLLs.
    add_library(ffmpeg_avcodec STATIC IMPORTED GLOBAL)
    set_target_properties(ffmpeg_avcodec PROPERTIES
        IMPORTED_LOCATION "${FFMPEG_LIB_DIR}/avcodec.lib"
        INTERFACE_INCLUDE_DIRECTORIES "${FFMPEG_INCLUDE_DIR}"
    )
    add_dependencies(ffmpeg_avcodec ffmpeg_external)

    add_library(ffmpeg_avformat STATIC IMPORTED GLOBAL)
    set_target_properties(ffmpeg_avformat PROPERTIES
        IMPORTED_LOCATION "${FFMPEG_LIB_DIR}/avformat.lib"
        INTERFACE_INCLUDE_DIRECTORIES "${FFMPEG_INCLUDE_DIR}"
    )
    add_dependencies(ffmpeg_avformat ffmpeg_external)

    add_library(ffmpeg_avutil STATIC IMPORTED GLOBAL)
    set_target_properties(ffmpeg_avutil PROPERTIES
        IMPORTED_LOCATION "${FFMPEG_LIB_DIR}/avutil.lib"
        INTERFACE_INCLUDE_DIRECTORIES "${FFMPEG_INCLUDE_DIR}"
    )
    add_dependencies(ffmpeg_avutil ffmpeg_external)

    add_library(ffmpeg_swresample STATIC IMPORTED GLOBAL)
    set_target_properties(ffmpeg_swresample PROPERTIES
        IMPORTED_LOCATION "${FFMPEG_LIB_DIR}/swresample.lib"
        INTERFACE_INCLUDE_DIRECTORIES "${FFMPEG_INCLUDE_DIR}"
    )
    add_dependencies(ffmpeg_swresample ffmpeg_external)

    add_library(ffmpeg_swscale STATIC IMPORTED GLOBAL)
    set_target_properties(ffmpeg_swscale PROPERTIES
        IMPORTED_LOCATION "${FFMPEG_LIB_DIR}/swscale.lib"
        INTERFACE_INCLUDE_DIRECTORIES "${FFMPEG_INCLUDE_DIR}"
    )
    add_dependencies(ffmpeg_swscale ffmpeg_external)

    add_library(ffmpeg INTERFACE)
    target_link_libraries(ffmpeg INTERFACE
        ffmpeg_avcodec
        ffmpeg_avformat
        ffmpeg_avutil
        ffmpeg_swresample
        ffmpeg_swscale
        bcrypt
        secur32
        ws2_32
        user32
        advapi32
        ole32
        shell32
    )

    set(PS2X_FFMPEG_BIN_DIR "${FFMPEG_BIN_DIR}" CACHE INTERNAL "Directory containing FFmpeg runtime DLLs")
    set(PS2X_COPY_FFMPEG_DLLS_SCRIPT
        "${CMAKE_CURRENT_SOURCE_DIR}/cmake/CopyFfmpegDlls.cmake"
        CACHE INTERNAL
        "Script used to stage FFmpeg runtime DLLs beside executables")
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET GLOBAL
        libavcodec
        libavformat
        libavutil
        libswresample
        libswscale
    )

    add_library(ffmpeg INTERFACE)
    target_link_libraries(ffmpeg INTERFACE PkgConfig::FFMPEG)
endif()

function(ps2x_stage_ffmpeg_runtime_dlls target_name)
    if(NOT WIN32)
        return()
    endif()

    if(NOT PS2X_FFMPEG_BIN_DIR OR NOT PS2X_COPY_FFMPEG_DLLS_SCRIPT)
        return()
    endif()

    if(TARGET ffmpeg_external)
        add_dependencies(${target_name} ffmpeg_external)
    endif()

    add_custom_command(
        TARGET ${target_name} POST_BUILD
        COMMAND "${CMAKE_COMMAND}"
        "-Dsource_dir=${PS2X_FFMPEG_BIN_DIR}"
        "-Ddest_dir=$<TARGET_FILE_DIR:${target_name}>"
        -P "${PS2X_COPY_FFMPEG_DLLS_SCRIPT}"
        VERBATIM
    )
endfunction()

# The VU1 interpreter TU (with the compiled microprograms) gains from AVX2;
# FP contraction stays off so results match the PS2 rounding model.
option(PS2X_VU1_AVX2 "Compile the VU1 interpreter with AVX2 (no measured gain on 2026-10-12)" OFF)
if(PS2X_VU1_AVX2 AND MSVC AND CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    set_source_files_properties(src/lib/vu/ps2_vu1_core.cpp PROPERTIES
        COMPILE_OPTIONS "/clang:-mavx2;/clang:-mfma;/clang:-ffp-contract=off")
endif()

add_library(ps2_runtime STATIC
    src/lib/native_module_registry.cpp
    src/lib/snr2_native_binding.cpp
    src/lib/game_overrides.cpp
    src/lib/gs/ps2_gif_arbiter.cpp
    src/lib/ps2_audio.cpp
    src/lib/ps2_audio_vag.cpp
    src/lib/gs/ps2_gs_memory.cpp
    src/lib/gs/gs_frontend.cpp
    src/lib/gs/gs_cpu_backend.cpp
    src/lib/ps2_iop_host.cpp
    src/lib/ps2_ipu.cpp
    src/lib/ps2_float_mode.cpp
    src/lib/ps2_memory.cpp
    src/lib/ps2_pad.cpp
    src/lib/ps2_pad_replay.cpp
    src/lib/ps2_rom_device.cpp
    src/lib/ps2_vfs.cpp
    src/lib/ps2_pnach.cpp
    src/lib/ps2_runtime.cpp
    src/lib/ps2_save_storage.cpp
    src/lib/ps2_vif1_interpreter.cpp
    src/lib/ps2_vif_work_queue.cpp
    src/lib/ps2_vu1_execution.cpp
    src/lib/vu/ps2_vu1_core.cpp
    src/lib/games_database.cpp
)

if(NOT PS2X_IS_VITA AND NOT PS2X_IS_ANDROID)
    target_compile_definitions(ps2_runtime PRIVATE PS2X_HOST_GLFW=1)
    target_include_directories(ps2_runtime PRIVATE "${raylib_SOURCE_DIR}/external/glfw/include")
endif()

if(PS2X_ENABLE_RUNTIME_LOGS)
    target_compile_definitions(ps2_runtime PUBLIC
        PS2_RUNTIME_LOGS=1
    )
endif()

if(PS2X_ENABLE_AGRESSIVE_LOGS)
    target_compile_definitions(ps2_runtime PUBLIC
        AGRESSIVE_LOGS=1
        PS2_FUNCTION_LOG_TRACKER=1
    )
endif()

if(PS2X_ENABLE_IOP_RPC_TRACE)
    target_compile_definitions(ps2_runtime PUBLIC
        PS2X_ENABLE_IOP_RPC_TRACE=1
    )
else()
    target_compile_definitions(ps2_runtime PUBLIC
        PS2X_ENABLE_IOP_RPC_TRACE=0
    )
endif()

if(PS2X_STRICT_RETURN_DIAGNOSTICS)
    target_compile_definitions(ps2_runtime PUBLIC
        PS2X_STRICT_RETURN_DIAGNOSTICS=1
    )
endif()

if(PS2X_GUEST_PC_PROFILE)
    # PRIVATE on purpose. The probe lives entirely inside EeScheduler.cpp and
    # this file; making it PUBLIC would invalidate all 8,343 generated TUs on
    # every toggle, for no reason.
    target_compile_definitions(ps2_runtime PRIVATE
        PS2X_GUEST_PC_PROFILE=1
    )
    message(STATUS "> PS2X_GUEST_PC_PROFILE=ON: one PC sample per guest dispatch, "
                   "top-12 window report every \$PS2X_PC_PROFILE_INTERVAL dispatches "
                   "(default 2000000). OFF (default) compiles the probe out entirely.")
endif()

target_compile_definitions(ps2_runtime PRIVATE
    PS2X_HAS_FFMPEG=$<BOOL:${PS2X_ENABLE_FFMPEG}>
)

file(GLOB_RECURSE KERNEL_SRC_FILES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/lib/Kernel/*.cpp"
)

target_sources(ps2_runtime PRIVATE
    ${KERNEL_SRC_FILES}
)

# LODESTONE: the PC profile is added as a SOURCE only when enabled, not just
# with a preprocessor guard. An OFF build then never even compiles the TU, so
# the feature cannot cost a byte of code or an object file. (The in-file
# #if guards remain, because the header is shared with EeScheduler.cpp.)
if(PS2X_GUEST_PC_PROFILE)
    target_sources(ps2_runtime PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src/lib/GuestPcProfile.cpp"
    )
endif()

# LODESTONE PATCH 5 — let the generated tree live outside the source tree.
#
# Upstream hardcodes the recompiler output directory to
# ps2xRuntime/src/runner/*.cpp, which means a port must COPY 5,904 generated
# files (49.7 MB on RE4) into the upstream checkout to build. That is why every
# fork in this field carries a committed or copied runner tree, and why nobody
# can point a build at a profile's output directory.
#
# PS2X_RUNNER_SRC_DIR defaults to the upstream location, so nothing changes for
# anyone who does not set it. Lodestone sets it to recomp/generated/<serial>.
#
# LODESTONE PATCH 13 — CONFIGURE_DEPENDS is removed from this glob, and the
# reason is a measurement, not a preference.
#
# CONFIGURE_DEPENDS makes CMake emit a `cmake.verify_globs` step that re-runs
# the glob check on EVERY ninja invocation. That is cheap for the ~100-file
# kernel glob above and ruinous here: the runner directory holds 8,337 files on
# RE4. Measured on this machine — a ninja run whose entire work list was
# "[1/2] Linking" took **462 seconds**, all of it the verify step, before the
# link even started.
#
# The glob exists only to pick up a machine-generated tree, and we know exactly
# which command regenerates it. An implicit auto-recheck is the wrong mechanism
# for a directory whose contents change on demand; an explicit stamp check is
# both cheaper and more honest, because it fails loudly when the tree changed
# and nobody noticed, instead of silently paying 8 minutes for the privilege.
#
# for a directory whose contents change on demand; an explicit stamp check is
# both cheaper and more honest, because it fails loudly when the tree changed
# and nobody noticed, instead of silently paying 8 minutes for the privilege.
#
# `lodestone build` owns that check now: it compares a stamp of the generated
# directory against the last configure and re-runs CMake only on a real change.
# Nothing about the generated code changes — same files, same flags, same
# output. Build it and the default path is unaffected.
set(PS2X_RUNNER_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/src/runner"
    CACHE PATH "Directory holding the recompiler-generated translation units")

file(GLOB RUNNER_SRC_FILES
    "${PS2X_RUNNER_SRC_DIR}/*.cpp"
)

if(NOT RUNNER_SRC_FILES)
    message(WARNING
        "ps2EntryRunner: no generated sources in ${PS2X_RUNNER_SRC_DIR}. "
        "Run the recompiler first; see docs/01-BUILD.md.")
endif()

list(LENGTH RUNNER_SRC_FILES PS2X_RUNNER_SRC_COUNT)
message(STATUS "> ps2EntryRunner: ${PS2X_RUNNER_SRC_COUNT} generated source(s) from ${PS2X_RUNNER_SRC_DIR}")

set(RUNNER_MAIN_CPP "${CMAKE_CURRENT_SOURCE_DIR}/src/runner/main.cpp")
set(ROOT_MAIN_CPP "${CMAKE_CURRENT_SOURCE_DIR}/src/main.cpp")

if(EXISTS "${RUNNER_MAIN_CPP}")
    list(APPEND RUNNER_SRC_FILES "${RUNNER_MAIN_CPP}")
elseif(EXISTS "${ROOT_MAIN_CPP}")
    list(APPEND RUNNER_SRC_FILES "${ROOT_MAIN_CPP}")
endif()

if(PS2X_IS_ANDROID)
    add_library(ps2EntryRunner SHARED
        ${RUNNER_SRC_FILES}
    )

    target_link_options(ps2EntryRunner PRIVATE "-Wl,--undefined=ANativeActivity_onCreate")
else()
    add_executable(ps2EntryRunner
        ${RUNNER_SRC_FILES}
    )
endif()

# Host profiling: emit a PDB with public symbols for every object so sampling
# profilers (WPR/xperf) resolve function names. Link-only; nothing recompiles.
option(PS2X_RUNNER_PDB "Link ps2EntryRunner with /DEBUG for host profiling" OFF)
if(PS2X_RUNNER_PDB AND MSVC)
    target_link_options(ps2EntryRunner PRIVATE /DEBUG:FULL /OPT:REF /OPT:NOICF)
    # Full debug info for the runtime library only (static functions and
    # lambdas have no public symbols); the generated tree is unaffected.
    target_compile_options(ps2_runtime PRIVATE /Z7)
endif()

set(PS2_NATIVE_MODULE_SOURCE "" CACHE FILEPATH "Game-specific native module installer source")
if(PS2_NATIVE_MODULE_SOURCE)
    if(NOT EXISTS "${PS2_NATIVE_MODULE_SOURCE}")
        message(FATAL_ERROR "Native module installer source does not exist: ${PS2_NATIVE_MODULE_SOURCE}")
    endif()
    target_sources(ps2EntryRunner PRIVATE "${PS2_NATIVE_MODULE_SOURCE}")
    target_compile_definitions(ps2EntryRunner PRIVATE PS2X_NATIVE_MODULE_INSTALLER=1)
    set_source_files_properties("${PS2_NATIVE_MODULE_SOURCE}" PROPERTIES SKIP_UNITY_BUILD_INCLUSION ON)
endif()

# ThinLTO cache: a relink re-optimizes only modules whose bitcode changed.
# Without it every link of the ~8,600-object runner redoes all code
# generation (20-40 minutes with the native SNR2 modules).
if(MSVC AND CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    target_link_options(ps2EntryRunner PRIVATE "/lldltocache:${CMAKE_BINARY_DIR}/lto-cache"
                                               "/lldltocachepolicy:cache_size_bytes=12g")
endif()

# Complete native SNR2 modules (tools/diagnostics/snr2_full_build.py): every
# .cpp in the directory is its own translation unit, so the deduplicated
# bodies compile in parallel with the generated main executable.
set(PS2_NATIVE_MODULE_EXTRA_DIR "" CACHE PATH "Directory of generated native module body/descriptor sources")
if(PS2_NATIVE_MODULE_EXTRA_DIR)
    if(NOT IS_DIRECTORY "${PS2_NATIVE_MODULE_EXTRA_DIR}")
        message(FATAL_ERROR "Native module source directory does not exist: ${PS2_NATIVE_MODULE_EXTRA_DIR}")
    endif()
    file(GLOB PS2_NATIVE_MODULE_EXTRA_SOURCES CONFIGURE_DEPENDS
        "${PS2_NATIVE_MODULE_EXTRA_DIR}/snr2_bodies_*.cpp"
        "${PS2_NATIVE_MODULE_EXTRA_DIR}/snr2_descriptors_*.cpp")
    target_sources(ps2EntryRunner PRIVATE ${PS2_NATIVE_MODULE_EXTRA_SOURCES})
    set_source_files_properties(${PS2_NATIVE_MODULE_EXTRA_SOURCES} PROPERTIES SKIP_UNITY_BUILD_INCLUSION ON)
    list(LENGTH PS2_NATIVE_MODULE_EXTRA_SOURCES PS2_NATIVE_MODULE_EXTRA_COUNT)
    message(STATUS "> native SNR2 module sources: ${PS2_NATIVE_MODULE_EXTRA_COUNT} files from ${PS2_NATIVE_MODULE_EXTRA_DIR}")
endif()

if(PS2X_ENABLE_RUNNER_UNITY_BUILD)
    set_target_properties(ps2EntryRunner PROPERTIES
        UNITY_BUILD ON
        UNITY_BUILD_BATCH_SIZE "${PS2X_RUNNER_UNITY_BUILD_BATCH_SIZE}"
    )
endif()

if(PS2X_ENABLE_RUNNER_PCH)
    set(PS2X_RUNNER_PCH_HEADERS
        "${CMAKE_CURRENT_SOURCE_DIR}/include/ps2_runtime_macros.h"
        "${CMAKE_CURRENT_SOURCE_DIR}/include/ps2_runtime.h"
    )

    foreach(PS2X_RUNNER_GENERATED_HEADER IN ITEMS
        "${CMAKE_CURRENT_SOURCE_DIR}/include/ps2_recompiled_functions.h"
        "${CMAKE_CURRENT_SOURCE_DIR}/include/ps2_recompiled_stubs.h")
        if(EXISTS "${PS2X_RUNNER_GENERATED_HEADER}")
            list(APPEND PS2X_RUNNER_PCH_HEADERS "${PS2X_RUNNER_GENERATED_HEADER}")
        endif()
    endforeach()

    list(APPEND PS2X_RUNNER_PCH_HEADERS
        "${CMAKE_CURRENT_SOURCE_DIR}/include/ps2_syscalls.h"
        "${CMAKE_CURRENT_SOURCE_DIR}/include/ps2_stubs.h"
    )

    target_precompile_headers(ps2EntryRunner PRIVATE ${PS2X_RUNNER_PCH_HEADERS})
endif()

if(PS2X_DEFAULT_BOOT_ELF_DEFINE)
    target_compile_definitions(ps2EntryRunner PRIVATE
        PS2X_DEFAULT_BOOT_ELF="${PS2X_DEFAULT_BOOT_ELF_DEFINE}"
    )
endif()

if(MSVC)
    target_compile_options(ps2EntryRunner PRIVATE /FS)
endif()

option(PS2X_ENABLE_THINLTO_CACHE "Cache unchanged ThinLTO backend output between runner links" ON)
if(PS2X_ENABLE_THINLTO_CACHE AND WIN32 AND CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    target_link_options(ps2EntryRunner PRIVATE
        "/lldltocache:${CMAKE_BINARY_DIR}/thinlto-cache"
        "/lldltocachepolicy:cache_size_bytes=2147483648")
endif()

target_include_directories(ps2_runtime PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src/lib/Kernel
)

# LODESTONE PATCH 5 (continued) — the generated headers live next to the
# generated sources, so the runner needs that directory on its include path.
#
# register_functions.cpp emits:
#     #include <ps2_recompiled_functions.h>
#     #include <ps2_recompiled_stubs.h>
# and those two files are written by the recompiler into general.output, not into
# ps2xRuntime/include. Upstream only worked because every fork copied the whole
# generated tree into src/runner, headers included.
target_include_directories(ps2EntryRunner PRIVATE
    ${PS2X_RUNNER_SRC_DIR}
)

# LODESTONE PATCH 6 — SSE4.1 must be a COMPILER FLAG, not only a macro.
#
# Measured failure on RE4, first compile of the generated tree:
#
#   error: always_inline function '_mm_blendv_ps' requires target feature
#   'sse4.1', but would be inlined into function 'FUN_00102320_0x102320'
#   that is compiled without support for 'sse4.1'
#
# The recompiler emits PS2_VBLEND for VU0 macro-mode ops, which expands to
# _mm_blendv_ps in ps2_runtime_macros.h:72. That header ALSO contains proper
# `#if defined(__SSE4_1__)` fallbacks (lines 441 and 467), so it was written by
# someone who expected the macro to be undefined on old targets — but the
# generated code paths have no such guard, so on a build without -msse4.1 they
# hard-fail.
#
# Upstream never defines USE_SSE41 and never passes -msse4.1 anywhere, so
# upstream cannot compile its own generated output on x86-64 at all. The Agent
# SKILL documents the missing half of this fix as a mandatory CMake surgery
# ("inject add_compile_options(-msse4.1) next to add_compile_definitions(USE_SSE41=ON)
# because add_compile_definitions only sets a macro") but upstream has neither.
#
# SSE4.1 is a hard floor for this project, not an optimisation: the EE core has
# 128-bit GPRs and the generated code is vector-native by design.
# Recorded as dead_ends.jsonl#0042 / #0051.
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|amd64|i686|i386" OR NOT CMAKE_SYSTEM_PROCESSOR)
    if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
        target_compile_options(ps2_runtime PUBLIC -msse4.1)
        target_compile_options(ps2EntryRunner PRIVATE -msse4.1)
        # PS2X_TARGET_ARCH=AVX2 (Haswell and newer). FMA contraction stays off:
        # the PS2 FPU/VU never fuse a*b+c, and the float semantics are exact.
        if(PS2X_TARGET_ARCH STREQUAL "AVX2")
            if(CMAKE_CXX_COMPILER_FRONTEND_VARIANT STREQUAL "MSVC")
                set(PS2X_AVX2_FLAGS /arch:AVX2 /clang:-ffp-contract=off)
            else()
                set(PS2X_AVX2_FLAGS -mavx2 -mfma -mbmi -mbmi2 -mlzcnt -mpopcnt -mf16c -ffp-contract=off)
            endif()
            target_compile_options(ps2_runtime PUBLIC ${PS2X_AVX2_FLAGS})
            target_compile_options(ps2EntryRunner PRIVATE ${PS2X_AVX2_FLAGS})
            message(STATUS "> AVX2 code generation for ps2_runtime and ps2EntryRunner (FMA contraction off)")
        endif()
    elseif(MSVC AND CMAKE_SIZEOF_VOID_P EQUAL 4)
        target_compile_options(ps2_runtime PUBLIC /arch:SSE2)
        target_compile_options(ps2EntryRunner PRIVATE /arch:SSE2)
    endif()
    target_compile_definitions(ps2_runtime PUBLIC USE_SSE41=1)
    target_compile_definitions(ps2EntryRunner PRIVATE USE_SSE41=1)
    message(STATUS "> SSE4.1 enabled for ps2_runtime and ps2EntryRunner "
                   "(required by PS2_VBLEND / _mm_blendv_ps in generated code)")
endif()

# SoundTouch (LGPL-2.1, PCSX2's vendored copy): host audio time stretch with
# PCSX2's settings, see src/lib/audio/host_audio_stretch.h.
set(PS2X_SOUNDTOUCH_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../dependencies/pcsx2/3rdparty/soundtouch")
if(NOT TARGET pcsx2-soundtouch)
    add_subdirectory("${PS2X_SOUNDTOUCH_DIR}" "${CMAKE_BINARY_DIR}/soundtouch" EXCLUDE_FROM_ALL)
endif()
target_link_libraries(ps2_runtime PUBLIC ps2_host_backend ps2_iop)
# FFmpeg is used only by private MPEG implementation files. Static-library
# link dependencies still propagate, without exporting media headers to every
# generated guest function when media support is enabled.
target_link_libraries(ps2_runtime PRIVATE ffmpeg)
target_link_libraries(ps2_runtime PRIVATE pcsx2-soundtouch)

# paraLLEl-GS (LGPL-3.0+): GS on the GPU with Vulkan compute, selected at run
# time with PS2X_GS_BACKEND=parallel (src/lib/gs/gs_parallel_bridge.cpp).
# Library mode, and our DLL C runtime instead of its static default.
set(PS2X_PARALLEL_GS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../dependencies/parallel-gs")
if(NOT TARGET parallel-gs)
    set(PARALLEL_GS_STANDALONE ON CACHE BOOL "" FORCE)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")
    add_subdirectory("${PS2X_PARALLEL_GS_DIR}" "${CMAKE_BINARY_DIR}/parallel-gs" EXCLUDE_FROM_ALL)
endif()
target_sources(ps2_runtime PRIVATE src/lib/gs/gs_parallel_bridge.cpp)
target_link_libraries(ps2_runtime PRIVATE parallel-gs)
target_link_libraries(ps2EntryRunner
    PRIVATE
    ps2_runtime
)

if(PS2X_ENABLE_DEBUG_UI AND NOT PS2X_IS_VITA AND NOT PS2X_IS_ANDROID)
    target_sources(ps2EntryRunner PRIVATE
        src/lib/ps2_debug_panel.cpp
    )
    # Keep UI-only definitions and include paths out of the generated guest TUs.
    # These small host sources do not need the guest precompiled header.
    target_link_libraries(ps2EntryRunner PRIVATE "$<LINK_ONLY:rlImGui>" "$<LINK_ONLY:imgui>")
    set_property(SOURCE "${RUNNER_MAIN_CPP}" "${ROOT_MAIN_CPP}" src/lib/ps2_debug_panel.cpp
        APPEND PROPERTY COMPILE_DEFINITIONS PS2X_ENABLE_DEBUG_UI=1)
    set_property(SOURCE "${RUNNER_MAIN_CPP}" "${ROOT_MAIN_CPP}" src/lib/ps2_debug_panel.cpp
        APPEND PROPERTY INCLUDE_DIRECTORIES "${PS2X_IMGUI_SOURCE_DIR}" "${PS2X_RLIMGUI_SOURCE_DIR}")
    set_source_files_properties("${RUNNER_MAIN_CPP}" "${ROOT_MAIN_CPP}" src/lib/ps2_debug_panel.cpp
        PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
endif()

ps2x_stage_ffmpeg_runtime_dlls(ps2EntryRunner)

if(PS2X_IS_VITA)
    set(VITA_MKSFOEX_FLAGS "${VITA_MKSFOEX_FLAGS} -d PARENTAL_LEVEL=1") 
    set(VITA_MKSFOEX_FLAGS "${VITA_MKSFOEX_FLAGS} -d ATTRIBUTE2=12")

    if(PS2X_VITA_CREATE_PACKAGE)
        set(PS2X_VITA_VPK_FILES "")

        foreach(PS2X_VITA_MODULE IN ITEMS
            libgpu_es4_ext.suprx
            libIMGEGL.suprx
            libGLESv2.suprx
            libpvrPSP2_WSEGL.suprx
            libGL.suprx)
            set(PS2X_VITA_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/vita/module/${PS2X_VITA_MODULE}")

            if(EXISTS "${PS2X_VITA_MODULE_PATH}")
                list(APPEND PS2X_VITA_VPK_FILES FILE "${PS2X_VITA_MODULE_PATH}" "module/${PS2X_VITA_MODULE}")
            else()
                message(WARNING
                    "Missing ${PS2X_VITA_MODULE_PATH}; the vpk will rely on ur0:data/external/ for it")
            endif()
        endforeach()

        vita_create_self(eboot.bin ps2EntryRunner UNSAFE)
        vita_create_vpk(ps2EntryRunner.vpk ${PS2X_VITA_TITLEID} eboot.bin
            VERSION ${PS2X_VITA_VERSION}
            NAME ${PS2X_VITA_APP_NAME}
            ${PS2X_VITA_VPK_FILES}
        )
    endif()
endif()

if(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
    EnableFastReleaseMode(ps2_runtime)
    EnableFastReleaseMode(ps2EntryRunner)

    if(WIN32 AND NOT PS2X_SHOW_WINDOWS_CONSOLE)
        if(MSVC)
            target_link_options(ps2EntryRunner PRIVATE
                $<$<OR:$<CONFIG:Release>,$<CONFIG:RelWithDebInfo>>:/SUBSYSTEM:WINDOWS>
                $<$<OR:$<CONFIG:Release>,$<CONFIG:RelWithDebInfo>>:/ENTRY:mainCRTStartup>
            )
        elseif(MINGW)
            target_link_options(ps2EntryRunner PRIVATE
                $<$<OR:$<CONFIG:Release>,$<CONFIG:RelWithDebInfo>>:-mwindows>
            )
        endif()
    endif()
endif()

# Work around WinAPI vs raylib symbol clash for CloseWindow on x64
if(MSVC)
    target_link_options(ps2EntryRunner PRIVATE "/FORCE:MULTIPLE")
endif()

# Vita: Work around for GCC 10's LTO plugin
if(PS2X_IS_VITA)
    target_link_options(ps2EntryRunner PRIVATE "-Wl,--allow-multiple-definition")
    target_sources(ps2EntryRunner PRIVATE src/lib/ps2_vita_runtime.cpp)
    set_source_files_properties(src/lib/ps2_vita_runtime.cpp PROPERTIES
        SKIP_UNITY_BUILD_INCLUSION TRUE
        COMPILE_OPTIONS "-fno-lto"
    )
endif()

if(PS2X_IS_ANDROID)
    target_sources(ps2EntryRunner PRIVATE src/lib/ps2_android_runtime.cpp)
endif()

install(TARGETS ps2_runtime ps2EntryRunner
    RUNTIME DESTINATION bin
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)

if(WIN32 AND PS2X_ENABLE_FFMPEG)
    install(DIRECTORY "${FFMPEG_BIN_DIR}/"
        DESTINATION bin
        FILES_MATCHING
        PATTERN "*.dll"
    )
endif()

install(DIRECTORY include/
    DESTINATION include
)

include(CheckIPOSupported)

check_ipo_supported(RESULT IPO_SUPPORTED OUTPUT IPO_ERROR)

# LODESTONE PATCH 2 — make the fast-release flag set compiler-aware.
#
# Upstream guarded this whole block with if(MSVC), which is TRUE for clang-cl
# because clang-cl advertises itself as an MSVC-compatible driver. clang-cl then
# rejects the MSVC-only options:
#
#   clang-cl: error: no such file or directory: '/Qspectre-';
#                          did you mean '/Qspectre'?
#   /arch:AVX2   MSVC only; clang uses -mavx2
#   /GS-         MSVC only; clang has no equivalent (and no need)
#   /Qspectre-   MSVC only
#
# This blocks the toolchain that every project document recommends. The Agent
# SKILL says clang-cl + Ninja takes a full rebuild from 20-30h to ~1h — but
# upstream cannot actually be configured with clang-cl until this is fixed.
# Recorded as dead_ends.jsonl#0044.
#
# If you are reading this and considering upstream clang-cl builds: the ~1h
# figure is real, but it is not reachable from a clean checkout without this
# patch.

function(_lodestone_is_msvc_only CompilerId CompilerVersion)
    if(CompilerId STREQUAL "MSVC")
        set(_out TRUE PARENT_SCOPE)
    else()
        set(_out FALSE PARENT_SCOPE)
    endif()
endfunction()

function(EnableFastReleaseMode TargetName)
    message("> Enabling optimization for: ${TargetName}")

    if(MSVC)
        # Options every MSVC-compatible driver understands.
        target_compile_options(${TargetName} PRIVATE
            $<$<CONFIG:Release>:
                /O2     # speed
                /Ob2    # inline aggressively
                /Oi     # intrinsics
                /EHsc   # C++ exceptions ON (see below)
                /Gy     # function-level linking
                /Gw     # global data in COMDAT
                /GF     # string pooling
                /Zc:inline # remove unreferenced inline
                /fp:fast  # fast math (graphics friendly)
                /DNDEBUG
            >
        )

        # LODESTONE: MSVC_VERSION is defined for clang-cl too (it targets the
        # MSVC ABI), so it cannot be used to test for the real MSVC driver.
        # CMAKE_CXX_COMPILER_ID is the only reliable discriminator.
        if(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
            target_compile_options(${TargetName} PRIVATE
                $<$<CONFIG:Release>:/GS- /GL>)
            target_link_options(${TargetName} PRIVATE $<$<CONFIG:Release>:/LTCG>)

            if(MSVC_VERSION LESS 1938)
                # /Qspectre- does not exist before VS 2022 17.8.
                target_compile_options(${TargetName} PRIVATE
                    $<$<CONFIG:Release>:/arch:AVX2>)
            else()
                target_compile_options(${TargetName} PRIVATE
                    $<$<CONFIG:Release>:/arch:AVX2 /Qspectre->)
            endif()
        endif()

        if(TARGET ${TargetName})
            target_link_options(${TargetName} PRIVATE
                $<$<CONFIG:Release>:
                    /OPT:REF # remove unreferenced
                    /OPT:ICF # fold identical COMDATs
                >
            )
        endif()
    endif()

    # clang-cl (and clang) equivalents. AVX2 stays opt-in rather than forced:
    # the generated code must also build for hosts without AVX2, so the runtime
    # is compiled portable and the -mavx2 knob is applied per-file where it
    # actually helps (see knowledge/PS2_REFERENCE.md for the SSE4.1 requirement,
    # which IS mandatory because ps2_runtime_macros.h uses SSE4.1 intrinsics).
    if(CMAKE_CXX_COMPILER_ID MATCHES "Clang" AND NOT MSVC)
        target_compile_options(${TargetName} PRIVATE
            $<$<CONFIG:Release>:
                -ffp-contract=fast
                -fno-math-errno
            >
        )
    endif()

    if(IPO_SUPPORTED)
        set_property(TARGET ${TargetName} PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
    else()
        message(WARNING "Interprocedural optimization not supported: ${IPO_ERROR}")
    endif()
endfunction()

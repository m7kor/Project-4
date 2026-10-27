@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
"cmake" "-S" "D:\Project\compatbilty\lab\zmbor-phase2\src" "-B" "D:\Project\compatbilty\lab\zmbor-phase2\build" "-G" "Ninja" "-DCMAKE_BUILD_TYPE=Release" "-DPS2X_BUILD_STUDIO=OFF" "-DPS2X_ENABLE_SCCACHE=OFF" "-DPS2X_ENABLE_FFMPEG=OFF" "-DFETCHCONTENT_FULLY_DISCONNECTED=ON" "-DFETCHCONTENT_SOURCE_DIR_ELFIO=D:\Project\compatbilty\lab\zmbor-phase2\deps\elfio" "-DFETCHCONTENT_SOURCE_DIR_FMT=D:\Project\compatbilty\lab\zmbor-phase2\deps\fmt" "-DFETCHCONTENT_SOURCE_DIR_IMGUI=D:\Project\compatbilty\lab\zmbor-phase2\deps\imgui" "-DFETCHCONTENT_SOURCE_DIR_LIBDWARF=D:\Project\compatbilty\lab\zmbor-phase2\deps\libdwarf" "-DFETCHCONTENT_SOURCE_DIR_NLOHMANN_JSON=D:\Project\compatbilty\lab\zmbor-phase2\deps\nlohmann_json" "-DFETCHCONTENT_SOURCE_DIR_RABBITIZER=D:\Project\compatbilty\lab\zmbor-phase2\deps\rabbitizer" "-DFETCHCONTENT_SOURCE_DIR_RAYLIB=D:\Project\compatbilty\lab\zmbor-phase2\deps\raylib" "-DFETCHCONTENT_SOURCE_DIR_RLIMGUI=D:\Project\compatbilty\lab\zmbor-phase2\deps\rlimgui" "-DFETCHCONTENT_SOURCE_DIR_TOML11=D:\Project\compatbilty\lab\zmbor-phase2\deps\toml11"
if errorlevel 1 exit /b %errorlevel%
cmake --build "D:\Project\compatbilty\lab\zmbor-phase2\build" --target ps2_recomp --parallel 4

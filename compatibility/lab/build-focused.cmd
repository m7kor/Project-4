@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
cmake -S D:/Project/compatbilty/lab -B D:/Project/compatbilty/lab/gif-clang -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER="C:/Program Files/LLVM/bin/clang-cl.exe" -DCMAKE_LINKER="C:/Program Files/LLVM/bin/lld-link.exe"
if errorlevel 1 exit /b %errorlevel%
cmake --build D:/Project/compatbilty/lab/gif-clang
if errorlevel 1 exit /b %errorlevel%
ctest --test-dir D:/Project/compatbilty/lab/gif-clang --output-on-failure

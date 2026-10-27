@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
cd /d D:\Project\compatbilty\artifacts\experiments\vu-queue-allocation\selector
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /std:c++20 /O2 /EHsc selector.cpp /Foselector.obj /Feselector.exe
if errorlevel 1 exit /b %errorlevel%
selector.exe

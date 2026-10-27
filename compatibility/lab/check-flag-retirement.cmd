@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
cd /d D:\Project\compatbilty\artifacts\experiments\vu-flag-coalescing\retirement-witness
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /std:c++20 /O2 /EHsc witness.cpp /Fowitness.obj /Fewitness.exe
if errorlevel 1 exit /b %errorlevel%
witness.exe

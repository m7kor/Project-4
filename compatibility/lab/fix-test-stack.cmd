@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
editbin /STACK:8388608 D:\Project\compatbilty\lab\native-link\ps2x_tests_before.exe D:\Project\compatbilty\lab\native-link\ps2x_tests_after.exe

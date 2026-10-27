@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
"C:\Users\KH\AppData\Local\Programs\Python\Python312\python.exe" D:/Project/compatbilty/tools/rebuild_hardware_phase2.py

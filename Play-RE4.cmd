@echo off
setlocal
pushd "%~dp0"
if not exist "Resident Evil 4\Play.cmd" (
    echo The Resident Evil 4 native folder has not been packaged yet.
    popd
    exit /b 1
)
set "PS2X_IOP_SIO2_NATIVE=1"
set "PS2X_IOP_SPU2_NATIVE=1"
rem Normal play uses the automatically detected physical controller.
rem Integration-test input and diagnostic selections are process-local only.
set "PS2X_NATIVE_PAD_REPLAY="
set "PS2X_IOP_RPC_CAPTURE="
set "PS2X_TRACE_NATIVE_RPC_SID="
set "PS2X_TRACE_IOP_PC="
call "Resident Evil 4\Play.cmd"
set "RE4_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %RE4_EXIT_CODE%

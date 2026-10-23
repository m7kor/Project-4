@echo off
setlocal
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\audio\record_game_audio.ps1" %*
set "AUDIO_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%AUDIO_EXIT_CODE%"=="0" pause
exit /b %AUDIO_EXIT_CODE%

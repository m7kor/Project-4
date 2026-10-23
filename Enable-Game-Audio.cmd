@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\audio\enable_game_audio.ps1"
exit /b %errorlevel%

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$taskOut = Join-Path $taskRoot 'artifacts\tools'
New-Item -ItemType Directory -Force $taskOut | Out-Null
& 'C:\Program Files\LLVM\bin\clang-cl.exe' /nologo /O2 /EHsc /std:c++20 `
    "$PSScriptRoot\enable_game_audio.cpp" /Fo"$taskOut\enable_game_audio.obj" /Fe"$taskOut\enable_game_audio.exe" `
    /link ole32.lib
if ($LASTEXITCODE -ne 0) { throw 'Game audio helper build failed' }

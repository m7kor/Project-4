param([ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$OutputName = 'capture_speakers')
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$taskOut = Join-Path $taskRoot 'artifacts\tools'
New-Item -ItemType Directory -Force $taskOut | Out-Null
& 'C:\Program Files\LLVM\bin\clang-cl.exe' /nologo /O2 /EHsc /std:c++20 `
    /I "$taskRoot\core\deps\raylib\src\external" `
    "$PSScriptRoot\capture_speakers.cpp" /Fo"$taskOut\$OutputName.obj" /Fe"$taskOut\$OutputName.exe" `
    /link ole32.lib winmm.lib
if ($LASTEXITCODE -ne 0) { throw 'Speaker capture build failed' }
Write-Output "Built $taskOut\$OutputName.exe"

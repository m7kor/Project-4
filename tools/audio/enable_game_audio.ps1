$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$helper = Join-Path $taskRoot 'artifacts\tools\enable_game_audio.exe'
if (-not (Test-Path -LiteralPath $helper)) { & "$PSScriptRoot\build_enable_game_audio.ps1" }
foreach ($relative in @('Resident Evil 4\Resident Evil 4.exe', 'core\out\build\ps2xRuntime\ps2EntryRunner.exe')) {
    & $helper (Join-Path $taskRoot $relative)
    if ($LASTEXITCODE -eq 3) { Write-Host "No matching audio session: $relative" }
    elseif ($LASTEXITCODE -ne 0) { throw "Cannot enable game audio: $relative" }
}
Write-Host 'Game sessions checked. Speaker and other app levels were preserved.'

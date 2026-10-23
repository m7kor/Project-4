param([ValidateRange(1,3600)][int]$Seconds = 60, [int]$Device = -1)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$captureTool = Join-Path $taskRoot 'artifacts\tools\capture_speakers.exe'
if (-not (Test-Path -LiteralPath $captureTool)) { & "$PSScriptRoot\build_capture_speakers.ps1" }
$taskName = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$recordingDir = Join-Path $taskRoot "artifacts\audio-check\$taskName"
New-Item -ItemType Directory -Path $recordingDir | Out-Null
$playbackInspector = Join-Path $taskRoot 'artifacts\tools\inspect_playback.exe'
if (Test-Path -LiteralPath $playbackInspector) {
    $gameProcessIds = @(Get-Process -Name 'ps2EntryRunner','Resident Evil 4' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $playbackLines = @(& $playbackInspector --seconds 1 2>&1)
    $playbackLines | Set-Content -LiteralPath (Join-Path $recordingDir 'playback-state.log')
    foreach ($playbackLine in $playbackLines) {
        if ("$playbackLine" -match 'Session pid=(\d+) state=1 volume=([0-9.]+) mute=(\d+)') {
            $sessionPid = [int]$Matches[1]
            $sessionLevel = [double]::Parse($Matches[2], [System.Globalization.CultureInfo]::InvariantCulture)
            $sessionMuted = $Matches[3] -eq '1'
            if ($gameProcessIds -contains $sessionPid -and ($sessionMuted -or $sessionLevel -eq 0)) {
                Write-Warning 'The game is muted or its Windows app volume is zero. Check the game in the Windows volume mixer.'
            }
        }
    }
}
$captureArgs = @('--out', (Join-Path $recordingDir 'heard.wav'), '--seconds', "$Seconds")
if ($Device -ge 0) { $captureArgs += @('--device', "$Device") }
Write-Host 'Play the affected game cutscene now. Recording the speaker output; no microphone.'
& $captureTool @captureArgs 2>&1 | Tee-Object -FilePath (Join-Path $recordingDir 'capture.log')
if ($LASTEXITCODE -ne 0) { throw "Capture failed. See $recordingDir\capture.log" }
& python "$taskRoot\tools\diagnostics\audio_check.py" (Join-Path $recordingDir 'heard.wav') --out (Join-Path $recordingDir 'report.json')
if ($LASTEXITCODE -ne 0) { throw 'Audio inspection failed' }
$audioReport = Get-Content -LiteralPath (Join-Path $recordingDir 'report.json') -Raw | ConvertFrom-Json
if ($audioReport.recordings.single.digital_silence) {
    Write-Warning 'The recording is entirely silent. Check game mute and the playback output. This recording cannot validate game sound.'
}
Write-Host "Listen to the exact recording and inspect the report: $recordingDir\report.html"
Invoke-Item -LiteralPath (Join-Path $recordingDir 'report.html')

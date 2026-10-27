# Builds tools/audio/audio_lab.cpp with SoundTouch (PCSX2's vendored copy,
# LGPL-2.1) into artifacts/tools/audio_lab.exe. Needs LLVM (clang-cl).
$ErrorActionPreference = 'Stop'
$root = Resolve-Path "$PSScriptRoot\..\.."
$st = "$root\dependencies\pcsx2\3rdparty\soundtouch"
$out = "$root\artifacts\tools"
New-Item -ItemType Directory -Force $out | Out-Null
$sources = 'AAFilter', 'FIFOSampleBuffer', 'FIRFilter', 'InterpolateCubic', 'InterpolateLinear', 'InterpolateShannon',
    'PeakFinder', 'RateTransposer', 'SoundTouch', 'TDStretch', 'cpu_detect_x86', 'mmx_optimized', 'sse_optimized' |
    ForEach-Object { "$st\source\SoundTouch\$_.cpp" }
& "C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /O2 /EHsc /std:c++17 /fp:fast -Wno-deprecated-declarations `
    /DSOUNDTOUCH_FLOAT_SAMPLES /DST_NO_EXCEPTION_HANDLING /I "$st\soundtouch" `
    "$root\tools\audio\audio_lab.cpp" @sources /Fo"$out\\" /Fe"$out\audio_lab.exe"
if ($LASTEXITCODE -ne 0) { throw "audio_lab build failed" }
Write-Output "built $out\audio_lab.exe"

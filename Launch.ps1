$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath) -or !(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'dist/index.html')) -or !(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'tools/rtxio/bin/RtxIoResourceExtractor.exe'))) {
    & (Join-Path $PSScriptRoot 'Setup.ps1')
}
& $pythonPath (Join-Path $PSScriptRoot 'launch.py')
exit $LASTEXITCODE

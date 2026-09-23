$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is required to create the app environment.' }
}
& .venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
if (!(Test-Path -LiteralPath 'tools/rtxio/bin/RtxIoResourceExtractor.exe')) {
    $downloadPath = Join-Path $PSScriptRoot 'tools/rtxio.7z'
    New-Item -ItemType Directory -Force 'tools/rtxio' | Out-Null
    Invoke-WebRequest 'https://d1oqksizpb0e3d.cloudfront.net/rtx-remix-rtxio@7.7z' -OutFile $downloadPath
    $actualHash = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash
    if ($actualHash -ne '83103CB2EE14A65702DCB3FBDC238C26C685E89F3C00C5A98D6CE7095EBFA785') { throw 'RTX IO package checksum mismatch.' }
    tar -xf $downloadPath -C tools/rtxio
    if ($LASTEXITCODE -ne 0) { throw 'RTX IO extraction failed.' }
    Remove-Item -LiteralPath $downloadPath
}
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Web dependency installation failed.' }
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Web app build failed.' }
Write-Host 'Setup complete. Open Launch.cmd to start the asset browser.'

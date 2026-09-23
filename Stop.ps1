$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'data/server.pid'
if (!(Test-Path -LiteralPath $pidFile)) { Write-Host 'No launched service is recorded.'; exit 0 }
$serviceId = [int](Get-Content -LiteralPath $pidFile)
$service = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId"
$expectedPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($service -and $service.ExecutablePath -eq $expectedPython -and $service.CommandLine -match 'uvicorn server.app:app') {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $serviceId"
    foreach ($child in $children) {
        if ($child.CommandLine -match 'uvicorn server.app:app') {
            $workers = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($child.ProcessId)"
            foreach ($worker in $workers) {
                if ($worker.CommandLine -like "*$PSScriptRoot*") { Stop-Process -Id $worker.ProcessId -ErrorAction SilentlyContinue }
            }
            Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        }
    }
    Stop-Process -Id $serviceId -ErrorAction SilentlyContinue
    Write-Host 'Asset browser stopped.'
}
Remove-Item -LiteralPath $pidFile

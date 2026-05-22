#Requires -RunAsAdministrator

param(
    [string]$NssmDir = "$PSScriptRoot\nssm",
    [string]$ServiceName = "agenteum-net"
)

$NssmExe = Join-Path $NssmDir "nssm.exe"
if (-not (Test-Path $NssmExe)) {
    $NssmExe = "nssm"
}

Stop-Service $ServiceName -ErrorAction SilentlyContinue
& $NssmExe remove $ServiceName confirm
Write-Host "Service '$ServiceName' removed."

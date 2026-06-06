#Requires -RunAsAdministrator

param(
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot | Split-Path -Parent),
    [string]$NssmDir = "$PSScriptRoot\nssm",
    [string]$ServiceName = "agenteum-net"
)

$ErrorActionPreference = "Stop"

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$LogDir = Join-Path $ProjectDir ".logs"
$OutLog = Join-Path $LogDir "agenteum-net.out.log"
$ErrLog = Join-Path $LogDir "agenteum-net.err.log"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual env not found at: $VenvPython. Run 'uv sync' first."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$NssmExe = Join-Path $NssmDir "nssm.exe"
if (-not (Test-Path $NssmExe)) {
    Write-Host "Downloading NSSM..."
    $NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
    $ZipPath = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri $NssmUrl -OutFile $ZipPath
    Expand-Archive -Path $ZipPath -DestinationPath $NssmDir -Force
    $Found = Get-ChildItem -Path $NssmDir -Recurse -Filter "nssm.exe" | Select-Object -First 1
    if (-not $Found) { Write-Error "Failed to find nssm.exe after download" }
    $NssmExe = $Found.FullName
}

& $NssmExe remove $ServiceName confirm 2>$null

& $NssmExe install $ServiceName $VenvPython
& $NssmExe set $ServiceName AppDirectory $ProjectDir
& $NssmExe set $ServiceName AppParameters "-c `"from src.app import main; main()`""
& $NssmExe set $ServiceName DisplayName "Agenteum Net MCP Server"
& $NssmExe set $ServiceName Description "HTTP-only MCP server for web search and fetch providers"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout $OutLog
& $NssmExe set $ServiceName AppStderr $ErrLog
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760

Start-Service $ServiceName
Write-Host "Service '$ServiceName' installed and started."
Write-Host "Logs: $LogDir"

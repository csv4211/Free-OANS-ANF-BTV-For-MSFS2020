# Copy built EXE to server/updates and print STOCK_EXE_HASH.
# Run from client/ after .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$exe = Join-Path $PSScriptRoot "dist\AmdbOansClient.exe"
if (-not (Test-Path $exe)) { throw "Build first: .\build.ps1  (missing $exe)" }

$updates = Join-Path (Split-Path $PSScriptRoot -Parent) "server\updates"
New-Item -ItemType Directory -Force -Path $updates | Out-Null
$dest = Join-Path $updates "AmdbOansClient.exe"
Copy-Item -Force $exe $dest

$hash = (Get-FileHash -Algorithm SHA256 $dest).Hash.ToLower()
Write-Host "Published: $dest"
Write-Host "STOCK_EXE_HASH=$hash"
Write-Host "Set the same hash + REQUIRED_CLIENT_VERSION in server/embedded.py, then restart server."
Write-Host "If the origin runs on another PC, copy $dest there into its updates/ folder."

# Build AmdbOansClient.exe — run from client/ folder
# Edit embedded.py (SERVER_BASE_URL etc.) before building.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -q pyinstaller SimConnect cryptography

python -m PyInstaller `
  --noconfirm `
  --clean `
  --name AmdbOansClient `
  --windowed `
  --onefile `
  --paths "." `
  --add-data "web;web" `
  --hidden-import SimConnect `
  --hidden-import cryptography `
  --collect-all SimConnect `
  .\run_client.py

$exe = Join-Path $PSScriptRoot "dist\AmdbOansClient.exe"
if (-not (Test-Path $exe)) { throw "EXE not found: $exe" }

# Append uncompressed device slot at EOF (PyInstaller compresses strings inside; trailer stays patchable)
$prefix = "AMDB_DEVSEC_SLOT_v1="
$slot = $prefix + ("0" * 64)
$bytes = [System.IO.File]::ReadAllBytes($exe)
$ascii = [System.Text.Encoding]::ASCII
$prefBytes = $ascii.GetBytes($prefix)
$found = $false
for ($i = $bytes.Length - $prefBytes.Length; $i -ge 0; $i--) {
  $ok = $true
  for ($j = 0; $j -lt $prefBytes.Length; $j++) {
    if ($bytes[$i + $j] -ne $prefBytes[$j]) { $ok = $false; break }
  }
  if ($ok) { $found = $true; break }
}
if (-not $found) {
  $tail = $ascii.GetBytes($slot)
  $out = New-Object byte[] ($bytes.Length + $tail.Length)
  [Array]::Copy($bytes, 0, $out, 0, $bytes.Length)
  [Array]::Copy($tail, 0, $out, $bytes.Length, $tail.Length)
  [System.IO.File]::WriteAllBytes($exe, $out)
  Write-Host "Appended device slot trailer ($($tail.Length) bytes)"
} else {
  Write-Host "Device slot already present in EXE"
}

$hash = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLower()
Write-Host "Built: $exe"
Write-Host "STOCK_EXE_HASH=$hash"
Write-Host "1) Paste hash into server/embedded.py STOCK_EXE_HASH"
Write-Host "2) Set REQUIRED_CLIENT_VERSION = client CLIENT_VERSION"
Write-Host "3) Copy EXE to server/updates/AmdbOansClient.exe"
Write-Host "4) Restart server (or POST /admin/reload)"

# Build AmdbOansClient.exe + AmdbOansUpdater.exe + AmdbOansUnregister.exe (+ Inno Setup).
# Edit embedded.py before building.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$verLine = (Select-String -Path .\embedded.py -Pattern '^\s*CLIENT_VERSION\s*=' | Select-Object -First 1).Line
$ver = "1.0.0"
if ($verLine -match '"([^"]+)"') { $ver = $Matches[1] }
$parts = @($ver -split '\.')
while ($parts.Count -lt 4) { $parts += '0' }
$v0 = [int]$parts[0]; $v1 = [int]$parts[1]; $v2 = [int]$parts[2]; $v3 = [int]$parts[3]

function Write-VersionInfo([string]$OutPath, [string]$FileDescription, [string]$InternalName, [string]$OriginalFilename) {
  $vi = @"
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($v0, $v1, $v2, $v3),
    prodvers=($v0, $v1, $v2, $v3),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'Free OANS AMDB'),
            StringStruct(u'FileDescription', u'$FileDescription'),
            StringStruct(u'FileVersion', u'$ver'),
            StringStruct(u'InternalName', u'$InternalName'),
            StringStruct(u'LegalCopyright', u'Copyright (c) Free OANS AMDB'),
            StringStruct(u'OriginalFilename', u'$OriginalFilename'),
            StringStruct(u'ProductName', u'AMDB OANS'),
            StringStruct(u'ProductVersion', u'$ver'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@
  [System.IO.File]::WriteAllText($OutPath, $vi, [System.Text.UTF8Encoding]::new($false))
}

Write-VersionInfo (Join-Path $PSScriptRoot 'version_info.txt') 'AMDB OANS Client' 'AmdbOansClient' 'AmdbOansClient.exe'
Write-VersionInfo (Join-Path $PSScriptRoot 'version_info_updater.txt') 'AMDB OANS Updater' 'AmdbOansUpdater' 'AmdbOansUpdater.exe'
Write-VersionInfo (Join-Path $PSScriptRoot 'version_info_unregister.txt') 'AMDB OANS Unregister' 'AmdbOansUnregister' 'AmdbOansUnregister.exe'

$issPath = Join-Path $PSScriptRoot 'installer.iss'
$iss = [System.IO.File]::ReadAllText($issPath)
$iss = [regex]::Replace($iss, '#define MyAppVersion "[\d.]+"', "#define MyAppVersion `"$ver`"")
[System.IO.File]::WriteAllText($issPath, $iss, [System.Text.UTF8Encoding]::new($false))

python -m pip install -q pyinstaller SimConnect cryptography
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

function Append-DeviceSlot([string]$ExePath) {
  $prefix = "AMDB_DEVSEC_SLOT_v1="
  $slot = $prefix + ("0" * 64)
  $bytes = [System.IO.File]::ReadAllBytes($ExePath)
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
    [System.IO.File]::WriteAllBytes($ExePath, $out)
    Write-Host "Appended device slot trailer to $(Split-Path $ExePath -Leaf)"
  }
}

# --- Main client ---
python -m PyInstaller `
  --noconfirm `
  --clean `
  --name AmdbOansClient `
  --windowed `
  --onefile `
  --version-file version_info.txt `
  --paths "." `
  --add-data "web;web" `
  --hidden-import SimConnect `
  --hidden-import cryptography `
  --collect-all SimConnect `
  .\run_client.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller client failed" }

$exe = Join-Path $PSScriptRoot "dist\AmdbOansClient.exe"
if (-not (Test-Path $exe)) { throw "EXE not found: $exe" }
Append-DeviceSlot $exe

# --- Updater (no SimConnect / web) ---
python -m PyInstaller `
  --noconfirm `
  --clean `
  --name AmdbOansUpdater `
  --windowed `
  --onefile `
  --version-file version_info_updater.txt `
  --paths "." `
  .\run_updater.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller updater failed" }

$upd = Join-Path $PSScriptRoot "dist\AmdbOansUpdater.exe"
if (-not (Test-Path $upd)) { throw "Updater EXE not found: $upd" }

# --- Unregister (local Cred Manager wipe only; no server delete) ---
python -m PyInstaller `
  --noconfirm `
  --clean `
  --name AmdbOansUnregister `
  --windowed `
  --onefile `
  --version-file version_info_unregister.txt `
  --paths "." `
  --hidden-import cryptography `
  .\run_unregister.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller unregister failed" }

$unreg = Join-Path $PSScriptRoot "dist\AmdbOansUnregister.exe"
if (-not (Test-Path $unreg)) { throw "Unregister EXE not found: $unreg" }

$hash = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLower()
Write-Host "Built: $exe"
Write-Host "Built: $upd"
Write-Host "Built: $unreg"
Write-Host "STOCK_EXE_HASH=$hash"
Write-Host "VERSION=$ver"

$pf86 = ${env:ProgramFiles(x86)}
$candidates = @(
  (Join-Path $env:LocalAppData 'Programs\Inno Setup 6\ISCC.exe'),
  (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
)
if ($pf86) { $candidates += (Join-Path $pf86 'Inno Setup 6\ISCC.exe') }
$iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($iscc) {
  Write-Host "Compiling installer with: $iscc"
  & $iscc .\installer.iss
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }
  $setup = Join-Path $PSScriptRoot "dist\AMDB-OANS-Setup-$ver.exe"
  if (-not (Test-Path $setup)) { throw "Installer not created: $setup" }
  Write-Host "Installer: $setup"
  Write-Host 'GitHub Releases: publish Setup.  server/updates/: AmdbOansClient.exe only.'
} else {
  Write-Host 'Inno Setup not found - skipped installer. Install from https://jrsoftware.org/isinfo.php'
}

Write-Host '1) Paste hash into server/embedded.py STOCK_EXE_HASH'
Write-Host "2) Set REQUIRED_CLIENT_VERSION = $ver"
Write-Host '3) Copy AmdbOansClient.exe to server/updates/'
Write-Host '4) Restart server (or POST /admin/reload)'

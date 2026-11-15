# Build AmdbOansClient.exe (+ optional Inno Setup installer like AMDB-Bridge-Setup).
# Edit embedded.py before building.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Sync VERSIONINFO from embedded.CLIENT_VERSION
$verLine = (Select-String -Path .\embedded.py -Pattern '^\s*CLIENT_VERSION\s*=' | Select-Object -First 1).Line
$ver = "1.0.0"
if ($verLine -match '"([^"]+)"') { $ver = $Matches[1] }
$parts = @($ver -split '\.')
while ($parts.Count -lt 4) { $parts += '0' }
$v0 = [int]$parts[0]; $v1 = [int]$parts[1]; $v2 = [int]$parts[2]; $v3 = [int]$parts[3]

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
            StringStruct(u'FileDescription', u'AMDB OANS Client'),
            StringStruct(u'FileVersion', u'$ver'),
            StringStruct(u'InternalName', u'AmdbOansClient'),
            StringStruct(u'LegalCopyright', u'Copyright (c) Free OANS AMDB'),
            StringStruct(u'OriginalFilename', u'AmdbOansClient.exe'),
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
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'version_info.txt'), $vi, [System.Text.UTF8Encoding]::new($false))

# Keep installer version in sync
$issPath = Join-Path $PSScriptRoot 'installer.iss'
$iss = [System.IO.File]::ReadAllText($issPath)
$iss = [regex]::Replace($iss, '#define MyAppVersion "[\d.]+"', "#define MyAppVersion `"$ver`"")
[System.IO.File]::WriteAllText($issPath, $iss, [System.Text.UTF8Encoding]::new($false))

python -m pip install -q pyinstaller SimConnect cryptography
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

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
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

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
Write-Host "VERSION=$ver"

# Optional: Inno Setup wrapper (same idea as AMDB-Bridge-Setup-*.exe)
$pf86 = ${env:ProgramFiles(x86)}
$candidates = @(
  (Join-Path $env:LocalAppData 'Programs\Inno Setup 6\ISCC.exe'),
  (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
)
if ($pf86) { $candidates += (Join-Path $pf86 'Inno Setup 6\ISCC.exe') }
$iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($iscc) {
  & $iscc .\installer.iss
  $setup = Join-Path $PSScriptRoot "dist\AMDB-OANS-Setup-$ver.exe"
  if (Test-Path $setup) {
    Write-Host "Installer: $setup"
    Write-Host 'Publish the Setup EXE on GitHub Releases (better AV reputation).'
    Write-Host 'Keep AmdbOansClient.exe for server/updates/ auto-update.'
  }
} else {
  Write-Host 'Inno Setup not found - skipped installer. Install from https://jrsoftware.org/isinfo.php then re-run.'
}

Write-Host '1) Paste hash into server/embedded.py STOCK_EXE_HASH'
Write-Host "2) Set REQUIRED_CLIENT_VERSION = $ver"
Write-Host '3) Copy AmdbOansClient.exe to server/updates/'
Write-Host '4) Restart server (or POST /admin/reload)'

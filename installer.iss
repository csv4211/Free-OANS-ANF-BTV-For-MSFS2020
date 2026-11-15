; Inno Setup — installs client + separate updater next to it.
; Requires Inno Setup 6: https://jrsoftware.org/isinfo.php

#define MyAppName "AMDB OANS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Free OANS AMDB"
#define MyAppExeName "AmdbOansClient.exe"
#define MyUpdaterExeName "AmdbOansUpdater.exe"
#define MyUnregisterExeName "AmdbOansUnregister.exe"

[Setup]
AppId={{8F3C2A91-6B4E-4D2F-9A1C-A1B2C3D4E5F6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=AMDB-OANS-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=AMDB OANS Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyUpdaterExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyUnregisterExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Unregister this PC"; Filename: "{app}\{#MyUnregisterExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#MyUnregisterExeName}"; Parameters: "--silent"; RunOnceId: "ClearLocalReg"; Flags: runhidden waituntilterminated

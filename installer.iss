; ============================================================================
;  Superfast Download Manager — Inno Setup installer script
;  Developer: Samir Uddin Ahmed
;
;  Build the distributable setup .exe:
;    1) Build the app first (one-dir build — required by this installer):
;         pyinstaller superfast-onedir.spec --clean --noconfirm
;       That produces:  dist\onedir\SuperfastDownloadManager\
;    2) Compile this script:
;         "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;       Output:  installer_output\SuperfastDownloadManager-Setup-2.0.0.exe
; ============================================================================

#define MyAppName "Superfast Download Manager"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Samir Uddin Ahmed"
#define MyAppExeName "SuperfastDownloadManager.exe"
; Folder produced by the PyInstaller one-dir build:
#define MyAppSrcDir "dist\onedir\SuperfastDownloadManager"

[Setup]
; A stable unique ID for this application (keeps upgrades/uninstall clean).
AppId={{8F3C6B21-2E4D-4A9C-9C1B-5D2A7E6F1A34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Install per-user by default so no admin rights are required; switch to
; "admin" + {autopf} if you prefer an all-users install.
PrivilegesRequiredOverridesAllowed=dialog commandline
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=SuperfastDownloadManager-Setup-{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "launchatstartup"; Description: "Start {#MyAppName} when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Recursively bundle the entire one-dir build output (exe + _internal + assets).
Source: "{#MyAppSrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Optional "launch at startup" entry (added only if the task is selected).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: launchatstartup

[Run]
; Offer to launch the app when the installer finishes.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up per-user app data on uninstall (config + download history DB).
; The app stores these under the user's home: ~/.superfast-dm
Type: filesandordirs; Name: "{%USERPROFILE}\.superfast-dm"

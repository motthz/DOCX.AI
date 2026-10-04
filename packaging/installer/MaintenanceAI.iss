; MaintenanceAI - script Inno Setup 6
; Compilato da scripts\build_installer.ps1 (richiede dist\MaintenanceAI\ gia' buildato).
;
; - Installazione per l'utente corrente SENZA diritti di amministratore
;   (%LOCALAPPDATA%\Programs\MaintenanceAI); a scelta per tutti gli utenti.
; - Crea il collegamento sul Desktop e nel menu Start, con l'icona dell'app.
; - Disinstallazione da "App installate"; i dati utente in
;   %LOCALAPPDATA%\MaintenanceAI NON vengono cancellati.

#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#define AppName "MaintenanceAI"
#define AppExe "MaintenanceAI.exe"
#define Root "..\.."

[Setup]
AppId={{6F1C2B7E-3D4A-4E8B-9C21-5A7D3E9B4F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=MaintenanceAI
AppPublisherURL=https://github.com/motthz/MaintenanceAI
AppSupportURL=https://github.com/motthz/MaintenanceAI/issues
AppUpdatesURL=https://github.com/motthz/MaintenanceAI/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Root}\release
OutputBaseFilename=MaintenanceAI-Setup-{#AppVersion}
SetupIconFile={#Root}\src\maintenance_ai\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Root}\dist\MaintenanceAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; rimuove i file della versione precedente (es. librerie non piu' usate)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

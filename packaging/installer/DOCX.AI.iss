; DOCX.AI - script Inno Setup 6
; Compilato da scripts\build_installer.ps1 (richiede dist\DOCX.AI\ gia' buildato).
;
; - Installazione per l'utente corrente SENZA diritti di amministratore
;   (%LOCALAPPDATA%\Programs\DOCX.AI); a scelta per tutti gli utenti.
; - Crea il collegamento sul Desktop e nel menu Start, con l'icona dell'app.
; - Disinstallazione da "App installate"; i dati utente in
;   %LOCALAPPDATA%\DOCX.AI NON vengono cancellati.

#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif
#define AppName "DOCX.AI"
#define AppExe "DOCX.AI.exe"
#define Root "..\.."

[Setup]
AppId={{8CEE9891-576B-4EE1-A65E-41EF747F18CA}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=DOCX.AI
AppPublisherURL=https://github.com/motthz/DOCX.AI
AppSupportURL=https://github.com/motthz/DOCX.AI/issues
AppUpdatesURL=https://github.com/motthz/DOCX.AI/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Root}\release
OutputBaseFilename=DOCX.AI-Setup-{#AppVersion}
SetupIconFile={#Root}\src\docx_ai\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
DisableWelcomePage=no
LicenseFile={#Root}\LICENSE
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

[CustomMessages]
it.WelcomeLabel2=Questa procedura installerà [name/ver] sul computer.%n%nDOCX.AI compila i rapporti di manutenzione con un'intelligenza artificiale che funziona interamente sul tuo PC: nessun dato viene inviato in Internet.%n%nNon servono diritti di amministratore.
en.WelcomeLabel2=This will install [name/ver] on your computer.%n%nDOCX.AI fills in maintenance reports with an AI that runs entirely on your PC: no data is sent to the Internet.%n%nNo administrator rights are required.
it.AiPageTitle=Intelligenza artificiale locale
en.AiPageTitle=Local artificial intelligence
it.AiPageDesc=Scegli il modello AI da scaricare al primo avvio (una sola volta).
en.AiPageDesc=Choose the AI model to download on first launch (only once).
it.AiPageSub=Il modello viene scaricato da Internet al primo avvio dell'app e poi funziona offline. Potrai cambiarlo in seguito da Impostazioni → Componenti AI.
en.AiPageSub=The model is downloaded on the app's first launch and then works offline. You can change it later in Settings → AI components.
it.AiOpt0=Automatico - il modello più preciso che il PC regge (consigliato)
en.AiOpt0=Automatic - the most accurate model this PC can run (recommended)
it.AiOpt1=Qwen3 4B Instruct - il più preciso, per PC recenti o con scheda video (circa 2,5 GB)
en.AiOpt1=Qwen3 4B Instruct - the most accurate, for recent PCs or PCs with a graphics card (about 2.5 GB)
it.AiOpt2=Qwen3 1.7B - veloce, per PC datati (circa 1,1 GB, servono almeno 4 GB di RAM)
en.AiOpt2=Qwen3 1.7B - fast, for older PCs (about 1.1 GB, needs at least 4 GB RAM)
it.AiOpt3=Qwen3 0.6B - solo per PC con meno di 4 GB di RAM, poco preciso (circa 640 MB)
en.AiOpt3=Qwen3 0.6B - only for PCs with less than 4 GB RAM, less accurate (about 640 MB)
it.AiOpt4=Non ora: deciderò in seguito
en.AiOpt4=Not now: I will decide later

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Root}\dist\DOCX.AI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; rimuove i file della versione precedente (es. librerie non piu' usate)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; aggiornamento automatico dall'app (/SILENT /RELAUNCH=1): riapre DOCX.AI a fine installazione
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchRequested

[Code]
const
  { AppId della versione precedente (MaintenanceAI 0.1-0.3) }
  LegacyKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F1C2B7E-3D4A-4E8B-9C21-5A7D3E9B4F10}_is1';

function LegacyUninstaller(): String;
var
  S: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, LegacyKey, 'UninstallString', S) or
     RegQueryStringValue(HKLM, LegacyKey, 'UninstallString', S) then
    Result := RemoveQuotes(S);
end;

function RelaunchRequested(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Uninst: String;
  Code: Integer;
begin
  { MaintenanceAI ora si chiama DOCX.AI: rimuove la vecchia installazione (i dati
    utente restano e vengono spostati dall'app al primo avvio) }
  Result := '';
  Uninst := LegacyUninstaller();
  if (Uninst <> '') and FileExists(Uninst) then
    Exec(Uninst, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

var
  AiPage: TInputOptionWizardPage;

procedure InitializeWizard();
var
  Param: String;
begin
  AiPage := CreateInputOptionPage(wpSelectTasks, CustomMessage('AiPageTitle'), CustomMessage('AiPageDesc'),
    CustomMessage('AiPageSub'), True, False);
  AiPage.Add(CustomMessage('AiOpt0'));
  AiPage.Add(CustomMessage('AiOpt1'));
  AiPage.Add(CustomMessage('AiOpt2'));
  AiPage.Add(CustomMessage('AiOpt3'));
  AiPage.Add(CustomMessage('AiOpt4'));
  Param := Lowercase(ExpandConstant('{param:AIMODEL|auto}'));
  if Param = '4b' then AiPage.SelectedValueIndex := 1
  else if Param = '1.7b' then AiPage.SelectedValueIndex := 2
  else if Param = '0.6b' then AiPage.SelectedValueIndex := 3
  else if Param = 'none' then AiPage.SelectedValueIndex := 4
  else AiPage.SelectedValueIndex := 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Model, Dir: String;
begin
  if CurStep = ssPostInstall then
  begin
    case AiPage.SelectedValueIndex of
      0: Model := 'auto';
      1: Model := 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf';
      2: Model := 'Qwen3-1.7B-Q4_K_M.gguf';
      3: Model := 'Qwen3-0.6B-Q8_0.gguf';
    else
      Model := '';
    end;
    if Model <> '' then
    begin
      Dir := ExpandConstant('{localappdata}\DOCX.AI');
      ForceDirectories(Dir);
      SaveStringToFile(Dir + '\ai_request.json', '{"model": "' + Model + '"}', False);
    end;
  end;
end;

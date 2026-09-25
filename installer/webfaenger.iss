; Installer für Webfänger (Inno Setup 6).
; build.ps1 ruft ihn auf:  ISCC /DAppVersion=1.0.0 installer\webfaenger.iss
;
; Installiert nur für den aktuellen Benutzer, ohne Administratorrechte, nach
; %LOCALAPPDATA%\Programs\Webfaenger. Fehlt die Edge-WebView2-Laufzeit (ältere
; Windows-10-Rechner), lädt der Installer sie von Microsoft nach.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Webfänger"
#define AppExe "Webfaenger.exe"
#define RepoUrl "https://github.com/phuelsebus/webfaenger"

[Setup]
AppId={{8C1F3E2A-5B7D-4E61-9A3C-2F4D6B8E0A17}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Pascal Hülsebus
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
DefaultDirName={autopf}\Webfaenger
DefaultGroupName={#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=Webfaenger-Setup-{#AppVersion}
SetupIconFile=..\webfaenger\assets\icon.ico
WizardSmallImageFile=..\webfaenger\assets\icon.png
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSizePercent=110
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
ShowLanguageDialog=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Webfaenger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Reste einer älteren Version entfernen, bevor die neue kopiert wird
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2Url = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  WebView2Client = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Setup = 'MicrosoftEdgeWebview2Setup.exe';

var
  DownloadPage: TDownloadWizardPage;

function HasVersion(RootKey: Integer; SubKey: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2Installed: Boolean;
begin
  Result := HasVersion(HKLM, 'SOFTWARE\WOW6432Node\' + WebView2Client)
    or HasVersion(HKLM, 'SOFTWARE\' + WebView2Client)
    or HasVersion(HKCU, 'Software\' + WebView2Client);
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and not WebView2Installed then begin
    DownloadPage.Clear;
    DownloadPage.Add(WebView2Url, WebView2Setup, '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        MsgBox('Die Microsoft Edge WebView2-Laufzeit konnte nicht geladen werden. ' +
               'Webfänger wird trotzdem installiert; die Laufzeit gibt es kostenlos unter ' +
               WebView2Url, mbInformation, MB_OK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Installer: String;
begin
  Installer := ExpandConstant('{tmp}\' + WebView2Setup);
  if (CurStep = ssPostInstall) and not WebView2Installed and FileExists(Installer) then begin
    WizardForm.StatusLabel.Caption := 'Microsoft Edge WebView2 wird installiert …';
    Exec(Installer, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

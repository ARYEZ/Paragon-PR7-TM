; Paragon PR7-TM installer (Inno Setup 6): a terminal, the way Windows Terminal and PuTTY work.
;   iscc /DAppVersion=0.1.0 installer\pr7tm.iss      (after pyinstaller pr7tm.spec has made dist\PR7-TM)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-TM, with a Start menu entry. Nothing is registered;
; saved sessions and known host keys stay in %APPDATA%\Paragon\PR7-TM after an uninstall (they're the user's).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{1B3CDC35-2FB9-49F0-A5F3-7211F808AF28}
AppName=Paragon PR7-TM
AppVersion={#AppVersion}
AppVerName=Paragon PR7-TM {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-TM
DefaultGroupName=Paragon PR7-TM
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-TM-Setup-{#AppVersion}
SetupIconFile=..\pr7tm\icons\app.ico
UninstallDisplayIcon={app}\PR7-TM.exe
UninstallDisplayName=Paragon PR7-TM
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-TM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-TM"; Filename: "{app}\PR7-TM.exe"; Comment: "Terminal"
Name: "{autodesktop}\Paragon PR7-TM"; Filename: "{app}\PR7-TM.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-TM.exe"; Description: "{cm:LaunchProgram,Paragon PR7-TM}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-TM again when done.
Filename: "{app}\PR7-TM.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;

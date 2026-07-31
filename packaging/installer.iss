; Inno Setup script for Dubai Estate Windows installer.
; Produces DubaiEstate-Setup-<version>.exe.
;
; Build (on Windows, after PyInstaller has created dist/DubaiEstate.exe):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
;
; Or let GitHub Actions do it (.github/workflows/build-windows.yml) — the
; workflow installs Inno Setup and runs this script automatically.

#define MyAppName        "Dubai Estate Analytics"
#define MyAppVersion     "1.0.0"
#define MyAppPublisher   "DeLemon Studio"
#define MyAppExeName     "DubaiEstate.exe"
#define MyAppURL         "https://delemonstudio.com"

[Setup]
AppId={{8F3C2A1B-4D5E-6F70-8190-DUBAIESTATE001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=DubaiEstate-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
; Per-user install (no admin needed) — pairs with APPDATA settings location.
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=app.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional shortcuts:"

[Files]
; The PyInstaller-built single exe.
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Microsoft Edge WebView2 Evergreen bootstrapper — only run if the runtime is
; missing on an older Windows install. Download once and place beside the .iss:
; https://go.microsoft.com/fwlink/p/?LinkId=2124703  (MicrosoftEdgeWebView2RuntimeInstallerX64.exe)
; Source: "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; (Optional) install WebView2 runtime silently if bundled above.
; Filename: "{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/silent /install"; Check: NeedWebView2; StatusMsg: "Installing WebView2 runtime…"
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Dubai Estate Analytics"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Keep user settings (.ai.env lives in %APPDATA%\DubaiEstate, NOT here, so it
; survives uninstall — only remove program files).
Type: filesandordirs; Name: "{app}"

[Code]
function NeedWebView2(): Boolean;
var
  Version: String;
begin
  // Returns True if WebView2 isn't registered. Win10/11 usually has it.
  Result := not RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

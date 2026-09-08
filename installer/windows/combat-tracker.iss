; Inno Setup script for the D&D Combat Tracker Windows installer.
;
; Built by package_WIN.sh (and by .github/workflows/release.yml) from the tree
; package_WIN.sh has already staged, so the installer and the .zip ship byte
; identical builds -- the installer is a different way to deliver the same
; files, not a second build.
;
;   iscc /DAppVersion=0.5.1 /DStageDir=..\..\package_win\combat-tracker-0.5.1-windows-x64 \
;        /DOutputDir=..\..\dist installer\windows\combat-tracker.iss
;
; Requires Inno Setup 6.3 or newer (for ArchitecturesAllowed=x64compatible).
;
; WHY AN INSTALLER AT ALL: the .zip asked the user to "unpack it somewhere
; permanent" and then to run combat-tracker.exe rather than the very similarly
; named combat_tracker.exe one directory down. Both are choices no one should
; have to make to run a program, and getting either wrong silently costs them
; in-app updating.

#ifndef AppVersion
  #error AppVersion must be passed with /DAppVersion=<version>
#endif
#ifndef StageDir
  #error StageDir must be passed with /DStageDir=<staged tree>
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

#define AppName "Combat Tracker"
#define AppPublisher "Mason Hyde"
#define AppURL "https://github.com/mhyde777/dnd_app"
; The launcher, never the app binary under versions\. See install_layout.py.
#define LauncherExe "combat-tracker.exe"

[Setup]
; Never change AppId: it is how Windows recognises an existing install as the
; same program. A new one turns every upgrade into a second entry in Add/Remove
; Programs, both pointing at the same directory.
AppId={{B8FF9A0E-B6A7-4875-B818-67F0475BF17E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases/latest
VersionInfoVersion={#AppVersion}

; Per-user install, and the reason for it: PrivilegesRequired=lowest means
; Windows never shows a UAC prompt. An elevation dialog on an unsigned binary
; reads as malware to exactly the person this installer exists for, and a
; single-user desktop app has no business writing to Program Files anyway.
; It also keeps the install root user-writable, which is what lets Help ->
; Check for Updates install a new version (install_layout.can_self_update).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\combat-tracker
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; The default location is right for virtually everyone, but someone with a
; small C: drive can still change it -- "auto" shows the page only when the
; install is not a straightforward first one.
DisableDirPage=auto
DisableReadyPage=no
AllowNoIcons=yes

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir={#OutputDir}
OutputBaseFilename=combat-tracker-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\images\d20_icon.ico
UninstallDisplayIcon={app}\{#LauncherExe}
UninstallDisplayName={#AppName}

; Restart Manager: if the app is running, offer to close it rather than failing
; partway through. Windows holds a running .exe and its loaded DLLs open, so a
; copy over a live install stops halfway and leaves a broken version directory.
CloseApplications=yes
RestartApplications=no
SetupMutex=CombatTrackerSetupMutex

; Code signing is wired but inactive: pass /DSign to enable it once a
; certificate exists. Defining the SignTool only when asked keeps an unsigned
; build from failing on a missing tool, so adding a certificate later is a
; command-line flag rather than a change to this file.
#ifdef Sign
SignTool=combattracker
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; The whole staged tree: the launcher, versions\<ver>\ and current. Laid out
; exactly as the .zip is, because the layout is what the updater and the
; launcher both depend on.
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Shortcuts point at the launcher and never into versions\ -- that indirection
; is what lets an update swap the version underneath a shortcut that keeps
; working. It also means the user never has to know the distinction exists.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#LauncherExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#LauncherExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#LauncherExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Self-update writes versions\<newer>\, rewrites current, and leaves
; launcher.log and launching behind -- none of which the installer put there,
; so none of which Inno would remove on its own. Without this an uninstall
; leaves most of a working install on disk.
;
; This is scoped to {app} and deliberately stops there: user data lives in
; %USERPROFILE%\.dnd_tracker_config and is never touched by an uninstall.
Type: filesandordirs; Name: "{app}\versions"
Type: files; Name: "{app}\current"
Type: files; Name: "{app}\launching"
Type: files; Name: "{app}\launcher.log"
Type: dirifempty; Name: "{app}"

[Code]
// A pre-0.5.x install was a flat folder: combat_tracker.exe and _internal\ at
// the root, with no launcher and no versions\. Upgrading in place would leave
// that stale binary sitting beside the new launcher, and any old shortcut
// would go on starting it -- a copy that runs but can never update itself.
procedure RemoveLegacyFlatInstall();
begin
  if FileExists(ExpandConstant('{app}\combat_tracker.exe')) then
  begin
    DeleteFile(ExpandConstant('{app}\combat_tracker.exe'));
    DelTree(ExpandConstant('{app}\_internal'), True, True, True);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    RemoveLegacyFlatInstall();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox('Combat Tracker has been removed.' + #13#10 + #13#10 +
           'Your encounters, characters and settings were left in place, in' + #13#10 +
           ExpandConstant('{%USERPROFILE}\.dnd_tracker_config') + #13#10 + #13#10 +
           'Delete that folder if you want to remove them too.',
           mbInformation, MB_OK);
end;

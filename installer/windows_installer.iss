; Inno Setup script for YouTube Video Downloader
; -----------------------------------------------------------------------------
; Packages the PyInstaller *onedir* output
;   dist\windows\YouTubeVideoDownloader\  (YouTubeVideoDownloader.exe + _internal\)
; into a single per-user installer: YouTubeVideoDownloader-Setup.exe
;
; The installer copies the app (including the _internal folder) into a real
; install directory and creates Start Menu + optional Desktop shortcuts, so the
; user launches from a shortcut and never sees _internal. This also avoids the
; "run the exe from inside the zip" trap that makes Windows extract a broken
; partial copy to %TEMP% (the "Failed to load Python DLL python312.dll" error).
;
; Compiled in CI (from the repo root) with the version defined on the command
; line:
;   ISCC /DMyAppVersion=0.2.6 installer\windows_installer.iss
; -----------------------------------------------------------------------------

#define MyAppName "YouTube Video Downloader"
#define MyAppPublisher "NuthanReddy"
#define MyAppURL "https://github.com/NuthanReddy/YoutubeVideoDownloader"
#define MyAppExeName "YouTubeVideoDownloader.exe"
; Source folder (relative to this .iss file, which lives in installer\).
#define MySourceDir "..\dist\windows\YouTubeVideoDownloader"

; Version is normally injected with /DMyAppVersion=... ; fall back for local runs.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
; A stable AppId keeps upgrades/uninstall tied to the same product across versions.
AppId={{A7F3C2E1-9B4D-4E6A-8C1F-2D5B7E9A3C64}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
; Per-user install => no UAC prompt. {autopf} maps to %LocalAppData%\Programs
; and {autoprograms}/{autodesktop} map to the per-user locations in this mode.
PrivilegesRequired=lowest
DefaultDirName={autopf}\YouTubeVideoDownloader
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist\installer
OutputBaseFilename=YouTubeVideoDownloader-Setup
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy the entire onedir bundle (exe + _internal\ with python312.dll, ffmpeg, etc.).
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Inno Setup script: wraps the PyInstaller folder into Trapster-Setup.exe
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6C1E2B7A-3F0D-4C55-9C3E-CA77E7A0A1B2}
AppName=Trapster
AppVersion={#AppVersion}
AppPublisher=Wildsolutions
DefaultDirName={localappdata}\Programs\Trapster
DefaultGroupName=Trapster
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=Trapster-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\app.ico
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Trapster

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\Trapster\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Trapster"; Filename: "{app}\Trapster.exe"
Name: "{autodesktop}\Trapster"; Filename: "{app}\Trapster.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Trapster.exe"; Description: "Start Trapster"; Flags: nowait postinstall skipifsilent

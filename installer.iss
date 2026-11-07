; Inno Setup script: wraps the PyInstaller folder into CameraTrapTool-Setup.exe
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6C1E2B7A-3F0D-4C55-9C3E-CA77E7A0A1B2}
AppName=Camera Trap Tool
AppVersion={#AppVersion}
AppPublisher=Wild Solutions
DefaultDirName={localappdata}\Programs\CameraTrapTool
DefaultGroupName=Camera Trap Tool
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=CameraTrapTool-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Camera Trap Tool

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\CameraTrapTool\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Camera Trap Tool"; Filename: "{app}\CameraTrapTool.exe"
Name: "{autodesktop}\Camera Trap Tool"; Filename: "{app}\CameraTrapTool.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CameraTrapTool.exe"; Description: "Start Camera Trap Tool"; Flags: nowait postinstall skipifsilent

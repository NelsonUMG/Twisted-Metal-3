#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\build\payload"
#endif
[Setup]
AppId={{ACE478C4-FB66-4C51-A67A-C1E83B43174E}
AppName=TM3 Online
AppVersion={#AppVersion}
AppPublisher=NelsonUMG
AppPublisherURL=https://github.com/NelsonUMG/Twisted-Metal-3
DefaultDirName={localappdata}\Programs\TM3Online
DefaultGroupName=TM3 Online
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=TM3Online-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter=TM3Lobby.exe,TM3Online.exe
RestartApplications=no
UninstallDisplayIcon={app}\TM3Lobby.exe
SetupLogging=yes
[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "TM3Console.ini"
Source: "..\config\TM3Console.example.ini"; DestDir: "{app}\runtime"; DestName: "TM3Console.ini"; Flags: onlyifdoesntexist uninsneveruninstall
[Icons]
Name: "{group}\TM3 Online"; Filename: "{app}\TM3Lobby.exe"
Name: "{userdesktop}\TM3 Online"; Filename: "{app}\TM3Lobby.exe"
[Run]
Filename: "{app}\TM3Lobby.exe"; Description: "Abrir TM3 Online"; Flags: nowait postinstall skipifsilent

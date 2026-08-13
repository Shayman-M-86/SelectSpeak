#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef AppNumericVersion
  #define AppNumericVersion "0.1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\SelectSpeak"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef SetupIcon
  #define SetupIcon "..\build\packaging\SelectSpeak.ico"
#endif

[Setup]
AppId={{A441CF57-CAEC-4C75-9E64-90EB3F806014}
AppName=SelectSpeak
AppVersion={#AppVersion}
AppVerName=SelectSpeak {#AppVersion}
AppPublisher=SelectSpeak Project
AppPublisherURL=https://github.com/Shayman-M-86/my-TTS
AppSupportURL=https://github.com/Shayman-M-86/my-TTS/issues
AppUpdatesURL=https://github.com/Shayman-M-86/my-TTS/releases
AppMutex=Local\SelectSpeak
SetupMutex=Local\SelectSpeakSetup-A441CF57-CAEC-4C75-9E64-90EB3F806014
DefaultDirName={localappdata}\Programs\SelectSpeak
DefaultGroupName=SelectSpeak
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=SelectSpeak-Setup-{#AppVersion}
SetupIconFile={#SetupIcon}
UninstallDisplayIcon={app}\SelectSpeak.exe
UninstallDisplayName=SelectSpeak {#AppVersion}
VersionInfoVersion={#AppNumericVersion}
VersionInfoCompany=SelectSpeak Project
VersionInfoDescription=SelectSpeak installer
VersionInfoProductName=SelectSpeak
VersionInfoProductVersion={#AppVersion}
VersionInfoOriginalFileName=SelectSpeak-Setup-{#AppVersion}.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
AllowNoIcons=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=SelectSpeak.exe
ChangesAssociations=no
ChangesEnvironment=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start SelectSpeak when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{app}\SelectSpeak.exe"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\native"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SelectSpeak\SelectSpeak"; Filename: "{app}\SelectSpeak.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\SelectSpeak\Uninstall SelectSpeak"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SelectSpeak"; Filename: "{app}\SelectSpeak.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\SelectSpeak"; Filename: "{app}\SelectSpeak.exe"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\SelectSpeak.exe"; Description: "Launch SelectSpeak"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

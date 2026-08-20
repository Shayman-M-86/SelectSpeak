#ifndef AppVersion
  #define AppVersion "0.1.2"
#endif
#ifndef AppNumericVersion
  #define AppNumericVersion "0.1.2.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\SelectSpeak"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif
#ifndef SetupIcon
  #define SetupIcon "..\..\.build\packaging\SelectSpeak.ico"
#endif
#ifndef InstallerInfo
  #define InstallerInfo "..\..\docs\INSTALLATION_NOTICE.txt"
#endif
#ifndef NuGetExe
  #error NuGetExe must point to the pinned NuGet command-line executable
#endif
#ifndef RuntimeInstaller
  #error RuntimeInstaller must point to install_speech_runtime.ps1
#endif
#ifndef PlayerRuntimeInstaller
  #error PlayerRuntimeInstaller must point to install_player_runtime.ps1
#endif
#ifndef RuntimePackages
  #error RuntimePackages must point to the Natural Voice packages.config
#endif
#ifndef SupertonicInstaller
  #error SupertonicInstaller must point to install_supertonic_payload.ps1
#endif
#ifndef SupertonicLayerUrl
  #error SupertonicLayerUrl must identify the optional dependency archive
#endif
#ifndef SupertonicLayerVersion
  #error SupertonicLayerVersion must identify the dependency-layer format
#endif
#ifndef SupertonicModelRevision
  #error SupertonicModelRevision must identify the pinned model snapshot
#endif
#ifndef SupertonicLayerSha256
  #error SupertonicLayerSha256 must contain the dependency archive SHA-256
#endif
#ifndef SupertonicLayerFileName
  #error SupertonicLayerFileName must identify the local dependency archive
#endif
#ifndef SupertonicModelUrl
  #error SupertonicModelUrl must identify the pinned model archive
#endif
#ifndef SupertonicModelSha256
  #error SupertonicModelSha256 must contain the model archive SHA-256
#endif
#ifndef SupertonicModelFileName
  #error SupertonicModelFileName must identify the local model archive
#endif
#ifdef EmbedSupertonicPayload
  #ifndef SupertonicLayerArchive
    #error SupertonicLayerArchive is required for an embedded payload
  #endif
  #ifndef SupertonicModelArchive
    #error SupertonicModelArchive is required for an embedded payload
  #endif
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
InfoBeforeFile={#InstallerInfo}
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
UsePreviousSetupType=yes
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=SelectSpeak.exe
ChangesAssociations=no
ChangesEnvironment=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "standard"; Description: "Standard installation"
Name: "full"; Description: "Full installation with Supertonic"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "supertonic"; Description: "Supertonic Neural Voice (approximately 475 MB including model)"; Types: full; ExtraDiskSpaceRequired: 524288000

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start SelectSpeak when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[Registry]
Root: HKCU; Subkey: "Software\SelectSpeak"; ValueType: string; ValueName: "InstallerPath"; ValueData: "{srcexe}"; Flags: uninsdeletekey

[InstallDelete]
Type: files; Name: "{app}\SelectSpeak.exe"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\native"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#NuGetExe}"; Flags: dontcopy
Source: "{#RuntimeInstaller}"; Flags: dontcopy
Source: "{#PlayerRuntimeInstaller}"; Flags: dontcopy
Source: "{#RuntimePackages}"; Flags: dontcopy
Source: "{#SupertonicInstaller}"; DestName: "install_supertonic_payload.ps1"; Flags: dontcopy; Components: supertonic
#ifdef EmbedSupertonicPayload
Source: "{#SupertonicLayerArchive}"; DestName: "supertonic-dependencies.zip"; Flags: dontcopy; Components: supertonic
Source: "{#SupertonicModelArchive}"; DestName: "supertonic-model.zip"; Flags: dontcopy; Components: supertonic
#endif

[UninstallDelete]
Type: filesandordirs; Name: "{app}\dependencies\supertonic"

[Icons]
Name: "{autoprograms}\SelectSpeak\SelectSpeak"; Filename: "{app}\SelectSpeak.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\SelectSpeak\Uninstall SelectSpeak"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SelectSpeak"; Filename: "{app}\SelectSpeak.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\SelectSpeak"; Filename: "{app}\SelectSpeak.exe"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\SelectSpeak.exe"; Description: "Launch SelectSpeak"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
var
  SupertonicLayerArchivePath: String;
  SupertonicModelArchivePath: String;

function OnSupertonicDownloadProgress(
  const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then
  begin
    WizardForm.StatusLabel.Caption := Format(
      'Downloading %s... %d%%', [FileName, (Progress * 100) div ProgressMax]);
    WizardForm.ProgressGauge.Max := ProgressMax;
    WizardForm.ProgressGauge.Position := Progress;
  end
  else
    WizardForm.StatusLabel.Caption := 'Downloading ' + FileName + '...';
  Result := True;
end;

function SupertonicLayerInstalled: Boolean;
var
  Manifest: AnsiString;
begin
  Result :=
    FileExists(ExpandConstant('{app}\dependencies\supertonic\supertonic-layer.json')) and
    FileExists(ExpandConstant('{app}\dependencies\supertonic\supertonic\__init__.py')) and
    FileExists(ExpandConstant('{app}\dependencies\supertonic\numpy\__init__.py')) and
    FileExists(ExpandConstant('{app}\dependencies\supertonic\onnxruntime\__init__.py'));
  if Result then
  begin
    Result := LoadStringFromFile(
      ExpandConstant('{app}\dependencies\supertonic\supertonic-layer.json'), Manifest) and
      (Pos('"layer_version": "{#SupertonicLayerVersion}"', Manifest) > 0);
  end;
end;

function SupertonicModelInstalled: Boolean;
var
  Manifest: AnsiString;
  ManifestPath: String;
begin
  Result :=
    FileExists(ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3\onnx\tts.json')) and
    FileExists(ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3\onnx\unicode_indexer.json')) and
    FileExists(ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3\onnx\duration_predictor.onnx')) and
    FileExists(ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3\onnx\text_encoder.onnx')) and
    FileExists(ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3\onnx\vector_estimator.onnx')) and
    FileExists(ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3\onnx\vocoder.onnx')) and
    FileExists(ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3\voice_styles\F4.json'));
  ManifestPath := ExpandConstant(
    '{localappdata}\SelectSpeak\models\supertonic3\supertonic-model.json');
  if Result and FileExists(ManifestPath) then
  begin
    Result := LoadStringFromFile(ManifestPath, Manifest) and
      (Pos('"revision": "{#SupertonicModelRevision}"', Manifest) > 0);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  LocalArchive: String;
begin
  Result := '';
  SupertonicLayerArchivePath := '';
  SupertonicModelArchivePath := '';
  if not WizardIsComponentSelected('supertonic') then
    exit;

  try
    if not SupertonicLayerInstalled then
    begin
#ifdef EmbedSupertonicPayload
      SupertonicLayerArchivePath := ExpandConstant('{tmp}\supertonic-dependencies.zip');
#else
      LocalArchive := AddBackslash(ExtractFileDir(ExpandConstant('{srcexe}'))) +
        '{#SupertonicLayerFileName}';
      if FileExists(LocalArchive) and
         (CompareText(GetSHA256OfFile(LocalArchive), '{#SupertonicLayerSha256}') = 0) then
        SupertonicLayerArchivePath := LocalArchive
      else
      begin
        WizardForm.StatusLabel.Caption := 'Downloading Supertonic dependencies...';
        DownloadTemporaryFile(
          '{#SupertonicLayerUrl}',
          'supertonic-dependencies.zip',
          '{#SupertonicLayerSha256}',
          @OnSupertonicDownloadProgress);
        SupertonicLayerArchivePath := ExpandConstant('{tmp}\supertonic-dependencies.zip');
      end;
#endif
    end;
    if not SupertonicModelInstalled then
    begin
#ifdef EmbedSupertonicPayload
      SupertonicModelArchivePath := ExpandConstant('{tmp}\supertonic-model.zip');
#else
      LocalArchive := AddBackslash(ExtractFileDir(ExpandConstant('{srcexe}'))) +
        '{#SupertonicModelFileName}';
      if FileExists(LocalArchive) and
         (CompareText(GetSHA256OfFile(LocalArchive), '{#SupertonicModelSha256}') = 0) then
        SupertonicModelArchivePath := LocalArchive
      else
      begin
        WizardForm.StatusLabel.Caption := 'Downloading the Supertonic voice model...';
        DownloadTemporaryFile(
          '{#SupertonicModelUrl}',
          'supertonic-model.zip',
          '{#SupertonicModelSha256}',
          @OnSupertonicDownloadProgress);
        SupertonicModelArchivePath := ExpandConstant('{tmp}\supertonic-model.zip');
      end;
#endif
    end;
  except
    Result := 'Supertonic could not be downloaded: ' + GetExceptionMessage;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PowerShell: String;
  Parameters: String;
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    ExtractTemporaryFile('nuget.exe');
    ExtractTemporaryFile('install_speech_runtime.ps1');
    ExtractTemporaryFile('install_player_runtime.ps1');
    ExtractTemporaryFile('packages.config');
    if WizardIsComponentSelected('supertonic') then
    begin
      ExtractTemporaryFile('install_supertonic_payload.ps1');
#ifdef EmbedSupertonicPayload
      if SupertonicLayerArchivePath <> '' then
        ExtractTemporaryFile('supertonic-dependencies.zip');
      if SupertonicModelArchivePath <> '' then
        ExtractTemporaryFile('supertonic-model.zip');
#endif
    end;
  end;

  if CurStep = ssPostInstall then
  begin
    PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');

    { The player is framework-dependent, so the Microsoft runtimes it needs are
      installed here rather than bundled. The script leaves any compatible
      version already on the machine alone, and re-checks after installing. }
    WizardForm.StatusLabel.Caption := 'Checking Microsoft player runtimes...';
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{tmp}\install_player_runtime.ps1') + '"';
    if not Exec(PowerShell, Parameters, '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode) then
      RaiseException('Could not start the player runtime installer.');
    if ResultCode <> 0 then
      RaiseException(Format(
        'The Microsoft runtimes SelectSpeak''s player needs could not be installed ' +
        '(exit code %d). Check your internet connection and run setup again, or ' +
        'install the .NET 8 Desktop Runtime and Windows App Runtime 1.8 from ' +
        'Microsoft and retry.', [ResultCode]));

    WizardForm.StatusLabel.Caption := 'Installing Microsoft Speech runtime...';
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{tmp}\install_speech_runtime.ps1') + '" -NuGetPath "' +
      ExpandConstant('{tmp}\nuget.exe') + '" -PackagesConfig "' +
      ExpandConstant('{tmp}\packages.config') + '" -Destination "' +
      ExpandConstant('{app}\native') + '"';
    if not Exec(PowerShell, Parameters, '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode) then
      RaiseException('Could not start the Natural Voice runtime installer.');
    if ResultCode <> 0 then
      RaiseException(Format(
        'Natural Voice runtime installation failed with exit code %d. ' +
        'Check your internet connection and run setup again.', [ResultCode]));

    if WizardIsComponentSelected('supertonic') and
       ((SupertonicLayerArchivePath <> '') or (SupertonicModelArchivePath <> '')) then
    begin
      WizardForm.StatusLabel.Caption := 'Installing Supertonic Neural Voice...';
      Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
        ExpandConstant('{tmp}\install_supertonic_payload.ps1') + '"';
      if SupertonicLayerArchivePath <> '' then
        Parameters := Parameters + ' -LayerArchive "' + SupertonicLayerArchivePath +
          '" -LayerDestination "' +
          ExpandConstant('{app}\dependencies\supertonic') + '"';
      if SupertonicModelArchivePath <> '' then
        Parameters := Parameters + ' -ModelArchive "' + SupertonicModelArchivePath +
          '" -ModelDestination "' +
          ExpandConstant('{localappdata}\SelectSpeak\models\supertonic3') + '"';
      if not Exec(PowerShell, Parameters, '', SW_HIDE,
        ewWaitUntilTerminated, ResultCode) then
        RaiseException('Could not start the Supertonic component installer.');
      if ResultCode <> 0 then
        RaiseException(Format(
          'Supertonic installation failed with exit code %d. Run setup again to retry.', [ResultCode]));
    end;
  end;
end;

; Inno Setup script for SurveyCleaner-Setup.exe (built by windows/build.ps1).
; Installs for the current user only: no administrator rights needed.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Survey Cleaner"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{6F1C7A52-3B8E-4F0D-9C2A-5E7B1D4A9C31}
AppName=Survey Cleaner
AppVersion={#AppVersion}
AppVerName=Survey Cleaner {#AppVersion}
AppPublisher=Alfred Kombo Emali
AppPublisherURL=https://github.com/emali-alfred/kobo-survey-cleaner
AppSupportURL=https://github.com/emali-alfred/kobo-survey-cleaner/issues
AppComments=Clean KoboToolbox and ODK survey exports and get a data quality report.
DefaultDirName={localappdata}\Programs\Survey Cleaner
DefaultGroupName=Survey Cleaner
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=SurveyCleaner-Setup-{#AppVersion}
SetupIconFile=..\surveyclean\assets\icon.ico
UninstallDisplayIcon={app}\Survey Cleaner.exe
UninstallDisplayName=Survey Cleaner
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Survey Cleaner"; Filename: "{app}\Survey Cleaner.exe"
Name: "{group}\Uninstall Survey Cleaner"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Survey Cleaner"; Filename: "{app}\Survey Cleaner.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Survey Cleaner.exe"; Description: "Open Survey Cleaner now"; Flags: nowait postinstall skipifsilent

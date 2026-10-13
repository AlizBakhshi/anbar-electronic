; نصب‌کننده‌ی «انبار الکترونیک» — با Inno Setup 6 کامپایل کنید (build.bat این کار را انجام می‌دهد).
; پیش‌نیاز: اول exe را با PyInstaller بسازید (پوشه‌ی dist\AnbarElectronic).

#define AppName "انبار الکترونیک"
#define AppVersion "1.0.2"
#define AppExe "AnbarElectronic.exe"

[Setup]
AppId={{7D3C9E2A-5B41-4F7A-9C61-2E8B1A4D6F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\AnbarElectronic
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=release
OutputBaseFilename=AnbarElectronic-Setup-{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\AnbarElectronic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "AnbarElectronic.App"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "AnbarElectronic.App"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; اطلاعات کاربر در %APPDATA%\AnbarElectronic است و با حذف برنامه پاک نمی‌شود.

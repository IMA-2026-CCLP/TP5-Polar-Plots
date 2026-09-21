; installer.iss — Instalador de Polar Pattern CCLP (Inno Setup 6).
; Se compila con build_installer.bat (que pasa /DAppVersion=<versión de app\version.py>).
; Requiere que ya exista dist\PolarPatternAnalyzer\ (build_exe.bat / PyInstaller).

#ifndef AppVersion
  #define AppVersion "5.0.0"
#endif
#define AppName "Polar Pattern CCLP"
#define AppExe  "PolarPatternAnalyzer.exe"

[Setup]
; GUID fijo: identifica la app para actualizar/desinstalar (no cambiarlo entre versiones)
AppId={{6B0F2E4A-3C1D-4E8B-9A57-2D9C4F7E1A30}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=CCLP
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Sin permisos de administrador por defecto (se instala para el usuario); el asistente permite elegir "todos los usuarios"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer_output
OutputBaseFilename=PolarPatternCCLP-Setup-{#AppVersion}
SetupIconFile=app\ui\icons\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el &escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "dist\PolarPatternAnalyzer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent

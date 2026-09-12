; HeartBeam Windows installer — Inno Setup script.
;
; Build: install Inno Setup 6 (winget install JRSoftware.InnoSetup), then
;   ISCC.exe installer\heartbeam.iss
; produces:
;   installer\Output\HeartBeam-Setup-0.1.0.exe (application and setup scripts)
;
; What this installer does on the user's machine:
;   1. Drops the HeartBeam source tree into %LOCALAPPDATA%\HeartBeam.
;   2. Runs scripts\install.ps1 from inside the install dir:
;        - winget-installs Python 3.12 if missing
;        - winget-installs ffmpeg (Gyan build, libass) if missing
;        - creates venv and pip-installs heartbeam[cpu] (or [gpu] if user opted in)
;        - optionally downloads Mesk Rifforge for the metal preset
;   3. Creates a Start Menu shortcut + (optional) Desktop shortcut pointing at
;      heartbeam-gui.exe — double-click to open the browser-based UI.
;   4. Registers an uninstaller that removes the install dir.
;
; Sizes:
;   - This installer .exe: ~5 MB (just the heartbeam source)
;   - After first-run pip install: ~700 MB on disk (CPU) or ~3 GB (GPU)
;   - After first separation run: another ~2 GB of cached models

#define MyAppName "HeartBeam"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "thevampiresocialclub"
#define MyAppURL "https://github.com/<your-github>/HeartBeam"
#define MyAppExeName "heartbeam.exe"

[Setup]
AppId={{F8E9D1A2-3C4B-5D6E-7F80-91A2B3C4D5E6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=HeartBeam-Setup-{#MyAppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "installgpu"; Description: "Force the NVIDIA GPU build (CUDA 12.8; otherwise detect automatically)"; GroupDescription: "Variant:"; Flags: unchecked
Name: "installmetal"; Description: "Also install the metal preset (Mesk Rifforge, ~2 GB)"; GroupDescription: "Optional models:"; Flags: unchecked

[Files]
; ---- HeartBeam source tree ----
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\heartbeam\*"; DestDir: "{app}\heartbeam"; Excludes: "__pycache__\*,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Excludes: "__pycache__\*,*.pyc,*.pyo"; Flags: ignoreversion recursesubdirs
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

; Note: we do NOT bundle Python. install.ps1 winget-installs Python 3.12 on the
; target machine if it's missing. That keeps this installer ~5 MB instead of 80 MB.

[Icons]
; Primary launcher — opens the GUI in the user's default browser, no console window.
Name: "{group}\HeartBeam"; \
    Filename: "{app}\.venv\Scripts\heartbeam-gui.exe"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\.venv\Scripts\heartbeam-gui.exe"; \
    Comment: "HeartBeam karaoke generator"
; Power-user CLI shortcut — opens a CMD with venv activated.
Name: "{group}\HeartBeam Console"; \
    Filename: "{cmd}"; \
    Parameters: "/k ""{app}\.venv\Scripts\activate.bat"" && echo HeartBeam venv active. Type 'heartbeam --help' to get started."
Name: "{group}\Uninstall HeartBeam"; Filename: "{uninstallexe}"
; Optional desktop icon — GUI launcher.
Name: "{userdesktop}\HeartBeam"; \
    Filename: "{app}\.venv\Scripts\heartbeam-gui.exe"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\.venv\Scripts\heartbeam-gui.exe"; \
    Comment: "HeartBeam karaoke generator"; \
    Tasks: desktopicon

[Run]
; First-run install. Do NOT re-add -SkipFfmpeg here: heartbeam/io.py shells out
; to ffmpeg to decode the *input* file, so without it every run dies on step one.
Filename: "powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\scripts\install.ps1"" -InstallDir ""{app}"""; \
  StatusMsg: "Running first-time setup (installs ffmpeg + Python deps, ~3-5 min)..."; \
  Tasks: not installgpu

Filename: "powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\scripts\install.ps1"" -InstallDir ""{app}"" -Variant GPU"; \
  StatusMsg: "Running first-time setup with GPU deps (~5-8 min)..."; \
  Tasks: installgpu

Filename: "powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -NoProfile -Command ""& '{app}\.venv\Scripts\python.exe' '{app}\scripts\install_metal_model.py'"""; \
  StatusMsg: "Downloading metal preset model (~2 GB)..."; \
  Tasks: installmetal

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\__pycache__"

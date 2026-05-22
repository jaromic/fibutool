#define MyAppName "fibutool"
#define MyAppPublisher "Jarosoft e.U."
#define MyAppURL "https://github.com/jaromic/fibutool"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\fibutool
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=fibutool-setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Main executable
Source: "..\dist\fibutool.exe"; DestDir: "{app}"; Flags: ignoreversion

; Example config — placed in %APPDATA%\fibutool\ so it is ready to rename
Source: "..\config.yaml.example"; DestDir: "{userappdata}\fibutool"; Flags: ignoreversion createallsubdirs

[Registry]
; Add install dir to user PATH
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  OrigPath, AppDir, NewPath: string;
  P: integer;
begin
  if CurUninstallStep <> usPostUninstall then exit;
  AppDir := ExpandConstant('{app}');
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then exit;
  NewPath := OrigPath;
  P := Pos(';' + AppDir, NewPath);
  if P > 0 then
    Delete(NewPath, P, Length(';' + AppDir));
  if NewPath <> OrigPath then
    RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', NewPath);
end;

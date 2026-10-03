; ClawBoard Windows 安装包脚本（Inno Setup 6）
;
; 编译方式（在项目根目录执行）：
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
; 产物：release\ClawBoard-<版本>-setup.exe
;
; 路径均相对本 .iss 文件所在目录（packaging\），因此 ..\ 指向项目根。
;
; 卸载残留说明（v1.6.1 修）：
;   1. 自启动注册表值不是用户数据，卸载后无条件删掉；
;   2. 数据文件由程序运行时生成、不在 [Files] 里，卸载不会带走 —— 这里在卸载时
;      先问一下，选「是」才连 %APPDATA%\ClawBoard 一起删，默认保留。

#define MyAppName "ClawBoard"
#define MyAppVersion "2.2.4"
#define MyAppPublisher "ClawBoard"
#define MyAppURL "https://github.com/pay-and-gain/ClawBoard"
#define MyAppExeName "ClawBoard.exe"

[Setup]
; AppId 一经发布不要再改，否则会变成"两个不同的程序"
AppId={{8A3F2B14-6C7D-4E59-9F21-3B8D5A7C4E16}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\release
OutputBaseFilename=ClawBoard-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
; 中文放第一位 = 安装向导默认中文；英文作为备选
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\ClawBoard.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\使用说明.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  WipeData: Boolean;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\ClawBoard');
    WipeData := MsgBox('要一并删除 ClawBoard 的数据吗（剪切板历史、常用语、设置）？'
                       + #13#10#13#10
                       + '选「是」：彻底清干净，卸载后不留任何痕迹。' + #13#10
                       + '选「否」：数据保留在 ' + DataDir + #13#10
                       + '　　　　　以后重装还能接着用。',
                       mbConfirmation, MB_YESNO) = IDYES;
    Exit;
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    { 自启动项是注册表垃圾，不是用户数据：无条件清掉，否则开机一直拉一个已删除的程序 }
    RegDeleteValue(HKEY_CURRENT_USER,
                   'Software\Microsoft\Windows\CurrentVersion\Run',
                   '{#MyAppName}');

    if not WipeData then
      Exit;

    { 安装到 Program Files 时程序把数据写在 %APPDATA%\ClawBoard }
    DataDir := ExpandConstant('{userappdata}\ClawBoard');
    if DirExists(DataDir) then
      DelTree(DataDir, True, True, True);

    { 以管理员身份运行时，数据也可能落在程序目录里 }
    if FileExists(ExpandConstant('{app}\ClawBoard数据.json')) then
      DeleteFile(ExpandConstant('{app}\ClawBoard数据.json'));
    if FileExists(ExpandConstant('{app}\ClawBoard数据.json.bak')) then
      DeleteFile(ExpandConstant('{app}\ClawBoard数据.json.bak'));
    if FileExists(ExpandConstant('{app}\crash.log')) then
      DeleteFile(ExpandConstant('{app}\crash.log'));

    { 万一被 UAC 重定向过，VirtualStore 里也会有一份 }
    DataDir := ExpandConstant('{localappdata}\VirtualStore\Program Files\{#MyAppName}');
    if DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
  end;
end;

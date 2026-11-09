; Mitra Home for Windows: per-user installer with its own Python. Built by installer/build_installer.py, which passes
; AppVersion, Stage (the staged app/ and runtime/ folders) and OutDir. No administrator rights, nothing system-wide.
;   code    -> {autopf}\MitraHome          (= %LOCALAPPDATA%\Programs\MitraHome; `onboard.py update` keeps working here)
;   Python  -> {localappdata}\MitraHome\runtime   (launch.py makes the private environment next to it, in ...\venv)
;   papers, settings, database -> the household folder chosen on the wizard page (default Documents\Mitra-Home-Data),
;   made by launch.py on the first start and never touched by an update or by uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Stage
  #define Stage "build\stage"
#endif
#ifndef OutDir
  #define OutDir "..\dist\installer"
#endif
#define Runtime "{localappdata}\MitraHome\runtime"
#define Py "{localappdata}\MitraHome\runtime\python.exe"
; no console window: the Start menu, the desktop icon and the start on the last page (launch.py --quiet)
#define Pyw "{localappdata}\MitraHome\runtime\pythonw.exe"

[Setup]
AppId={{8F3C2A51-6B7E-4D2A-9C1F-3E5B7A9D0C42}
AppName=Mitra Home
AppVersion={#AppVersion}
AppVerName=Mitra Home {#AppVersion}
AppPublisher=Rajesh Katukojwala
AppPublisherURL=https://rnetgit.github.io/mitra-home/
DefaultDirName={autopf}\MitraHome
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=MitraHome-Setup-{#AppVersion}
SetupIconFile=mitrahome.ico
UninstallDisplayIcon={app}\mitrahome.ico
UninstallDisplayName=Mitra Home
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
#ifdef Sign
; ISCC /Smitrasign=... (installer/build_installer.py --sign) signs the installer and the embedded uninstaller
SignTool=mitrasign
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "Put a Mitra Home icon on the desktop"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start Mitra Home by itself when I sign in to this PC, and again if it stops"; GroupDescription: "Startup:"

[Files]
Source: "{#Stage}\app\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Stage}\runtime\*"; DestDir: "{#Runtime}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "mitrahome.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; "Mitra Home" follows Settings > Phones > Connection (phones and walls on the home Wi-Fi, on by default, once an adult
; has a PIN); the second entry keeps it to this PC whatever that setting says.
Name: "{autoprograms}\Mitra Home"; Filename: "{#Pyw}"; Parameters: """{app}\launch.py"" --quiet --home ""{code:HomeDir}"""; WorkingDir: "{app}"; IconFilename: "{app}\mitrahome.ico"; Comment: "Start Mitra Home and open it in the browser (phones and walls on the home Wi-Fi too)"
Name: "{autoprograms}\Mitra Home (this PC only)"; Filename: "{#Pyw}"; Parameters: """{app}\launch.py"" --quiet --pc-only --home ""{code:HomeDir}"""; WorkingDir: "{app}"; IconFilename: "{app}\mitrahome.ico"; Comment: "Start Mitra Home for this PC only (no phones or walls)"
Name: "{autoprograms}\Mitra Home health check"; Filename: "{cmd}"; Parameters: "/k """"{#Py}"" ""{app}\onboard.py"" doctor"""; WorkingDir: "{app}"; IconFilename: "{app}\mitrahome.ico"
Name: "{autodesktop}\Mitra Home"; Filename: "{#Pyw}"; Parameters: """{app}\launch.py"" --quiet --home ""{code:HomeDir}"""; WorkingDir: "{app}"; IconFilename: "{app}\mitrahome.ico"; Tasks: desktopicon

[Run]
; the private environment and its packages now, from the shipped wheels (no download), so the first start is quick;
; if this fails the first start tries again and shows what went wrong
Filename: "{#Py}"; Parameters: """{app}\launch.py"" --prepare"; WorkingDir: "{app}"; Flags: runhidden; StatusMsg: "Preparing Mitra Home (one time, about a minute)..."
; a task that ticks every 5 minutes (first tick in 10): starts the app at sign-in and again after it stopped; launch.py
; follows the phones setting, so the task needs no --lan.
; --home so a first start by the task makes the household in the folder chosen above; nothing is written to the app folder before then.
Filename: "{#Py}"; Parameters: """{app}\data\autostart.py"" on web --no-start --home ""{code:HomeDir}"""; WorkingDir: "{app}"; Flags: runhidden; Tasks: autostart; StatusMsg: "Setting Mitra Home to start when you sign in..."
Filename: "{#Pyw}"; Parameters: """{app}\launch.py"" --quiet --home ""{code:HomeDir}"""; WorkingDir: "{app}"; Description: "Start Mitra Home now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; scheduled jobs and the phone bot's start-at-sign-in task of THIS install (others are left alone)
Filename: "{#Py}"; Parameters: """{app}\data\task_register.py"" remove"; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "RemoveTasks"
; then this install's running app: it has no window to close any more
Filename: "{#Py}"; Parameters: """{app}\launch.py"" --stop"; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "StopApp"

[UninstallDelete]
; the private environment and Python's own caches; the household folder is never listed here
Type: filesandordirs; Name: "{localappdata}\MitraHome\venv"
Type: filesandordirs; Name: "{#Runtime}"
Type: filesandordirs; Name: "{localappdata}\MitraHome\logs"

[Code]
var
  HomePage: TInputDirWizardPage;

function MarkerFile(): String;
begin
  Result := ExpandConstant('{app}\mitrahome_home.txt');
end;

{ An existing install already knows its household folder: the wizard page is skipped and the marker wins. }
function ExistingHome(): String;
var
  S: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(MarkerFile(), S) then
    Result := Trim(String(S));
end;

function HomeDir(Param: String): String;
begin
  if ExistingHome() <> '' then
    Result := ExistingHome()
  else
    Result := HomePage.Values[0];
end;

{ 1 when A > B, -1 when A < B, 0 when equal; dotted numbers such as 0.109.1 }
function CompareVersion(A, B: String): Integer;
var
  PA, PB, NA, NB: Integer;
begin
  Result := 0;
  while (Result = 0) and ((A <> '') or (B <> '')) do
  begin
    PA := Pos('.', A); PB := Pos('.', B);
    if PA = 0 then begin NA := StrToIntDef(A, 0); A := ''; end
    else begin NA := StrToIntDef(Copy(A, 1, PA - 1), 0); Delete(A, 1, PA); end;
    if PB = 0 then begin NB := StrToIntDef(B, 0); B := ''; end
    else begin NB := StrToIntDef(Copy(B, 1, PB - 1), 0); Delete(B, 1, PB); end;
    if NA > NB then Result := 1
    else if NA < NB then Result := -1;
  end;
end;

function LooksSynced(Path: String): Boolean;
begin
  Path := Lowercase(Path);
  Result := (Pos('onedrive', Path) > 0) or (Pos('dropbox', Path) > 0) or (Pos('google drive', Path) > 0);
end;

{ Documents\Mitra-Home-Data, unless Documents is redirected to OneDrive (common on Windows 11): then the user's own
  profile folder, which is never synced. /HOME="D:\Somewhere" on the command line wins. }
function DefaultHome(): String;
begin
  Result := ExpandConstant('{param:HOME|}');
  if Result = '' then
  begin
    Result := ExpandConstant('{userdocs}\Mitra-Home-Data');
    if LooksSynced(Result) then
      Result := AddBackslash(GetEnv('USERPROFILE')) + 'Mitra-Home-Data';
  end;
end;

procedure InitializeWizard();
begin
  HomePage := CreateInputDirPage(wpSelectDir, 'Household folder',
    'Where should your papers, settings and database live?',
    'Mitra Home keeps everything about your household in one folder on this PC, apart from the app, so an update ' +
    'or an uninstall never touches it.' + #13#10#13#10 +
    'Pick a folder that is NOT synced to OneDrive, Dropbox or another cloud service.',
    False, '');
  HomePage.Add('');
  HomePage.Values[0] := DefaultHome();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = HomePage.ID) and (ExistingHome() <> '');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  H, A: String;
begin
  Result := True;
  if CurPageID = HomePage.ID then
  begin
    H := Lowercase(AddBackslash(HomePage.Values[0]));
    A := Lowercase(AddBackslash(WizardDirValue()));
    if (Pos(A, H) = 1) or (Pos(H, A) = 1) then
    begin
      MsgBox('The household folder must be outside the app folder (' + WizardDirValue() + ').', mbError, MB_OK);
      Result := False;
    end
    else if LooksSynced(H) and not WizardSilent() then
      Result := MsgBox('This folder looks synced to a cloud service, so your statements, IDs and database would be ' +
        'copied off this PC. Mitra Home is meant to keep them here.' + #13#10#13#10 +
        'Use this folder anyway?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

{ This install's running app (pid in .webapp.json, written by launch.py) is stopped before its files are replaced: it
  runs with no window, so there is nothing for the family to close. Read here rather than by `launch.py --stop`,
  because the launch.py already installed may be older than that option. }
procedure StopRunningApp();
var
  S: AnsiString;
  T, Pid: String;
  P, Code: Integer;
begin
  if not LoadStringFromFile(ExpandConstant('{app}\.webapp.json'), S) then
    exit;
  T := String(S);
  P := Pos('"pid":', T);
  if P = 0 then
    exit;
  Delete(T, 1, P + 5);
  T := Trim(T);
  Pid := '';
  while (Length(T) > 0) and (T[1] >= '0') and (T[1] <= '9') do
  begin
    Pid := Pid + T[1];
    Delete(T, 1, 1);
  end;
  if Pid <> '' then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/PID ' + Pid + ' /T /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ Never put an older app over a newer one (an install updated by `onboard.py update` may be ahead of this installer). }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  S: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(ExpandConstant('{app}\VERSION'), S) then
    if CompareVersion(Trim(String(S)), '{#AppVersion}') > 0 then
      Result := 'Mitra Home ' + Trim(String(S)) + ' is already installed here, newer than this installer ({#AppVersion}). ' +
        'Nothing was changed. Use "Mitra Home health check" or Settings > Data > Updates instead.';
  if Result = '' then
    StopRunningApp();
end;

{ The last page says where everything lives (also in Settings > Data > Where things are). }
{ A folder shortened with "..." in the middle so it fits on one line of the last page (the full paths are in Settings). }
function FitPath(Path: String): String;
begin
  Result := MinimizePathName(Path, WizardForm.FinishedLabel.Font, WizardForm.FinishedLabel.Width - ScaleX(16));
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Home: String;
begin
  if CurPageID = wpFinished then
  begin
    Home := RemoveBackslash(HomeDir(''));
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
      'Mitra Home opens in your browser and runs with no window. To stop it: Settings > Data > Stop Mitra Home.' + #13#10#13#10 +
      'App:' + #13#10 + FitPath(ExpandConstant('{app}')) + #13#10 +
      'Your household (papers, settings, database):' + #13#10 + FitPath(Home) + #13#10 +
      'Backups:' + #13#10 + FitPath(ExtractFileDir(Home) + '\Mitra-Home-Backup');
    WizardForm.FinishedLabel.AdjustHeight();
    WizardForm.RunList.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + ScaleY(12);
  end;
end;

{ Remove what is left of the app folder (caches, the running-app note) only when the household clearly lives elsewhere. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App, Home: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    App := ExpandConstant('{app}');
    Home := ExistingHome();
    if (Home <> '') and not FileExists(App + '\config\family.json') and not FileExists(App + '\data\family.db') then
    begin
      DelTree(App, True, True, True);
      if not UninstallSilent() then
        MsgBox('Mitra Home was removed. Your household folder was kept:' + #13#10 + Home, mbInformation, MB_OK);
    end
    else if not UninstallSilent() then
      MsgBox('Mitra Home was removed. Household files were found in ' + App + ' and were kept.', mbInformation, MB_OK);
  end;
end;

' Runs tasks\web_app.bat with no console window and waits for it, handing its exit code back to Task Scheduler.
' Used by the web app's keep-alive task (python data/autostart.py on web [--lan] [--home FOLDER]); extra arguments go to
' the .bat; an argument with a space in it (a folder) is passed in quotes.
Dim sh, fso, bat, args, i, a
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
bat = fso.GetParentFolderName(WScript.ScriptFullName) & "\web_app.bat"
args = ""
For i = 0 To WScript.Arguments.Count - 1
  a = WScript.Arguments(i)
  If InStr(a, " ") > 0 Then a = """" & a & """"
  args = args & " " & a
Next
WScript.Quit sh.Run("""" & bat & """" & args, 0, True)

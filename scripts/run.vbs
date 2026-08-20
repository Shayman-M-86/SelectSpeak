'' Launches SelectSpeak without a visible console window.
''
'' A thin wrapper over run-dev.ps1, so double-clicking gets the same
'' rebuild-if-stale behaviour as running that script by hand. Double-click this
'' file, or point a startup shortcut at it.
Dim fso, ws, scriptDir, root, runScript, powershell, command, result
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws  = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(scriptDir)
ws.CurrentDirectory = root
runScript = scriptDir & "\run-dev.ps1"

If Not fso.FileExists(root & "\.venv\Scripts\pythonw.exe") Then
    MsgBox "SelectSpeak has not been set up yet." & vbCrLf & vbCrLf & _
        "Open PowerShell in the repository and run" & vbCrLf & _
        ".\scripts\install-dev-dependencies.ps1.", _
        vbExclamation, "SelectSpeak setup required"
    WScript.Quit 1
End If

'' -Detached so this returns once SelectSpeak is running, rather than holding a
'' hidden console open for the life of the application.
powershell = ws.ExpandEnvironmentStrings("%SystemRoot%") & _
    "\System32\WindowsPowerShell\v1.0\powershell.exe"
command = Chr(34) & powershell & Chr(34) & _
    " -NoProfile -ExecutionPolicy Bypass -File " & _
    Chr(34) & runScript & Chr(34) & " -Detached"

'' Wait for it, so a build failure can be reported rather than vanishing.
result = ws.Run(command, 0, True)
If result <> 0 Then
    MsgBox "SelectSpeak could not start." & vbCrLf & vbCrLf & _
        "Run .\scripts\run-dev.ps1 in PowerShell to see why.", _
        vbExclamation, "SelectSpeak"
    WScript.Quit result
End If

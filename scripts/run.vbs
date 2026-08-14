'' Launches SelectSpeak without a visible console window.
'' Double-click this file to run, or point a startup shortcut at it.
Dim fso, ws, scriptDir, root, pythonw, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws  = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(scriptDir)
ws.CurrentDirectory = root
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "SelectSpeak has not been installed yet." & vbCrLf & vbCrLf & _
        "Open PowerShell in the repository and run .\scripts\install.ps1.", _
        vbExclamation, "SelectSpeak setup required"
    WScript.Quit 1
End If
If Not fso.FileExists(root & "\.runtime\native\selectspeak_native.dll") Then
    MsgBox "The SelectSpeak native bridge is not built." & vbCrLf & vbCrLf & _
        "Open PowerShell in the repository and run .\scripts\install.ps1.", _
        vbExclamation, "SelectSpeak setup required"
    WScript.Quit 1
End If
command = Chr(34) & pythonw & Chr(34) & " -m selectspeak"
ws.Run command, 0, False

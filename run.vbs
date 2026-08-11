'' Launches SelectSpeak without a visible console window.
'' Double-click this file to run, or point a startup shortcut at it.
Dim fso, ws, dir, pythonw, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws  = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = dir
pythonw = dir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "SelectSpeak has not been installed yet." & vbCrLf & vbCrLf & _
        "Open PowerShell in this folder and run .\install.ps1.", _
        vbExclamation, "SelectSpeak setup required"
    WScript.Quit 1
End If
If Not fso.FileExists(dir & "\.runtime\input\selectspeak_input.dll") Then
    MsgBox "The native input bridge is not built for SelectSpeak." & vbCrLf & vbCrLf & _
        "Open PowerShell in this folder and run .\install.ps1.", _
        vbExclamation, "SelectSpeak setup required"
    WScript.Quit 1
End If
command = Chr(34) & pythonw & Chr(34) & " " & _
    Chr(34) & dir & "\main.py" & Chr(34)
ws.Run command, 0, False

'' Launches SelectSpeak without a visible console window.
'' Double-click this file to run, or point a startup shortcut at it.
Dim fso, ws, dir
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws  = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = dir
If Not fso.FileExists(dir & "\.runtime\autohotkey\AutoHotkey64.exe") Then
    MsgBox "AutoHotkey is not installed for SelectSpeak." & vbCrLf & vbCrLf & _
        "Run install_autohotkey.ps1 from PowerShell first.", _
        vbExclamation, "SelectSpeak setup required"
    WScript.Quit 1
End If
ws.Run "uv run main.py", 0, False

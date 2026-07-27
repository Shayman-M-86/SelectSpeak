'' Launches SelectSpeak without a visible console window.
'' Double-click this file to run, or point a startup shortcut at it.
Dim fso, ws, dir
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws  = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = dir
ws.Run "uv run main.py", 0, False

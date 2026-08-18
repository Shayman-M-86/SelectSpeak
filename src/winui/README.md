# WinUI 3 reader spike

A minimal slice of the SelectSpeak player rendered by WinUI 3, driven by the
existing Python backend. It exists to answer one question: can the reader and
its word highlighting live in a native Windows UI while Python keeps every
decision?

## Layout

```
Python (owns all state)
   |  newline-delimited JSON over a named pipe
   v
SelectSpeak.UI.exe (renders, reports intents)
```

- `SelectSpeak.UI/` - the WinUI 3 app. Holds no application logic.
- `../python/selectspeak/ui/winui_bridge.py` - the Python side, exposing the
  familiar `PlayerWindow` method names.
- `demo.py` - drives the slice end to end.

## Protocol

Python sends state:

```json
{"type":"set_text","text":"..."}
{"type":"highlight_word","position":143,"length":7}
{"type":"set_playback","speaking":true,"paused":false}
{"type":"set_status","text":"Reading..."}
{"type":"show"}
{"type":"hide"}
```

The UI sends intent:

```json
{"type":"read"}
{"type":"play"}
{"type":"pause"}
{"type":"resume"}
{"type":"stop"}
```

## Running

```powershell
dotnet build src/winui/SelectSpeak.UI
.venv/Scripts/python.exe src/winui/demo.py
```

`demo.py` launches the UI itself. The bridge reconnects on its own, so either
process can be restarted independently.

## Not in this slice

Tray, hotkeys, OCR, voice menu, diagnostics panel, auto-hide, fullscreen
handling, installer packaging. All of that still runs through the Tk player.

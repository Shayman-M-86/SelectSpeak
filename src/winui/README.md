# SelectSpeak player

The SelectSpeak player, rendered by WinUI 3 and driven by the Python backend.

Python owns every decision; this process draws what it is sent and reports which
button was pressed. That split is what lets the player live in another process
without the application layer knowing.

## Layout

```
Python (owns all state)
   |  newline-delimited JSON over a named pipe
   v
SelectSpeak.UI.exe (renders, reports intents)
```

- `SelectSpeak.UI/` - the WinUI 3 app. Holds no application logic.
- `../python/selectspeak/ui/winui_bridge.py` - the Python side of the pipe.
- `../python/selectspeak/ui/contracts.py` - the contract both sides satisfy.

## Protocol

Python sends state:

```json
{"type":"set_text","text":"..."}
{"type":"highlight_word","position":143,"length":7}
{"type":"set_playback","speaking":true,"paused":false}
{"type":"set_shortcut","hotkey":"Alt+S"}
{"type":"set_settings","auto_hide":true,"voices":[]}
{"type":"show"}
{"type":"hide"}
```

The UI sends intent:

```json
{"type":"toggle_playback"}
{"type":"stop"}
{"type":"settings"}
{"type":"set_hotkey","hotkey":"ctrl+shift+r"}
{"type":"select_voice","voice":"supertonic"}
```

## Building and running

Use the repository's development launcher, which builds this project and starts
the backend that drives it:

```powershell
.\scripts\run-dev.ps1
```

Build output goes to `.build/winui/`, alongside every other build artefact.

Build this project alone with:

```powershell
dotnet build src/winui/SelectSpeak.UI/SelectSpeak.UI.csproj
```

Launching `SelectSpeak.UI.exe` on its own proves the XAML parses, but shows
nothing useful: with no backend connected the reader keeps its placeholder and
the buttons have nothing to report to.

Note that `dotnet publish` is not usable here - it drops `SelectSpeak.UI.pri`
and the compiled `.xbf` files, and the resulting executable faults inside
`Microsoft.UI.Xaml.dll` on launch. `build-tools/winui/build.ps1` uses
`dotnet build` for that reason.

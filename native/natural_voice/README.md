# SelectSpeak Natural Voice bridge

This optional 64-bit DLL talks directly to Microsoft's embedded Speech SDK and
installed `MicrosoftWindows.Voice.*` packages. It contains no SAPI, COM voice
registration, Azure/Edge networking, WebSockets, proxy support, or MP3 decoder.

The C ABI discovers packages, probes the actual SDK voice name, streams raw
24 kHz/16-bit/mono PCM, emits word boundaries, and supports cancellation after
the SDK's `SynthesisStarted` event. Python owns audio playback through WinMM so
pause and resume apply to already-buffered sound.

## Build

Install Visual Studio 2022 Build Tools with **Desktop development with C++** and
CMake, then run from the repository root:

```powershell
.\native\natural_voice\build.ps1
```

If those prerequisites are not installed, the script can install the official
Build Tools package through WinGet and then continue the build:

```powershell
.\native\natural_voice\build.ps1 -InstallPrerequisites
```

The script restores the pinned Speech SDK NuGet packages and creates the local,
ignored `.runtime/natural_voice` directory. It does not bundle voice packages.
Install a Narrator Natural Voice through Windows Settings before running the app.

The Narrator integration is unofficial and may break after Windows or voice
package updates. See `THIRD_PARTY_NOTICES.md` before redistributing anything.

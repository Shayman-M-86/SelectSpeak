# SelectSpeak Natural Voice bridge

This optional 64-bit DLL talks directly to Microsoft's embedded Speech SDK and
installed `MicrosoftWindows.Voice.*` packages. It contains no SAPI, COM voice
registration, Azure/Edge networking, WebSockets, proxy support, or MP3 decoder.

The C ABI discovers packages, probes the actual SDK voice name, streams raw
24 kHz/16-bit/mono PCM, emits word boundaries, and supports cancellation after
the SDK's `SynthesisStarted` event. Python owns audio playback through WinMM so
pause and resume apply to already-buffered sound.

## Build

The recommended setup is the repository's complete installer, which provisions
the toolchain and builds this bridge along with the rest of SelectSpeak:

```powershell
.\install.ps1
```

For bridge-only development, run:

```powershell
.\native\natural_voice\build.ps1 -InstallPrerequisites
```

The script restores the pinned Speech SDK NuGet packages and creates the local,
ignored `.runtime/natural_voice` directory. It does not bundle voice packages.

To prevent Windows from updating a known-compatible package underneath the
bridge, keep the downloaded MSIX as an extracted, app-owned copy:

```powershell
.\native\natural_voice\pin_voice.ps1 -MsixPath "C:\Downloads\voice.msix"
```

Pinned packages are stored below `.runtime/natural_voice/voices` and are tried
before Windows-installed packages. The root installer accepts the same package
through `-NaturalVoiceMsix`. Neither command installs or downgrades the Windows
package.

The Narrator integration is unofficial and may break after Windows or voice
package updates. See `THIRD_PARTY_NOTICES.md` before redistributing anything.

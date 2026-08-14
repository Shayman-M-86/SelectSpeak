# SelectSpeak Natural Voice bridge

This optional module in SelectSpeak's unified 64-bit DLL talks directly to
Microsoft's embedded Speech SDK and
installed `MicrosoftWindows.Voice.*` packages. It contains no SAPI, COM voice
registration, Azure/Edge networking, WebSockets, proxy support, or MP3 decoder.

The C ABI discovers current installed packages, probes the actual SDK voice
name, streams raw 24 kHz/16-bit/mono PCM, emits word boundaries, and supports
cancellation after the SDK's `SynthesisStarted` event. It obtains the matching
credential only from the installed Windows speech runtime and keeps it in
memory. Python owns audio playback through WinMM so pause and resume apply to
already-buffered sound.

## Build

The recommended setup is the repository's complete installer, which provisions
the toolchain and builds this bridge along with the rest of SelectSpeak:

```powershell
.\install.ps1
```

For native-only development, run:

```powershell
.\native\build.ps1 -InstallPrerequisites -DevRuntime
```

The development variant restores the pinned Speech SDK NuGet packages and
creates the complete local, ignored `.runtime/native` directory. A normal native
build puts only `selectspeak_native.dll` there; the release installer uses NuGet
to place the same three required SDK DLLs beside it during installation. Neither
path downloads or bundles voice packages. The runtime is limited to Speech core,
Embedded TTS, and ONNX Runtime; unrelated audio-device, codec, KWS, LU, and
telemetry extensions are not deployed.
Natural Voice is available only when both a compatible
`MicrosoftWindows.Voice.*` package and the corresponding speech runtime are
installed through Windows.

The Narrator integration is unofficial and may break after Windows or voice
package updates. See `THIRD_PARTY_NOTICES.md` before redistributing anything.

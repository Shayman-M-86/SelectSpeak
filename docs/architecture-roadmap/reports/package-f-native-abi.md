# Package F — Native ABI

## Found

- Preflight route: **Proceed**. Native API version 6 was duplicated between
  Python and C++, while input, OCR, Natural Voice, and OCR integration tests
  independently assigned ctypes signatures to the shared DLL.
- The frozen Package C contract requires invalid or destroyed handles to remain
  safely identifiable. An opaque `uint64` token provides that property without
  exposing a freed native pointer.
- The XAudio2 engine is intentionally a Package J outcome. Package F therefore
  needed callable ABI symbols that reject requests without creating a temporary
  playback implementation or emitting accepted-request events.

## Changed

- Incremented `SELECTSPEAK_NATIVE_API_VERSION` and Python
  `NATIVE_API_VERSION` from 6 to 7.
- Added matching C++ and ctypes definitions for stable native statuses, terminal
  values, PCM16 format, request handles, boundaries, submission telemetry,
  request events, Natural synthesis results, and the request-scoped
  create/submit/finish/pause/resume/stop/destroy functions.
- Added a common Python status checker. Known failures expose their typed
  status; unknown future codes retain their numeric value and become a generic
  `NativeCallError` rather than being mistaken for success.
- `NativeBridge` now configures the bootstrap version symbols, rejects an old
  DLL with a clear version error, and then configures the complete ABI once.
  Input, OCR, Natural Voice, and tests no longer mutate SelectSpeak DLL
  signatures. Capability wrappers continue owning callback objects and their
  lifetimes.
- Added a non-accepting audio ABI stub. Valid create calls currently return
  `device_error`, expose no handle, and emit no event; all handle operations
  return `invalid_handle`. Package J replaces this source file with the real
  request-scoped XAudio2 implementation.
- Added native and Python ABI/layout/version tests, rebuilt the DLL, copied it
  to `.runtime/native`, and staged the identical allowlisted DLL plus manifest
  under `.build/staging`.

## Validation

- Warning-free native Release build and CTest: 4/4 passed (`audio_api`,
  `ocr_layout`, `selection_policy`, and `natural_voice_speech_runtime_config`).
- Focused native ABI/input/OCR/Natural suite: 19 passed, including the staged
  version-7 DLL and real generated-image OCR tests.
- Full Python suite: 157 passed in 0.34 seconds.
- Ruff and `ty check`: all checks passed.
- Built, runtime, and distribution-staged DLL SHA-256 values matched:
  `1DB93DAA27B9B16005227C01ACE2710DBB1C2FCE9D7C7C2B8A65B581B9727E2D`.
- The controlled real-device Natural workload completed playback,
  pause/resume, cancellation, and clean shutdown; stop settled `True` in
  24.163 ms. Its first attempt encountered a transient WaveOut device-open
  error; Windows reported one device and the immediate full retry passed.
- `git diff --check` passed; only Git's existing LF-to-CRLF notices were
  emitted.

## Remaining

- Package F is complete. Package G can build `PcmPlaybackSession` over these
  stable Python/native declarations without coupling backends to ctypes.
- The Package F audio stub accepts no request and is not a rollout path. Package
  J owns its replacement with persistent XAudio2 runtime and request-scoped
  source voices; Packages H and I own bounded admission and asynchronous UI
  delivery behavior.
- Existing input, OCR, and transitional Natural Voice APIs retain their
  capability-specific diagnostic text functions. The new audio ABI deliberately
  has no process-global `last_error`; accepted asynchronous failures will carry
  request-local status and copied diagnostic data when Package J implements
  sessions.

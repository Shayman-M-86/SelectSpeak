# Package G — Native PCM Session

## Found

- Preflight route: **Adapt**. The unified plan was deliberately revised before
  implementation: `PcmPlaybackSession` must target the native XAudio2 request
  path directly, existing WaveOut remains untouched legacy code, and the former
  optional G1 compatibility adapter must not exist.
- Package F supplied a complete version-7 ABI but intentionally left a
  non-accepting audio stub for Package J. Package G therefore needed a real
  Python ownership/validation seam with deterministic fake-native coverage,
  plus an integration check proving the staged stub rejects without falsely
  accepting a request.
- UTF-16 boundary validation needs the complete original request text in Python;
  a text length alone cannot detect a boundary that splits a surrogate pair.

## Changed

- Added native-only `PcmPlaybackSession`. One instance owns one immutable
  application request ID, one native handle, the complete request text, the PCM
  format, and the ctypes callback lifetime through native destroy.
- Added backend-facing PCM contracts independent of ctypes and WaveOut:
  `PcmFormat`, `PcmBoundary`, `PcmSubmitResult`, and typed started, played-word,
  underrun, and terminal events. Code-point-to-UTF-16 helpers provide the
  conversion seam required by future Supertonic integration.
- Submission copies caller PCM and boundary inputs, validates complete frames,
  nondecreasing slice-relative frame offsets, complete-request UTF-16 ranges,
  nonzero text lengths, and surrogate-pair edges before calling native. A
  successful partial native acceptance is treated as an internal contract
  failure.
- Native events are copied immediately, checked against immutable request
  identity and lifecycle order, serialized by the native contract, suppressed
  after terminal/close, and protected so Python exceptions cannot cross ctypes.
  Same-handle controls are explicitly rejected from inside the event callback.
- `finish_input`, pause, resume, terminal-reason stop, and idempotent close map
  directly to Package F functions. Submit does not hold a Python operation lock,
  leaving a separate control thread able to stop/destroy an eventually blocked
  native producer in Packages H/J.
- Removed G1 from the unified package map, deletion rule, and status ledger.
  Natural, Supertonic, and `WaveOutPlayer` were not modified or wrapped.

## Validation

- Focused PCM/native ABI suite: 18 passed, including the real staged Package F
  stub rejection with no false `started` event.
- Full Python suite: 171 passed in 0.36 seconds.
- Ruff and `ty check`: all checks passed.
- Native Release CTest: 4/4 passed (`audio_api`, `ocr_layout`,
  `selection_policy`, and `natural_voice_speech_runtime_config`).
- Controlled real-device Natural legacy workload completed playback,
  pause/resume, cancellation, and clean shutdown; stop settled `True` in
  27.886 ms.
- Controlled real-device Supertonic legacy workload completed the same
  scenarios; stop settled `True` in 6.920 ms.

## Remaining

- Package G is complete. Package H can define/tune bounded interruptible native
  admission through this synchronous `submit` seam; Package J implements the
  capacity wakeups and XAudio2 request behind it.
- Package I must establish asynchronous UI delivery before Package J emits real
  native played-word callbacks. Packages K and L later move Natural and
  Supertonic onto this session.
- The Package F stub still accepts no session, so this is not a selectable
  playback path yet. The existing WaveOut backend path remains deliberately
  separate until the native path is implemented, integrated, and proven; no G1
  adapter or dual playback abstraction should be reintroduced.

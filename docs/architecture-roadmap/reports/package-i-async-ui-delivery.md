# Package I — Asynchronous Played-Word Delivery

## Found

- Preflight route: **Proceed**. The application already validates each
  `SpeechWord` against the active request, and `WinUiPlayer.call_soon` already
  provides a thread-safe queue drained by the player main loop.
- The remaining gap was one inline call in `SelectSpeakApp._on_speech_event`:
  `highlight_word` reached `WinUiPlayer._send`, whose overlapped named-pipe
  write deliberately waits for completion. A speech/native callback could
  therefore block on UI pipe I/O.
- Playback-state and diagnostic rendering already use `call_soon`. No new
  dispatcher, pipe protocol, polling loop, or WinUI rendering change is needed.

## Changed

- Played-word handling now validates the active `request_id`, captures the
  immutable position and length, enqueues `highlight_word` through the player,
  and returns. The WinUI main loop performs the eventual named-pipe write.
- Added focused coverage proving that a valid word is not rendered inline and
  that a stale request does not add another queued UI callback.
- Kept the change limited to delivery. Pipe reads, reconnect behaviour, WinUI
  rendering, and the legacy audio paths are unchanged.

## Validation

- Focused application and WinUI bridge suites: 31 passed.
- Full Python suite: 205 passed.
- Ruff and `ty check`: all checks passed.
- `git diff --check`: passed.
- **Not exercised:** no WinUI or native build and no live named-pipe/device
  smoke. Neither C# nor C++ changed; the focused tests verify the callback-side
  non-blocking seam rather than Windows process I/O timing.

## Remaining

- Package I is complete. Package J may introduce native played-word callbacks
  through this delivery path without allowing those callbacks to perform UI
  pipe I/O.
- Broader WinUI transport cleanup remains outside the audio roadmap's critical
  path, as required by the unified plan.

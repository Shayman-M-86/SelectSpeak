# Package B — Lifecycle and Ownership

## Found

- Preflight route: **Proceed**, adapting only the wakeup mechanism to the existing
  `PlaybackController` queue. No Package C request/PCM contract was needed.
- `SelectSpeakApp` created the initial speaker, retained it as `_speaker`, then
  handed the same object to `VoiceController`; activation callbacks moved the
  app's pointer, leaving two current-speaker authorities.
- Natural, Supertonic, and SAPI workers were daemon threads with no backend
  `close()` contract, no queue shutdown signal, and no normal join path.
- Application shutdown assumed every startup attribute existed, stopped the
  native bridge before tray/player destruction, abandoned speech-wait threads,
  and was not guaranteed when setup or the UI main loop raised.
- Package A measured a 1,010.490 ms Natural `speaker.stop()` call even though
  `waveOutReset` itself took 7.074 ms. WaveOut was waiting for cleanup before the
  native synthesis call was cancelled.

## Changed

- `VoiceController` now creates and exclusively owns the initial/current/cached
  speakers. `SelectSpeakApp` obtains a temporary current reference only when
  starting or controlling a request; `_speaker` and duplicate backend state are
  gone.
- Voice selection/setup workers are non-daemon, tracked, rejected after close,
  joined before owned speakers close, and prevented from publishing a result
  once closure starts. A newly created late result closes itself.
- Added `Speaker.close()` and an idempotent `PlaybackController.close()` sentinel
  that rejects submissions, supersedes active work, wakes request workers and
  completion waiters, and lets Natural, Supertonic, and SAPI join normally.
- All backend workers are non-daemon. Natural joins before releasing its native
  engine; Supertonic waits for non-cancellable ONNX inference; SAPI purges active
  speech through its existing generation check and joins before COM teardown.
- Split WaveOut's stop into immediate device reset and a separate cleanup wait.
  Natural now resets audio, cancels synthesis, then waits, preserving prompt
  silence without the former one-second settlement delay.
- `SelectSpeakApp.run()` always invokes one idempotent, partial-startup-safe
  shutdown path. It marks closing, stops input activation, cancels the active
  session, closes all speakers, joins speech waiters, closes tray/player, and
  shuts down `NativeBridge` last. Each resource failure is logged without
  abandoning later cleanup. Startup and `atexit` native shutdown remain only
  idempotent last-resort protection.
- Moved application `PlaybackSession` from the one-module `audio` package to
  `app/playback_session.py` and removed the empty abstraction package.

## Validation

- Full Python suite: 141 passed in 0.38 seconds.
- Focused lifecycle/backend suite: 40 passed.
- Ruff: all checks passed for `src/python`, `tests`, and the Package A runner.
- `ty check`: all checks passed for the project and standalone baseline runner.
- Native Release CTest: 3/3 passed.
- Real Natural workload: stop settlement fell from 1,010.490 ms to 27.141 ms;
  WaveOut reset took 5.439 ms, the worker logged closed, and no workload process
  survived.
- Real Supertonic workload: stop settled in 12.648 ms, backend close completed,
  and no workload process survived.
- Active SAPI smoke: close completed in 437.467 ms, its COM worker reported not
  alive, and the process returned to one thread.
- Normal `scripts/run-dev.ps1 -NoBuild` startup succeeded. Ctrl+C produced
  `app.shutdown.started`, Natural worker/controller close events, and
  `app.shutdown.completed`; no application backend/player process survived.

## Remaining

- Package B is complete. Package C must freeze request identity, terminal-event,
  PCM, callback-ordering, and native session contracts before D–J proceed.
- Supertonic inference remains non-cancellable by its library. Close intentionally
  joins the current inference rather than abandoning it; changing inference
  mechanics is outside Package B.
- Request terminal statuses and removal of per-request speech-wait threads remain
  Package D work. Native ABI declaration ownership remains Package F work.

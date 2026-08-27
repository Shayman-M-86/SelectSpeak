# Package M — Native cutover, cleanup, and acceptance

## Found

- Preflight route: **Adapt**. Packages K1 and L already route Natural Voice and
  Supertonic through request-scoped native PCM/XAudio2 sessions, so a dual-path
  rollout would only recreate an obsolete architecture.
- `WaveOutPlayer` had no production caller; its only remaining references were
  its module and telemetry tests. SAPI is independently removable and is now
  retired rather than retained as a separate project.
- The Package A runner depended on private WaveOut state. It now waits only for
  the native request's start event during a controlled measurement; application
  playback neither waits nor polls for that event.

## Changed

- Collapsed former M/N/O into one Package M with native-only cutover,
  Phase-A comparison, legacy deletion, and clean-tree verification.
- Removed the Python WaveOut engine, WinMM ctypes structures/calls, polling,
  boundary polling, buffers, block preparation, and old-path telemetry tests.
- Updated the controlled baseline runner for native start-event measurement.
- Removed the SAPI backend, picker option, factory fallback, and test; existing
  saved SAPI selections deterministically migrate to Natural Voice.
- Exposed every installed Supertonic style as a separate persisted picker
  option; switching styles recreates only the Supertonic speaker. The optional
  payload now requires all F1–F5 and M1–M5 style files.

## Validation

- Clean-tree Python suite: 207 passed. Ruff and `ty check` passed.
- Native deterministic CTest: 5/5 passed (`audio_api`, OCR layout, selection
  policy, clipboard snapshot, and Natural runtime configuration).
- Real-device XAudio2 lifecycle smoke submitted silence only and passed.
- The native benchmark runner's help-only path passed. Its full Natural and
  Supertonic workloads are intentionally not run automatically because they
  play audible speech through the live device.
- The prior Package K real-device Natural smoke completed at user-confirmed
  100% volume; Package L's focused and full automated validation passed before
  this final cleanup.
- After SAPI removal: full Python suite 207 passed; Ruff and `ty check` passed.
  A source audit found no live SAPI implementation or COM-backend references.

## Remaining

- Run the focused removal validation and then, with explicit approval, the
  controlled Natural/Supertonic workloads plus live WinUI-highlighting and
  shutdown/restart checks. Record the Phase A comparison and mark M complete.

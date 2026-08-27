# Package D — Request and Completion

## Found

- Preflight route: **Proceed**. The live gap matched the frozen Package C
  contract: the application treated backend-local generations as request
  identity, created one `SpeechWait-*` thread per accepted request, and inferred
  completion by waiting on controller state.
- Word callbacks carried text offsets but no immutable request identity. Backend
  failures could also pass through a `finally: complete(...)` path and be
  observed as successful completion.
- The Package A controlled workload depended on the generation/wait seam and had
  to migrate with the product contract so it remains usable for Package O.

## Changed

- Added stable `uint32`-compatible terminal values (`none=0`, `completed=1`,
  `cancelled=2`, `superseded=3`, `failed=4`, `closed=5`) and typed started,
  played-word, and terminal request events.
- `SelectSpeakApp` now allocates monotonically increasing nonzero `uint64`
  request IDs. The ID flows through `Speaker`, each backend's `SpeechRequest`,
  controller state, word events, terminal events, and application stale-event
  validation. Backend generations remain private worker-cancellation tokens.
- `PlaybackController` serializes callbacks outside its state lock, delivers
  `started -> words -> exactly one terminal`, rejects invalid/non-monotonic IDs,
  suppresses all events after terminal, and maps replacement, stop, failure, and
  close to the frozen statuses.
- Natural, Supertonic, and SAPI now publish completion and failure directly from
  their existing worker/playback paths. Failure can no longer be overwritten by
  a successful completion.
- Removed `Speaker.wait_until_done`, application completion polling, the
  `_speech_waiters` registry, and all per-request `SpeechWait-*` threads.
- `PlaybackSession` now stores request identity and the last terminal status.
  The Package A runner waits on terminal events and allocates its own IDs.

## Validation

- Full Python suite: 148 passed in 0.33 seconds.
- Focused request/application/backend suite: 43 passed.
- Ruff: all checks passed for `src/python`, `tests`, and the Package A runner.
- `ty check`: all checks passed with zero diagnostics.
- Native Release CTest: 3/3 passed (`ocr_layout`, `selection_policy`, and
  `natural_voice_speech_runtime_config`).
- Controlled real-device Natural workload completed normal playback,
  pause/resume, and cancellation; stop settled `True` in 27.373 ms and the
  backend worker closed cleanly.
- Controlled real-device Supertonic workload completed the same scenarios;
  stop settled `True` in 4.714 ms and the inference worker closed cleanly.
- `git diff --check` is included in the final clean-diff validation.

## Remaining

- Package D is complete. Package E may now simplify overlapping
  `PlaybackController` state without changing the request/event contract.
- The current Python WaveOut path still invokes callbacks synchronously on its
  existing playback/backend threads. Package I owns non-blocking UI delivery.
- The same request ID will enter the request-scoped native PCM handle when
  Packages F, G, J, and K introduce that ABI; the transitional native Natural
  synthesis API has no request parameter and is intentionally unchanged here.

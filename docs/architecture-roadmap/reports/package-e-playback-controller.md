# Package E — PlaybackController

## Found

- Preflight route: **Proceed**. Package D had stabilized the request-event
  contract, while `PlaybackController` still represented one latest request
  with a drainable `Queue`, a separate current request, an active generation,
  and two pause/resume `Event` objects.
- Submit, cancel, and close repeatedly drained the queue and installed a resume
  signal that was a no-op after the same transition cleared paused state.
- The worker's `begin()` call was a second mutation after dequeue even though
  dequeue is the natural pending-to-active ownership transition.

## Changed

- Replaced the request queue with one condition-protected pending-request slot.
  `next_request()` now waits interruptibly and atomically moves that request to
  the active slot; close still wakes blocked workers and timeout callers still
  receive `queue.Empty`.
- Replaced the pause/resume `Event` pair with one pending `PlaybackCommand`.
  Request settlement clears the command and paused state, preventing controls
  from leaking into a replacement request.
- Removed the redundant active-generation/current-request overlap and the
  `begin()` transition. Natural, Supertonic, and SAPI now consume the active
  request established by `next_request()` while retaining their stale-request
  checks.
- Kept callbacks serialized outside the state condition and made delivery
  reentrant so a callback may safely stop its own request. Package D request
  IDs, event ordering, terminal statuses, and exactly-once settlement are
  unchanged.

## Validation

- Focused controller/backend suite: 34 passed.
- Full Python suite: 153 passed in 0.32 seconds.
- Ruff and `ty check`: all checks passed.
- Native Release CTest: 3/3 passed (`ocr_layout`, `selection_policy`, and
  `natural_voice_speech_runtime_config`).
- Controlled real-device Natural workload completed playback, pause/resume,
  cancellation, and clean worker shutdown; stop settled `True` in 29.938 ms.
- Controlled real-device Supertonic workload completed the same scenarios and
  clean worker shutdown; stop settled `True` in 6.430 ms.

## Remaining

- Package E is complete. Package F may centralize the existing native ABI
  declarations and introduce the frozen audio ABI without changing this
  controller's request-event semantics.
- Python WaveOut buffering, polling, and callback delivery remain intentionally
  unchanged; Packages H, I, J, and N own those later migration steps.

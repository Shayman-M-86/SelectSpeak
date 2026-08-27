# Package H — Bounded Admission

## Found

- Preflight route: **Adapt**. The roadmap states H as "define bounded
  interruptible admission through `PcmPlaybackSession`; implement its native
  wakeup and capacity accounting with the XAudio2 request in J". Package J is
  `Unassessed` and the Package F audio stub still accepts no request, so the
  native half is not implementable yet. H therefore delivers the SelectSpeak
  side of the frozen §5 rule — thresholds, slice sizing, boundary arithmetic,
  and the interruption seam — with the wait itself left to J behind the same
  `submit` call.
- The frozen contract forbids two shapes that would otherwise be tempting here:
  a separate `wait_for_capacity()` ABI ("adds a race without adding
  capability") and any new polling loop. Both constraints are load-bearing on
  the design below.
- Package C fixes provisional values at 1-second low water, 3-second high
  water, and 4-second hard capacity, and states public capacities in frames
  while those values were chosen in seconds. The policy therefore converts at
  the format edge rather than storing seconds.
- The Supertonic 12-second poll named in the contract's seam table
  (`_wait_for_buffer_capacity`, `backends/supertonic.py`) is bound to
  `WaveOutPlayer` through `feed_silence`, `fed_bytes`, `buffered_seconds`, and
  `add_boundary`. Rewriting it now would require either the compatibility
  adapter the plan explicitly forbids or breaking working playback against a
  native path that does not exist. That migration belongs to Package L.

## Changed

- Added `speech/admission.py`. `AdmissionPolicy` holds frame-denominated low
  water, high water, and hard capacity, builds from a `PcmFormat` and the
  provisional second-denominated constants, and rejects threshold sets that
  cannot bound admission. `max_slice_frames` is the high water mark: a slice
  larger than hard capacity could deadlock a producer waiting for room the
  request can never provide, and bounding at high water preserves the
  hysteresis band native uses to schedule wakeups.
- Added `slice_for_admission`, which cuts oversized PCM into admissible slices
  and rebases each boundary onto the slice containing it. Slice-relative frame
  offsets stay slice-relative; complete-request UTF-16 text positions are never
  rewritten; input order is preserved at equal offsets; a boundary sitting
  exactly at the end of the PCM stays in the final slice.
- Added `PcmPlaybackSession.submit_bounded`, which slices and offers each piece
  through the existing synchronous `submit`. It never polls, sleeps, or queries
  free capacity before offering, so it adds no second protocol step and no new
  loop. `needs_more_audio` reads the `buffered_frames_after_submit` telemetry
  the caller already holds rather than consulting native, keeping that value
  advisory as the contract requires.
- Added `PcmAdmissionInterrupted`, raised when stop, supersede, failure, or
  close ends a request while slices remain. `stop`, `close`, and terminal event
  delivery now set an interruption flag that bounded submission observes, so a
  separate control thread ends production; the blocked worker is never
  responsible for interrupting itself. Frames already accepted stay accepted.

## Validation

- Focused suites: `tests/test_admission.py` 19 passed,
  `tests/test_pcm.py` 24 passed.
- Full Python suite: 204 passed in 0.42 seconds, up from the 175-test baseline
  taken at the start of this session.
- Ruff check and `ty check`: all checks passed. `ty` initially reported one
  Liskov violation in the new blocking test double; its override signature was
  corrected rather than suppressed.
- Mutation check on the interruption test: removing the control thread's
  release call makes `test_a_control_thread_releases_a_blocked_submission`
  fail on a still-alive worker, confirming it detects a submission that never
  returns rather than passing vacuously.
- Slicing was verified to preserve every frame and every boundary exactly once,
  including the multi-slice rebasing case and concurrent invocation.
- **Not exercised:** no native build or CTest run. CMake is absent from this
  environment's PATH, and no C++ source was touched this session, so the native
  artifacts are unchanged from commit `0c62e62`. Real bounded blocking is
  modelled by a deterministic test double; genuine native capacity waiting
  arrives with Package J.

## Remaining

- Package H's Python-side outcomes are delivered. The native capacity
  accounting, the interruptible wait inside `submit`, and the wakeup on
  stop/supersede/failure/close are Package J work behind this unchanged call.
- Package J should honour `AdmissionPolicy.max_slice_frames` as the largest
  single admission and wake blocked submissions with their stable status rather
  than a timeout.
- Packages K and L move Natural and Supertonic onto `submit_bounded`. L is
  where `_wait_for_buffer_capacity` and its 12-second poll are deleted; until
  then that loop stays as working legacy WaveOut code, with no adapter built
  between the two playback systems.
- The provisional 1s/3s/4s thresholds may be tuned from Package A evidence
  during M/O without reopening Package C; bounded interruptible admission may
  not.

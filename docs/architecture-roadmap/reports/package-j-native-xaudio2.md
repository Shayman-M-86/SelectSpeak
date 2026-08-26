# Package J — Native XAudio2 Requests

## Found

- Preflight route: **Proceed**. API version 7, `PcmPlaybackSession`, bounded
  submission, and asynchronous played-word delivery already matched the frozen
  Package C contract. The remaining production implementation was the deliberate
  non-accepting Package F audio stub.
- The Package C spike's XAudio2 mechanics transferred cleanly: one persistent
  engine/mastering voice, one fresh source voice per request, `SamplesPlayed`
  corrected by reported output latency, and `OnBufferEnd`/`OnStreamEnd` for
  reclamation and completion.
- XAudio2 and COM initialization cannot safely belong to the arbitrary Python
  thread that first creates a request. A dedicated native runtime thread now
  creates and releases both in the same COM apartment.
- Holding an entire admission slice until `finish_input` could deadlock two
  3-second slices against the 4-second hard cap before playback began. Native
  therefore splits accepted PCM into 100 ms XAudio2 buffers and retains only
  the final internal buffer for `XAUDIO2_END_OF_STREAM`. This keeps the frozen
  ABI unchanged and caps the provisional 4-second queue at 40 buffers, below
  XAudio2's 64-buffer limit.

## Changed

- Replaced `audio_api_stub.cpp` with a production request registry and engine.
  Handles are opaque and request-scoped, request IDs are monotonic, accepting a
  newer request supersedes the old one, and destroyed handles remain invalid.
- Added a sink-independent request core and a thin XAudio2 sink. The core owns
  copied PCM, boundary metadata, 300 ms prebuffering, 1s/3s/4s low/high/hard
  admission, pause/resume/stop, underrun transitions, first-writer terminal
  settlement, and deterministic close. The sink owns only engine/source-voice
  calls and callback translation.
- XAudio2 voice and engine callbacks perform atomic bookkeeping/signalling only.
  A non-audio request dispatcher reclaims completed buffers, queries active
  position, emits ordered due boundaries, translates request-local failures,
  and invokes Python without holding native locks.
- Normal completion requires finished input, every buffer returned, and final
  stream end. Stop/supersede/close destroy the source voice before freeing
  cancelled PCM and do not depend on flush callback order. Destroy joins event
  delivery so callbacks and PCM reads are quiescent on return.
- Added engine-critical-error translation, callback reentrancy rejection,
  interruptible bounded waits, low-water recovery, exact duplicate/final-frame
  boundary ordering, and short-input settlement.
- `ss_shutdown` now closes the production audio runtime after input and Natural
  Voice shutdown. API version remains 7 because Package F already introduced
  the unchanged public audio ABI.
- Replaced the stub checks with deterministic fake-sink coverage and added a
  separate, explicitly invoked real-device smoke executable. Updated Python ABI
  and PCM integration tests to exercise the accepting staged engine.

## Validation

- Full Natural Voice Release build completed without compiler warnings; CTest
  passed 5/5: audio engine, OCR layout, selection policy, clipboard snapshot,
  and Natural Voice runtime configuration.
- The deterministic `audio_api` test passed 50 consecutive runs. Its scenarios
  cover prebuffer and short input, fresh voice lifetime, bounded admission and
  low-water recovery, pause/resume, stop while playing/paused/capacity-blocked,
  stop/close wakeups, ordered/duplicate/final-frame boundaries, invalid-boundary
  atomic rejection, stale IDs, submit after stop, underrun start/recovery,
  pre-start and active device failure, exactly-once terminals, callback order
  and reentrancy, shutdown, and no callback after close.
- The staged real-device XAudio2 smoke passed 3/3 runs. Each run exercised
  request creation, copied PCM submission, played-word delivery, actual playback
  completion, a second fresh request, pause/resume, cancellation, destroy, and
  persistent runtime shutdown.
- Full Python suite: 205 passed. Ruff and `ty check`: all checks passed.
- The SelectSpeak Python and Release WinUI processes were relaunched after DLL
  staging and remained running with the final runtime loaded.
- Built and staged runtime DLL SHA-256 values match:
  `F9EE7737F7777A3B2530DFA721E964F3F6A5C599469B03655E181AF1EAB00BD1`.
- `git diff --check` passed.
- **Limitation:** an AddressSanitizer-configured tree built and its four
  deterministic CTests passed, but the instrumented DLL smoke could not launch
  because the Visual Studio dynamic ASan runtime is not installed. No ASan
  runtime coverage is claimed.

## Remaining

- Package J is complete. Package K can connect Natural synthesis directly to
  this request without changing the PCM ABI, event order, capacity contract, or
  source-voice lifecycle.
- Package L later moves Supertonic PCM/boundaries onto `submit_bounded`; legacy
  WaveOut remains untouched until the rollout and deletion packages.
- The provisional 300 ms prebuffer and 1s/3s/4s admission thresholds remain
  internal and may be tuned from Package A evidence during M/O without reopening
  Package C.

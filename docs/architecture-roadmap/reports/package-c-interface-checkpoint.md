# Package C - Interface-design checkpoint

## Found

- The unified plan already supplies the architectural direction for every Phase C
  topic, but several implementation-critical choices were still implicit:
  accepted-request `started` semantics, UTF-16 text units, atomic boundary
  rejection, the concrete PCM sample format, bounded capacity, callback
  reentrancy, and behavior when a dependent cannot close before DLL shutdown.
- Current Python uses backend-local generations, bytes/seconds/SDK ticks, polling
  backpressure, and request wait threads. These are expected migration gaps, not
  reasons to redesign the target contracts.
- Package B established deterministic ownership and close/join behavior. Its
  shutdown work provides the base for the stronger frozen invariant that the
  native DLL is never unloaded beneath an unclosed dependent.
- The original roadmap went too far toward designing a custom event-driven
  WaveOut engine. SelectSpeak needs to own request semantics, boundary timing,
  capacity policy, and deterministic settlement, but it does not need to own
  low-level Windows device playback.
- XAudio2 best matches this Windows-only, generated-PCM workload: source voices
  accept incremental buffers and expose played-sample/buffer-completion signals
  without adding a third-party runtime. A thin SelectSpeak session is still
  required because XAudio2 does not define request IDs, supersession, word
  boundaries, terminal truth, or Python callback safety.
- Reusing one source voice across requests created counter rebasing, reset, and
  flush-order bookkeeping with no user benefit. The focused spike showed that a
  fresh request source voice removes that entire cross-request state problem.
- `SamplesPlayed` is useful only while a request is active and represents
  processing progress, not exact physical output. The real run reported up to
  39 ms of output latency and returned zero from a position query after stream
  end, so highlighting applies latency correction and completion uses buffer
  completion plus `OnStreamEnd`.

## Changed

- Reworked the unified plan and [proposed interface contract](package-c-interface-contract.md)
  around one persistent XAudio2 runtime and one source voice/handle per request.
- Separated frozen SelectSpeak-visible outcomes from private XAudio2 queue,
  callback, threshold, and thread mechanics. Bounded interruptible admission
  remains architectural; exact thresholds and hysteresis remain tunable.
- Removed the proposed separate `wait_for_capacity()` contract, sequential
  handle reuse, cross-request position rebasing, and dependence on flush callback
  order. `submit` now owns bounded admission and may return runway telemetry.
- Made the WaveOut compatibility adapter optional so work scheduled for deletion
  does not receive a final backpressure/event-engine rewrite unnecessarily.
- Added the [XAudio2 feasibility evidence](package-c-xaudio2-feasibility.md) and
  reduced the spike to one standalone target outside production code.
- Recorded provisional 1/3/4-second low/high/hard capacity starting points and
  the need to slice Supertonic's larger generated segments before admission.
- Recorded the maintainer's explicit approval on 2026-08-21 and froze the
  proposed contract without further clause changes.
- Chose **Adapt** for the revised preflight: the high-level migration remains
  sound, but the playback foundation changes from custom WaveOut to XAudio2.
- No production request/audio implementation was started or changed.

## Validation

- Re-read the unified plan, execution guide, and status cursor.
- Traced the relevant application session, `PlaybackController`, all three
  speakers, Python WaveOut, `NativeBridge`, current native Natural ABI, and WinUI
  callback queue.
- Checked the proposal against all 16 Phase C freeze bullets and the package gates
  for D through J.
- Built and ran the request-scoped real-device XAudio2 spike three consecutive
  final times: **29/29 checks passed** each run.
- Verified incremental PCM, buffer ownership, pause/resume, latency-corrected
  event-driven boundary dispatch, request-local position, prompt source-voice
  destruction, supersession, and no callbacks after destroy.
- Observed source-voice destruction in 14-26 microseconds on this system. This is
  evidence for suitability, not a permanent performance guarantee.
- Reused Package B's real Natural cancellation evidence rather than expanding
  this spike into the Package K integration. The final contract keeps synthesis
  cancellation and audio destruction independently controllable and requires
  both to quiesce before terminal delivery.
- Full Python suite: 141 passed.
- Ruff and `ty check`: all checks passed.
- Native Release CTest: 3/3 passed.
- `git diff --check`: passed.

## Remaining

- Package C is complete. Package D is the next eligible package and owns
  application-issued request identity, terminal status/order, exactly-once
  completion, and removal of per-request speech-wait threads.

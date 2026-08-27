# Package K — Natural Integration

## Found

- Preflight route: **Adapt**. Package J supplied the frozen request-scoped audio
  handle, but native Natural synthesis still returned PCM and boundaries through
  Python callbacks into `WaveOutPlayer`.
- The native ABI needed one direct synthesis operation and therefore advanced
  from version 7 to version 8. The old Natural callback/speak symbols remain only
  as transitional rollout compatibility for Packages M/N.
- The first real-device Natural-to-XAudio smoke exposed a signedness defect in
  the new volume scaler: multiplying negative `int16` samples by an unsigned
  percentage wrapped them before division, producing dangerously loud,
  crackling distortion.
- A silent capture proved the SDK stream itself is valid 24 kHz signed 16-bit
  mono PCM: 43,274 frames matched the SDK's 1,803 ms duration exactly. The
  distortion was introduced by SelectSpeak's scaler, not synthesis or format
  negotiation.
- A later smoke result was incorrectly reported as proving that no compatible
  Natural Voice was installed. A current-user Appx query and the staged native
  bridge both find six healthy voices; the zero-result launch was an execution
  environment failure, not a machine prerequisite gate.

## Changed

- Added `ss_voice_synthesize_to_audio`, which accepts the existing audio handle,
  immutable application request ID, adaptive text chunk, and complete-request
  UTF-16 base offset. Native retains PCM and SDK word boundaries, converts audio
  ticks to frames, validates request identity, and submits directly to the
  request-scoped XAudio2 engine.
- Added fixed-structure generation telemetry for generated frames, synthesis
  duration, and buffered frames after submission. Natural chunks larger than
  the native admission cap are submitted internally as boundary-preserving
  three-second slices.
- Migrated `NaturalVoiceSpeaker` from `WaveOutPlayer` to one
  `PcmPlaybackSession` per application request. Python still owns adaptive
  chunking, structural pauses, generation statistics, request identity, and
  cancellation policy, but no longer receives Natural PCM or synthesis-time
  word callbacks.
- Completion now comes from the native playback terminal event after every
  buffer has played. Pause/resume/stop/supersede/close target the same native
  request, while the Natural SDK remains independently cancellable from another
  Python thread.
- Added native volume configuration and signed-only PCM scaling. The regression
  test covers both positive and negative samples so unsigned wrap cannot recur.
- Direct synthesis now explicitly waits for all SDK audio/word callbacks to
  quiesce before inspecting or submitting captured data; its RAII registration
  still guarantees quiescence during exceptional teardown.
- The internal native-producer seam now validates the application request ID and
  complete-request UTF-16 text range before synthesis, including chunks that
  produce no word boundaries. Pause state that arrives before native request
  setup is carried onto the new audio handle.
- Added an explicit, non-CTest Natural-to-XAudio smoke executable. It is set to
  100% volume and must not be run without explicit user approval.
- Corrected the Natural Voice bridge README so its ownership description matches
  the direct native XAudio2 playback path.

## Validation

- Release Natural/native build completed without compiler warnings; CTest passed
  5/5 (audio engine, OCR layout, selection policy, clipboard snapshot, Natural
  runtime configuration).
- Full Python suite passed: 207 tests. Ruff and `ty check` both passed.
- Focused Natural/ABI/PCM integration passed 37 tests before the final full run;
  the full run includes the updated coverage and staged version-8 DLL checks.
- The deterministic native audio engine test passed 50 consecutive runs after
  adding same-handle producer identity/text-range validation and explicit SDK
  callback quiescence.
- Focused Python validation passed: 37 tests. The full Python suite passed 207
  tests; Ruff and `ty check` passed again.
- Existing Release native checks passed for audio API, speech runtime
  configuration, selection policy, clipboard snapshot, and OCR layout. The
  silent XAudio2 lifecycle smoke also passes when launched beside the staged
  runtime, disproving the reported missing-runtime-dependency blocker.
- Current-user Appx inventory finds six healthy Natural Voice packages: Ryan,
  Aria (two packages), AvaHD, Guy, and Jenny. The staged native bridge discovers
  all six SDK voices with an empty diagnostic.
- After the user's approval, the corrected Natural smoke was launched beside the
  staged bridge and Speech SDK dependencies at 5% volume. It passed discovery,
  initialization, synthesis, played-word delivery, actual playback completion,
  request destruction, and voice shutdown.
- A second user-approved product-path request ran at 100% volume through
  `NaturalVoiceEngine` and `PcmPlaybackSession`: Ryan generated 60,013 frames,
  emitted `started`, four `played_word` events, and one error-free `completed`
  terminal event. The standalone smoke harness still enumerates zero voices in
  its process context, while the same staged bridge discovers all six voices
  when hosted by Python; this harness-only discrepancy does not affect the
  application path.
- The initial audible smoke **failed acceptance** because it was loud, crackly,
  and distorted. This is not counted as a passing validation. Silent diagnosis
  identified and fixed the signed/unsigned PCM scaling defect, and deterministic
  coverage now proves `-20000, -1000, 0, 1000, 20000` scales at 20% to
  `-4000, -200, 0, 200, 4000`.
- The user confirmed that the 100%-volume phrase sounded correct, completing
  real-device acceptance for direct Natural synthesis and native playback.

## Remaining

- Package K is complete. Package K1 is now ready for its separately reviewable
  package-plus-exact-SDK-voice identity and persistence migration work.

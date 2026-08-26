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
- Added an explicit, non-CTest Natural-to-XAudio smoke executable. It is set to
  5% volume and must not be run again without explicit user approval.

## Validation

- Release Natural/native build completed without compiler warnings; CTest passed
  5/5 (audio engine, OCR layout, selection policy, clipboard snapshot, Natural
  runtime configuration).
- Full Python suite passed: 206 tests. Ruff and `ty check` both passed.
- Focused Natural/ABI/PCM integration passed 36 tests before the final full run;
  the full run includes the updated coverage and staged version-8 DLL checks.
- The initial audible smoke **failed acceptance** because it was loud, crackly,
  and distorted. This is not counted as a passing validation. Silent diagnosis
  identified and fixed the signed/unsigned PCM scaling defect, and deterministic
  coverage now proves `-20000, -1000, 0, 1000, 20000` scales at 20% to
  `-4000, -200, 0, 200, 4000`.
- No corrected audible playback has been attempted. The application remains
  stopped and no real-device acceptance is claimed.

## Remaining

- Run one explicitly user-approved, 5%-volume Natural direct-audio smoke and
  confirm clean, intelligible, correctly leveled playback.
- If that confirmation passes, rerun the normal checks if the smoke reveals no
  changes, mark Package K Complete, make K1 Ready, and relaunch the application.

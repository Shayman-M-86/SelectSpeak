# Package L — Supertonic Integration

## Found

- Supertonic inference, chunking, silence trimming, and estimated word
  boundaries were already self-contained in Python. Only its `WaveOutPlayer`
  transport violated the native PCM architecture.

## Changed

- Replaced Supertonic's WaveOut transport with one request-scoped
  `PcmPlaybackSession` at the model's sample rate.
- Submitted the unchanged synthesized PCM, estimated UTF-16 boundaries, and
  structural silence through bounded native admission.
- Routed native played-word and terminal events into the existing
  `PlaybackController`; pause, resume, stop, supersede, and close now target
  the same native request session.
- Corrected the live selector's false activation path: explicit Supertonic
  selection now rejects a fallback speaker, and installation detection requires
  the same managed dependency layer used by activation.

## Validation

- Focused Supertonic and PCM tests: 35 passed.
- Full Python suite: 211 passed. Ruff and `ty check` passed.
- Live log diagnosis reproduced the prior failure: the optional-layer predicate
  returned installed while activation raised `SupertonicDependenciesMissing`.
  Focused dependency/app checks passed 23 tests after the correction.

## Remaining

- Package L is complete. Package M owns opt-in/native-default rollout and the
  M3 pre-deletion comparison and acceptance evidence.

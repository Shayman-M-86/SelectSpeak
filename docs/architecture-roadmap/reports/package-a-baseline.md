# Package A — Baseline and Telemetry

## Found

- Preflight route: **Adapt**. The package already had an automated/current-log
  baseline, so implementation retained it and completed only the missing
  telemetry, controlled workload, and diagnostic gate.
- Package A had no durable baseline report or measurement artifact.
- The current automated suite covers the core Natural/Supertonic stream shape,
  request supersession, pause/resume state, repeat-hotkey stop, clipboard
  fallback, OCR, voice selection, WaveOut cleanup, and WinUI playback commands.
- Existing WaveOut logging records playback startup, completion, played bytes,
  elapsed time, and underruns. Natural chunk logs record playback runway.
- Existing logging does not record PCM callback sizes, peak pending bytes,
  WaveOut loop/position-query counts, submitted-block counts, capacity waits,
  process CPU, or thread counts. Stop-to-silence and playback-position-to-word
  callback delay also cannot be measured precisely from current events.
- The Python WaveOut implementation and its temporary instrumentation are
  transitional and are deleted by final Package M.
- The first attempted Supertonic measurement followed the application optional
  dependency path and correctly exposed a development fallback to Natural. The
  controlled runner now selects its requested installed backend directly so
  evidence cannot be mislabeled; application fallback behavior was not changed.

## Changed

- Added temporary per-playback WaveOut counters for feed-size distribution,
  pending bytes, polling/position queries, submitted blocks, played-word dispatch,
  underruns, reset latency, process CPU, and thread counts. The counters reset on
  every `start()` and emit one structured summary during cleanup.
- Added the repeatable `scripts/capture_audio_baseline.py` workload and preserved
  its Natural and Supertonic raw JSONL evidence beside the durable
  [audio baseline report](audio-baseline.md).
- Removed the six-entry type-check debt baseline with one exact pywin32 stub
  suppression and test-only typed mutation sites. No runtime behavior changed.

## Validation

- Full Python suite: 134 passed in 0.33 seconds (including three new telemetry
  reset/distribution/feed tests).
- Focused WaveOut/WinUI tests: 16 passed.
- Ruff: all checks passed for `src/python`, `tests`, and the baseline runner.
- `ty check`: all checks passed; zero diagnostics is now the required baseline.
- Controlled real-device workloads completed for Natural and Supertonic, each
  covering completion, pause/resume, stop, idle, and post-stop sampling.
- Native Release CTest: 3/3 passed (`ocr_layout`, `selection_policy`, and
  `natural_voice_speech_runtime_config`).

## Remaining

- Package A is complete. Package M owns the final comparison and removes the
  temporary old-path instrumentation only after preserving that evidence.
- End-to-end WinUI rendering delay, live backend switching, and application
  shutdown with active audio remain explicit manual
  acceptance checks; they are not part of the native PCM performance baseline.

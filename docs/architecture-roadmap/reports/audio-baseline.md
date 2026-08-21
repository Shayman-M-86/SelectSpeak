# SelectSpeak Audio Baseline

This artifact is the pre-migration comparison point for Package O. Measurements
are separated by evidence quality so an uncontrolled historical log is not
mistaken for a repeatable benchmark.

## Reference

- Roadmap reference commit: `1f7461213f55ebcc218a564405df3786c284f2d9`.
- Baseline captured: 2026-08-21 (Australia/Sydney).
- Current implementation: Python `WaveOutPlayer`, 24 kHz mono PCM16 for Natural
  Voice, 100 ms playback blocks, four queued WaveOut buffers, and a 2-5 ms
  polling loop.

## Automated behavior baseline

The full Python suite passed: 131 tests in 0.36 seconds. Relevant protected
behavior includes:

| Behavior | Current evidence |
| --- | --- |
| Natural Voice stream/chunk integration | `tests/test_natural_voice.py` |
| Supertonic stream, boundaries, and structural pauses | `tests/test_supertonic_voice.py` |
| WaveOut coordination and cleanup | `tests/test_waveout.py` |
| Request supersession and pause/resume state | `tests/test_playback.py` |
| Repeat-hotkey stop and delayed clipboard fallback | `tests/test_app.py` |
| Voice/backend option selection | `tests/test_voice_options.py`, `tests/test_natural_voice.py` |
| OCR and native input behavior | `tests/test_ocr_capture.py`, `tests/test_native_input.py`, native CTest |
| WinUI pause/resume commands | `tests/test_winui_bridge.py` |
| Text preparation and highlighting offsets | `tests/test_text_processing.py` |

Native Release CTest passed 3/3 tests: OCR layout, selection policy, and Natural
Voice speech-runtime configuration. Ruff passed for `src/python` and `tests`.

Automated gaps to retain as explicit manual/controlled checks are actual SAPI
audio/end-of-stream behavior, real audio-device pause/resume/stop timing,
backend switching during live playback, application shutdown with active audio,
and end-to-end WinUI highlighting timing.

## Type-check baseline

The six initial diagnostics were localized to one understated pywin32 buffer
stub and five deliberately replaced test attributes. Package A narrowed the
production suppression to the exact `ty` rule and typed the test-only mutation
sites through `Any`. `.venv/Scripts/python.exe -m ty check` now passes. Every
subsequent package must preserve a zero-diagnostic baseline.

## Existing-log observations

Source: `%LOCALAPPDATA%/SelectSpeak/logs/selectspeak.log`, session
`0b83037077554e0db0676093f9650e83`. This was a long interactive Natural Voice
session, not a controlled benchmark. It is useful evidence of present behavior
and scale, but Package O must compare against the later controlled Package A
workload rather than treating these figures as statistically repeatable.

| Metric | Observation |
| --- | --- |
| Completed playback records | 69 starts and 69 finishes |
| Playback disposition | 50 naturally completed; 19 finished with `stopped=True` |
| Total played PCM | 127,836,466 bytes / 2,663.253 audio seconds |
| First-audio latency | median 15 ms; P95 20 ms; max 236 ms |
| Chunk-selection runway | median 118.779 s; P95 875.027 s; max 1,184.294 s |
| Logged underruns | 0 |
| Played-word callbacks | 5,922 |
| Word callback to synchronous pipe-send log | median 0 ms; P95 1 ms; max 4 ms |

The last timing measures only the interval between the Python word-boundary log
and the synchronous WinUI pipe-send log. It does not measure how late the
boundary was relative to the audio position, pipe completion, WinUI dispatch,
or rendered highlighting.

The very large runway values confirm that current synthesis can run hundreds of
seconds ahead of playback. Package H owns the bounded high/low-water correction;
Package A records the behavior but must not redesign backpressure.

## Controlled workload

The repeatable runner is `scripts/capture_audio_baseline.py`. It loads the saved
voice/settings, selects one backend explicitly, and uses fixed text for three
scenarios: natural completion, a 300 ms in-playback pause/resume, and stop 350 ms
after playback starts. Each backend runs in its own process. Raw evidence is in
[Natural JSONL](package-a-natural-20260821.jsonl) and
[Supertonic JSONL](package-a-supertonic-20260821.jsonl).

Environment: Python 3.13 project venv, saved Ava Natural Voice, Supertonic F4
English at 8 steps and speed 1.05, 100% volume, the default Windows audio device,
and no other SelectSpeak process. Measurements are one controlled run per
backend, so they are comparison anchors rather than statistically stable claims.

### Scenario results

| Backend / scenario | First audio | Played audio | Peak pending | Feed calls | Blocks | Loops / position queries | CPU | Underruns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Natural completion | 231 ms | 9.525 s | 438,000 B / 9.125 s | 130 | 96 | 652 / 652 | 4.48% | 0 |
| Natural pause/resume | 15 ms | 20.550 s | 957,600 B / 19.950 s | 296 | 206 | 1,432 / 1,432 | 2.39% | 0 |
| Natural stop | 19 ms | 0.336 s | 1,229,400 B / 25.613 s | 349 | 7 | 126 / 126 | 20.72% | 0 |
| Supertonic completion | 31 ms | 7.425 s | 601,978 B / 6.825 s | 2 | 75 | 480 / 480 | 49.36% | 0 |
| Supertonic pause/resume | 8 ms | 17.962 s | 1,337,298 B / 15.162 s | 5 | 180 | 1,177 / 1,177 | 65.66% | 0 |
| Supertonic stop | 7 ms | 0.335 s | 403,472 B / 4.574 s | 2 | 7 | 22 / 22 | 916.18%* | 0 |

`*` The stopped Supertonic playback lasted only 361 ms while inference used
multiple CPU cores; this percentage is real process CPU divided by short wall
time, but is not a useful steady-state utilization figure.

Natural PCM callbacks were 600-11,400 bytes across the workload (median
3,000-3,600; P95 6,600). Supertonic submits synthesized segments rather than
engine callbacks: 2-5 feeds per scenario, from 8,820 to 798,362 bytes. Played-word
dispatch after the position sample was observed had a 0.002-0.003 ms median and
0.010 ms maximum. This measures Python dispatch after a polling observation, not
lateness relative to the exact device playback instant or WinUI rendering.

Pause calls took 2.159 ms for Natural and 6.548 ms for Supertonic; resume calls
took 0.094 ms and 0.135 ms. WaveOut reset, the closest available stop-to-silence
proxy, took 7.074 ms for Natural and 1.189 ms for Supertonic. The full Natural
`speaker.stop()` call took 1,010.490 ms because its audio completion wait reached
the existing one-second bound; Supertonic took 3.741 ms. Package B should retain
this as shutdown/settling evidence rather than treating device silence and API
settlement as the same measurement.

Idle and post-stop thread counts were both 2 for both backend processes; playback
peaked at 3. Idle CPU was 0.00%. Natural post-stop CPU was 0.00%; Supertonic
post-stop CPU was 429.64% because cancelled inference continued to completion
during that one-second sample. Logs also show post-terminal chunk/inference work
on both stopped requests. Packages B and D own deterministic worker settlement
and terminal-event rules; Package A records this behavior without changing it.

Capacity-wait duration is not applicable before Package H. SAPI remains a
separate manual behavior check because it owns its audio path and is outside the
native PCM comparison.

# Package C frozen interface contract

Status: **Frozen — explicitly approved by the maintainer on 2026-08-21.**

This document freezes SelectSpeak-visible behavior, not XAudio2 queue layout or
thread topology. The [feasibility evidence](package-c-xaudio2-feasibility.md)
supports one persistent XAudio2 runtime and one source voice per speech request.
Every **must** below is a gate for Packages D through J. A later change to these
visible rules must explicitly reopen Package C.

## 1. Responsibility boundary

Python owns application meaning and policy:

- text normalization, adaptive chunking, and structural pauses;
- backend selection/fallback and Supertonic inference;
- application request allocation and the decision to stop or supersede;
- voice/settings persistence and UI state.

The SelectSpeak native layer owns timing-sensitive enforcement:

- request-scoped PCM memory and XAudio2 source-voice lifetime;
- bounded producer admission and buffer reclamation;
- active playback position and word-boundary scheduling;
- native errors, event ordering, terminal settlement, and quiescence.

XAudio2 owns the engine, mastering/source voice processing, device output,
format conversion, and low-level audio callbacks. XAudio2 callbacks are signals,
not SelectSpeak request events.

## 2. Request identity and lifecycle

- Python allocates monotonically increasing `uint64 request_id` values in
  `1..UINT64_MAX`. Zero is invalid and IDs are not reused in one process.
- The immutable ID follows the application request, controller, speaker, native
  synthesis, native PCM request, every event, and terminal handling.
- A request is accepted after synchronous validation/admission. A rejected call
  emits no lifecycle event. Every accepted request emits exactly one `started`
  event and exactly one terminal event.
- `started` means accepted and current; it does not claim the first frame is
  physically audible.
- One application request is current. Accepting a replacement settles every
  older accepted non-terminal request as `superseded`.

Per-request event order is:

```text
started
-> zero or more played_word / underrun events
-> exactly one terminal event
```

Terminal values are stable `uint32` wire values:

| Value | Status | Meaning |
| --- | --- | --- |
| 0 | `none` | Sentinel; never emitted as a terminal event |
| 1 | `completed` | Input finished and XAudio2 consumed every accepted PCM buffer |
| 2 | `cancelled` | Explicit user stop |
| 3 | `superseded` | A newer request replaced it |
| 4 | `failed` | Backend, synthesis, runtime, or device failure |
| 5 | `closed` | Application/backend teardown |

Terminal selection is first-writer-wins under synchronization. No word,
underrun, error, or second terminal event may escape afterward.

## 3. Request-scoped native handle

The conceptual ABI is deliberately narrow:

```text
create(request_id, format, request_text_length_utf16, callback) -> handle
submit(handle, pcm, boundaries) -> submit_result
finish_input(handle)
pause(handle)
resume(handle)
stop(handle, terminal_reason)
destroy(handle)
```

- One handle represents exactly one request and owns exactly one XAudio2 source
  voice. Neither the handle nor source voice is reused for another request.
- The XAudio2 engine and mastering voice belong to the longer-lived native audio
  runtime, not to individual requests.
- The handle state is `accepting -> draining -> terminal -> destroyed`, with
  stop/failure/close paths able to move directly to terminal settlement.
- `finish_input` is accepted once. Later submissions fail with `wrong_state`.
- Pause/resume and stop are idempotent for the matching request.
- Destroy rejects new operations, interrupts blocked submission, coordinates
  producer shutdown, destroys the source voice from a non-XAudio2-callback
  thread, drains SelectSpeak event delivery, and invalidates the handle.
- After native destroy returns, the request emits no callback and native reads
  no request PCM. A later native operation returns `invalid_handle`.
- Python wrappers make `close()` idempotent and retain callback/context objects
  until native destroy returns.

## 4. PCM and text-boundary contract

- The first ABI accepts interleaved signed 16-bit little-endian PCM
  (`pcm_s16_le=1`). Format is immutable `{sample_rate_hz, channel_count,
  sample_format}`; zero values are invalid and the first implementation may
  reject non-mono input.
- A frame contains one sample per channel. Public positions, lengths,
  `generated_frames`, and optional buffer telemetry use non-negative integer
  frames, with cumulative values represented as `uint64`.
- Bytes, milliseconds, Speech SDK ticks, and XAudio2 mastering-rate latency are
  converted at their platform edges. PCM byte length must be divisible by
  `channel_count * 2`.

Each boundary is:

```text
{ uint64 frame_offset, uint32 text_position, uint32 text_length }
```

- `frame_offset` is relative to that submitted PCM slice.
- Text positions/lengths use UTF-16 code units relative to the complete spoken
  request. Python converts Supertonic code-point offsets before submission;
  Natural adds its complete-request UTF-16 base offset natively.
- Boundaries are nondecreasing, preserve input order at equal offsets, fit the
  submitted frame count and complete text, have nonzero text length, and do not
  split a surrogate pair.
- Invalid boundaries reject the whole submission atomically with
  `invalid_boundary`; no PCM or metadata from that call is retained.
- Python validates surrogate-pair edges using the original text. Native
  independently validates ordering, overflow, frame bounds, and UTF-16 bounds.

## 5. Submission ownership and bounded admission

- `submit` is synchronous and may wait interruptibly until bounded native
  capacity admits the slice. On success, native has copied all PCM, boundaries,
  and metadata needed after return. On failure, it accepts none of the call.
- Stop, supersede, failure, close, and destroy wake blocked submissions promptly
  with their stable status. The separate `wait_for_capacity()` ABI is rejected:
  a two-step wait/enqueue protocol adds a race without adding capability.
- Producers cannot grow queued audio without limit. Exact buffer size, queue
  layout, low/high thresholds, and hysteresis implementation remain internal.
- Large generated Supertonic segments are sliced, with boundary offsets adjusted,
  before bounded submission. Inference and waveform content do not change.
- Normal PCM is reclaimable at XAudio2 `OnBufferEnd`. Cancelled or superseded
  request PCM remains owned until `DestroyVoice()` returns, after which it is
  safe to free whether or not every buffer produced `OnBufferEnd`.
- A `buffered_frames` value may be returned as telemetry for adaptive chunking,
  diagnostics, or synthesis results. It is not a separate synchronization API
  or a frozen queue-mechanics promise.
- Package H/J begin with provisional 1-second low water, 3-second high water,
  and 4-second hard capacity. These values may be tuned from Package A evidence
  without reopening Package C; bounded interruptible admission may not.

## 6. Playback position, boundaries, and completion

- While a request is active, one SelectSpeak-owned non-audio event path observes
  its source voice. XAudio2 `OnVoiceProcessingPassEnd` performs only bounded
  signalling; it does not call Python or take application locks.
- The event path queries active-request `SamplesPlayed`, subtracts XAudio2's
  reported output latency converted to source frames and clamped at zero, and
  emits every due word boundary in order.
- This is a playback-position estimate, not a claim of sample-exact physical
  speaker observation. Package O compares its highlighting behavior with the
  Package A baseline.
- `SamplesPlayed` is consulted only while the request is active. The feasibility
  run observed it return to zero after stream end; terminal completion must not
  depend on a post-terminal cursor query.
- Normal completion requires synthesis/input finished, every accepted buffer
  handed back by `OnBufferEnd`, and exactly one `OnStreamEnd` for the final
  `XAUDIO2_END_OF_STREAM` buffer.
- Stop/supersede/close do not depend on `FlushSourceBuffers` callback order.
  They close producer admission, coordinate synthesis cancellation, destroy the
  request source voice, discard unplayed boundaries, and then emit the terminal
  result.

## 7. Native status and error behavior

Synchronous calls return stable `uint32` values:

```text
0 ok
1 invalid_handle
2 invalid_request
3 invalid_argument
4 invalid_boundary
5 wrong_state
6 device_error
7 closed
8 internal_error
```

- Unknown future values are preserved numerically and mapped to a generic Python
  native error; unknown never means success.
- Validation/state errors before acceptance emit no lifecycle event. A failure
  after acceptance emits exactly one terminal `failed` event with a stable code
  and copied diagnostic text.
- Audio errors are request/session-local. There is no process-global audio
  `last_error`, and diagnostic storage must not alias another request's failure.
- `NativeBridge` owns API-version verification, ctypes declarations, callback
  definitions, and common status mapping.

## 8. Callback and control threading

- XAudio2 callbacks perform only bounded atomic bookkeeping and signalling and
  return immediately. They do not call Python, allocate unbounded work, perform
  UI/pipe/disk I/O, destroy voices, or wait on SelectSpeak locks.
- SelectSpeak events are serialized per request on a non-audio path and never
  delivered while a native session/device lock is held. A single native audio
  event thread is the intended first implementation; thread count is not an ABI
  guarantee.
- Python callbacks copy retained payloads, validate `request_id`, update small
  synchronized state, and queue UI work through `call_soon`.
- The same handle is non-reentrant from its Python event callback. Control work
  caused by an event is queued to a separate Python-owned thread.
- Python exceptions are caught inside the ctypes callback and never cross the C
  ABI. Native terminal truth does not depend on a UI/debug consumer succeeding.
- A controller/control thread remains able to stop or close while Natural
  synthesis or bounded submission blocks on its worker. The blocked worker must
  never be responsible for interrupting itself.

## 9. Natural synthesis result

The Python-facing immutable result remains:

```text
NaturalSynthesisResult {
    status
    uint64 generated_frames
    uint64 synthesis_duration_us
    uint64 buffered_frames_after_submit
}
```

- The native result is size/version tagged. Metrics are valid only for `ok` and
  otherwise zero; `generated_frames` covers that adaptive chunk.
- Natural PCM and unplayed boundaries never cross Python. Played-word events use
  the native request event path.
- Cancellation first closes request admission, then coordinates Speech SDK
  cancellation and request-source-voice destruction. Terminal delivery waits
  for both to quiesce.

## 10. Shutdown guarantees

- Application shutdown is one idempotent path. Once closing begins, input,
  speech, backend-switch, and callback-driven new work are rejected.
- Shutdown is partial-startup safe, attempts independent cleanup, and preserves
  the first safety-relevant failure for diagnostics.
- Order is: mark closing; settle the active application request; close
  `VoiceController`; stop/join speech and inference workers; destroy request
  voices and synthesis capabilities; close UI/input/OCR capabilities; close
  `NativeBridge` last.
- Backend/request close has no timeout-based abandonment. On return, workers are
  joined, blocked producers are awake, source voices are destroyed, callback
  contexts are releasable, and no future callback is possible.
- If native capability destruction cannot be proven after a cleanup failure,
  leave the shared DLL loaded for process-exit cleanup rather than unloading code
  beneath a live worker or callback. `atexit` remains last-resort protection.

## Current-seam reconciliation

| Area | Current implementation | Package |
| --- | --- | --- |
| Identity/terminals | Backend generations and per-request wait threads | D |
| Controller state | Queue, generations, events, and booleans overlap | E |
| ABI/errors | Capability wrappers configure ctypes; Natural uses global error text | F |
| PCM abstraction | Backends instantiate Python `WaveOutPlayer` directly | G |
| Bounded admission | Supertonic polls at 12 seconds; Natural uses adaptive runway | H/J |
| UI dispatch | Word highlighting calls the bridge synchronously | I |
| Native playback | No request-scoped XAudio2 source-voice implementation | J |
| Natural flow | PCM and boundaries cross from C++ through Python | K |
| Supertonic flow | Python PCM still feeds Python WaveOut | L |

Implementation references:

- [Feasibility evidence](package-c-xaudio2-feasibility.md)
- [XAudio2 streaming](https://learn.microsoft.com/windows/win32/xaudio2/xaudio2-streaming-audio-data)
- [`DestroyVoice`](https://learn.microsoft.com/windows/win32/api/xaudio2/nf-xaudio2-ixaudio2voice-destroyvoice)
- [XAudio2 callback constraints](https://learn.microsoft.com/windows/win32/xaudio2/xaudio2-callbacks)

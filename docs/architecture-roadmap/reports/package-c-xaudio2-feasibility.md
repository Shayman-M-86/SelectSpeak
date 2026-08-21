# Package C - XAudio2 feasibility evidence

## Question

Can SelectSpeak use one persistent XAudio2 engine/mastering voice and one fresh
source voice per speech request, while preserving incremental PCM, word timing,
pause/resume, prompt cancellation, supersession, buffer ownership, and
deterministic shutdown?

## Method

The standalone, non-production spike lives under
[`spikes/xaudio2`](../spikes/xaudio2/). It links only Windows XAudio2 and does not
enter the shipped native DLL. The final form deliberately avoids source-voice
reuse across requests.

It exercises real default-device playback with 24 kHz mono PCM16 and uses only
atomics plus `SetEvent` in XAudio2 callbacks. One non-audio test thread consumes
processing-pass signals, queries active-request position, applies XAudio2's
reported output latency, and dispatches simulated word boundaries.

## Results

Three consecutive final runs passed all **29/29** checks.

| Observation | Result |
| --- | ---: |
| Mastering rate on this system | 44,100 Hz |
| Incremental request PCM | 24,000/24,000 frames accepted; 10/10 buffers completed |
| Event-driven boundary lateness | 0 ms observed; 20 ms check passed |
| Maximum reported output latency | 39 ms |
| Pause position | Stable within the allowed 10 ms committed quantum |
| Normal `DestroyVoice()` | 20-24 microseconds observed |
| Cancel/supersede `DestroyVoice()` | 14-26 microseconds observed |
| Callback after `DestroyVoice()` returned | None |
| Fresh superseding voice position | Began at zero and advanced independently |

The active source position reached 23,761 frames before end-of-stream, while a
query after end-of-stream returned zero. Completion therefore must use completed
buffer ownership plus `OnStreamEnd`; it must not depend on a post-terminal
`SamplesPlayed` query.

Cancellation intentionally destroyed a request with queued buffers. XAudio2 did
not need to deliver `OnBufferEnd` for those buffers: once `DestroyVoice()`
returned, it was safe to release all request-owned PCM and callback context, and
no later callback arrived.

## Architectural consequences

- Keep one XAudio2 engine and mastering voice for the native audio runtime.
- Create one source voice per accepted SelectSpeak PCM request; never reuse it
  for a later request.
- Reclaim normally played PCM at `OnBufferEnd`. On stop, supersede, failure, or
  close, reject further producer work and reclaim the remainder after
  `DestroyVoice()` returns.
- Use `OnVoiceProcessingPassEnd` only to signal one native non-audio event
  thread. That thread queries the active request's `SamplesPlayed`, subtracts
  XAudio2's reported output latency converted to source frames, and emits due
  word boundaries in order.
- Define completion as synthesis/input finished plus XAudio2 consumption of all
  accepted buffers. Physical speaker output cannot be known sample-exactly;
  XAudio2's reported latency is the best available correction for highlighting.
- Use one interruptible, bounded `submit` operation. Do not expose a separate
  `wait_for_capacity()` race or freeze queue topology.
- Treat 1 second low water, 3 seconds high water, and 4 seconds hard capacity as
  provisional Package H/J starting values only. At 100 ms native buffers the
  hard limit is 40 buffers, below XAudio2's 64-buffer queue limit.
- Supertonic produced individual baseline segments up to about 9.7 seconds, so
  Package L must slice generated PCM/boundaries into bounded submissions without
  changing inference.

## Natural cancellation boundary

The spike did not migrate Natural Voice or duplicate Package K. Package B's real
Natural workload already demonstrated that the independent control path cancels
synthesis and settles the worker promptly. The frozen rule is that cancellation
first closes producer admission, then coordinates Natural cancellation and
request-source-voice destruction; the terminal event follows only after both
are quiescent. Package K must validate that integrated path.

## Reproduction

Configure and build the standalone target with the repository's Visual Studio
CMake, then run:

```powershell
.\.build\xaudio2-spike\Release\xaudio2_spike.exe
```

Expected final line:

```text
=== summary: 29 passed, 0 failed ===
```

## Verdict

**Proceed with XAudio2, using one source voice per request.** The spike supports
the intended architecture with three explicit caveats: active position requires
output-latency correction, completion must not query position after stream end,
and cancellation releases remaining PCM after `DestroyVoice()` rather than
waiting for flushed-buffer callback order.

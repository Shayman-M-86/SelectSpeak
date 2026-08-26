These final reviewer comments are good refinements rather than another architectural change. I’ve folded them in below, fixed the phase/package lettering, removed duplicated work, and made the ABI/session rules explicit enough that an implementation agent should not need to redesign them mid-project.

# SelectSpeak Unified Architecture and Implementation Plan

> Agents execute this roadmap using
> [`architecture-roadmap/EXECUTION.md`](architecture-roadmap/EXECUTION.md) and
> record progress in
> [`architecture-roadmap/STATUS.md`](architecture-roadmap/STATUS.md). This
> document remains the source of truth for architectural intent and Package C
> contracts.

## Goal

Implement the audio-pipeline and Python simplification recommendations as one coordinated roadmap without:

* rewriting the same subsystem multiple times
* optimizing code that will shortly be deleted
* introducing temporary abstractions that later become permanent
* changing user-visible behaviour during architectural cleanup
* mixing unrelated cleanup into the audio migration
* creating competing request/session identities
* moving logic into C++ merely because native code is theoretically faster

## Known-good reference point

At feature-branch commit
`1f7461213f55ebcc218a564405df3786c284f2d9` (2026-08-21), the application is a
known-good working baseline before this architecture migration begins.

This roadmap is primarily an optimization, simplification, ownership, and
cleanliness migration. Preserving existing behaviour is therefore more important
than completing a structural change exactly as first imagined.

If implementation drifts substantially, several behaviours regress together, or
the intended old behaviour becomes unclear, compare the affected path with this
commit. Use it to recover working semantics, lifecycle expectations, tests, and
integration details before attempting broader corrective changes.

The reference commit is diagnostic evidence, not permission to reset the branch,
overwrite later work, or reintroduce architecture that a completed package has
intentionally replaced. Inspect and reconcile the relevant implementation while
preserving unrelated changes.

The target architecture is:

```text
Python
  application behaviour
  speech policy
  text preparation
  backend selection
  request/session state
  Supertonic inference
           │
           ▼
C++ native DLL
  Windows-specific facilities
  Natural Voice synthesis
  PCM playback
  PCM buffering
  playback timing
  word-boundary scheduling
  pause/resume/stop
           │
           ▼
Python application
  request validation
  asynchronous UI delivery
           │
           ▼
WinUI
  rendering
  player UI
  highlighting
  settings UI
```

---

# Locked architectural decisions

## 1. Python owns meaning and policy

Keep these Python-owned:

* text normalization
* adaptive chunking
* punctuation and structural-pause policy
* backend selection/fallback
* application `PlaybackSession`
* repeat-hotkey-to-stop behaviour
* request/session identity
* stale-request rejection
* Supertonic inference
* Supertonic boundary estimation
* voice/settings persistence
* application UI-state decisions

Do not migrate these into C++.

---

## 2. Native owns PCM playback through XAudio2

The final audio path uses a thin SelectSpeak-owned C++ session over Windows
XAudio2. SelectSpeak owns the application-facing audio contract; XAudio2 owns
the physical playback engine and device-facing mechanics.

Keep one XAudio2 engine/mastering voice for the native audio runtime. Create one
source voice for each accepted PCM speech request and destroy it at that
request's completion, cancellation, supersession, failure, or close. Do not
reuse a source voice across application requests.

The SelectSpeak native session owns:

* prebuffering
* bounded queueing
* PCM lifetime until XAudio2 buffer completion
* played-frame position
* word-boundary scheduling
* pause/resume
* stop/supersede settlement
* playback completion
* underrun detection
* deterministic audio shutdown

XAudio2 owns:

* mastering/source voices and audio-device output
* asynchronous PCM buffer consumption
* source-voice start/stop
* buffer-completion callbacks
* device-rate conversion where required

Do not build a second device engine around XAudio2. Native code may wrap its
callbacks and queue state only as required to satisfy SelectSpeak request,
boundary, capacity, error, and shutdown semantics. XAudio2 callbacks signal
SelectSpeak-owned non-audio work and return immediately; they never invoke
Python or perform UI I/O.

The current Python `WaveOutPlayer` is transitional and will eventually be deleted.

---

## 3. Natural Voice PCM stays native

Final Natural Voice flow:

```text
Python
  text chunk
  request_id
  complete-text base offset
       │
       ▼
C++ Natural Voice synthesis
       │
       ├── PCM ───────────────► native session ─► XAudio2
       │
       └── boundaries ────────► native boundary scheduler
                                      │
                                      ▼
                               played-word event
                                      │
                                      ▼
                                   Python
```

Python must not receive Natural Voice PCM once native playback exists.

---

## 4. Supertonic remains Python-owned

Final Supertonic flow:

```text
Python Supertonic inference
          │
          ▼
PCM segment + boundaries
          │
          ▼
native PCM session enqueue
          │
          ▼
native session ─► XAudio2
```

Do not migrate Supertonic inference into C++.

---

## 5. `PlaybackController` remains

Keep it.

It owns useful backend request, cancellation and pause/resume semantics shared by the speech backends.

It may be simplified internally but remains separate from application-level `PlaybackSession`.

---

## 6. `VoiceController` becomes the sole speaker owner

`VoiceController` owns:

* current speaker
* cached speakers
* activation
* backend identity
* speaker shutdown

`SelectSpeakApp` must not maintain a second independent current-speaker owner.

Completion callbacks must identify immutable requests rather than relying on mutable "current speaker" state.

---

# Request identity

## 7. The application allocates every `request_id`

Use an unsigned 64-bit integer:

```text
uint64 request_id
```

Rules:

* allocated by the Python application
* monotonically increasing
* never reused during one process lifetime
* process restart may reset the sequence
* the same ID flows through:

  * `PlaybackSession`
  * `PlaybackController`
  * speaker backend
  * native synthesis
  * native audio session
  * callbacks
  * application completion handling

Native code must not create a second competing generation identity.

Existing internal generation numbers may remain temporarily for implementation purposes, but they are not externally authoritative request identity.

---

# Completion semantics

## 8. Completion means playback completion

### Natural Voice

Completed only when:

* synthesis input is finished
* all queued PCM has actually played

### Supertonic

Completed only when all submitted PCM has played.

### SAPI

Completion means actual end-of-stream.

Initially the existing SAPI worker may continue determining this using its current mechanism.

Direct SAPI `EndStream` events are introduced later in the separate SAPI project.

### Cancellation

Cancellation completes only after synthesis/playback cancellation has settled sufficiently that no further events can occur for that request.

---

## 9. Terminal-status truth table

Use these meanings consistently:

| Situation                           | Terminal status |
| ----------------------------------- | --------------- |
| Audio fully played                  | `completed`     |
| Explicit user stop                  | `cancelled`     |
| New request replaces active request | `superseded`    |
| Backend/runtime/device error        | `failed`        |
| Application/backend/session closing | `closed`        |

Each accepted request receives **exactly one** terminal status.

---

## 10. Callback ordering

For each request:

```text
started
→ zero or more played_word / underrun events
→ exactly one terminal event
```

Rules:

* `started` occurs at most once
* no played-word callback occurs before `started`
* callbacks for one request are serialized in order
* terminal is always the final callback
* no callback occurs after terminal
* no callback occurs after session destruction returns

---

# Lifecycle

## 11. One authoritative application shutdown path

One idempotent shutdown implementation owns normal cleanup.

Whether its public name remains `shutdown()` or becomes `close()` is secondary.

It must:

* reject new work once closing begins
* work after partial startup
* continue cleanup if one resource fails
* log cleanup failures
* not abandon later resources because an earlier close operation failed

`atexit` may remain only as last-resort protection.

---

## 12. Shutdown order

Required invariant:

**NativeBridge must outlive every object capable of calling into it.**

Recommended order:

```text
mark application closing
→ reject/stop new input activation
→ cancel active PlaybackSession
→ close VoiceController
    → stop every speaker
    → join every speech worker
    → destroy native audio/speech sessions
→ stop OCR/input native capabilities
→ close tray / WinUI bridge/process
→ shut down shared NativeBridge last
```

Minor ordering between UI/tray and input may differ if implementation requires it, but:

* no speech worker may survive native DLL shutdown
* no callback may access unloaded native code
* no new speech request may start once closing begins

---

## 13. Backend close contract

Every backend must be able to:

1. reject new requests
2. cancel active work
3. wake blocked workers
4. terminate worker loops
5. join workers
6. release backend-specific resources

Daemon-thread abandonment is not the normal shutdown mechanism.

---

# Native ABI rules

## 14. Centralize native ABI configuration

`NativeBridge` owns:

* DLL loading
* API-version verification
* all `argtypes`
* all `restype`
* common status/error definitions
* capability creation
* final DLL shutdown

Capability wrappers own:

* Python callbacks
* callback lifetimes
* subsystem state

They do not repeatedly mutate shared ctypes function definitions.

---

## 15. Native API versioning

When the audio ABI is introduced:

* increment `SELECTSPEAK_NATIVE_API_VERSION`
* update Python `NATIVE_API_VERSION`
* update ABI/version tests
* ensure the matching DLL is staged before Python integration tests run

Do **not** increment the public native ABI version for internal C++ implementation changes that do not alter the interface.

---

# Native error model

## 16. Do not use one global `last_error` for audio sessions

Synchronous native calls return stable status/error codes.

Examples:

```text
ok
invalid_handle
invalid_request
invalid_argument
invalid_boundary
wrong_state
device_error
closed
```

Asynchronous session failures are delivered through the request's terminal `failed` event.

Diagnostic text may be:

* attached/copied as part of the terminal event, or
* retrieved from the specific session while it remains valid

Destroyed handles return `invalid_handle`.

Do not expose stale process-global audio errors belonging to another session.

---

# Audio-session ownership

## 17. Use request-scoped opaque native handles

Conceptually:

```text
ss_audio_request_create(request_id, format, ...) -> handle
ss_audio_request_submit(handle, pcm, boundaries) -> submit_result
ss_audio_request_finish_input(handle)
ss_audio_request_pause(handle)
ss_audio_request_resume(handle)
ss_audio_request_stop(handle, terminal_reason)
ss_audio_request_destroy(handle)
```

One handle owns one immutable request ID and one XAudio2 source voice. It is
never reset or reused for a later request. Explicit handles simplify:

* ownership
* testing
* callback contexts
* Natural/Supertonic format differences

---

## 18. Handle lifecycle and idempotency

Rules:

* lifecycle is `accepting -> draining -> terminal -> destroyed`
* `stop`, pause, and resume are idempotent where valid
* no new operation may begin once terminal settlement/destruction starts
* destroy interrupts blocked submission and destroys the source voice from a
  non-XAudio2-callback thread
* callback contexts and request PCM remain valid until destroy returns
* Python retains native callback objects until destroy returns
* native operations after destroy return `invalid_handle`; Python `close()` is
  independently idempotent
* after destroy returns, no callbacks or PCM reads may occur

---

# PCM contract

## 19. Frames are the canonical audio-position unit

Use integer frames throughout the final PCM API.

Do not mix:

* bytes
* milliseconds
* Speech SDK ticks
* frame counts

inside the core playback contract.

Convert only at platform boundaries.

PCM format includes at least:

```text
sample_rate
channels
sample_format / bits_per_sample
```

Natural and Supertonic may use different sample rates.

---

## 20. Submission ownership

When native submission returns successfully:

**native has copied everything it needs.**

This includes:

* PCM bytes/samples
* boundary array
* associated request metadata

Python/NumPy does not need to retain the input buffer after return.

This is the C ABI ownership rule, not a claim that XAudio2 copies the sample
payload. The native session retains its own PCM storage until XAudio2 reports
that the corresponding buffer is no longer in use.

---

## 21. Boundary representation

Each supplied boundary contains conceptually:

```text
frame_offset
text_position
text_length
```

`frame_offset`:

* relative to the submitted PCM segment

Text positions:

* relative to the complete spoken request

For Natural Voice adaptive chunks, Python supplies the complete-text base offset to native synthesis.

Native converts chunk-relative SDK positions into complete-request text positions.

---

## 22. Boundary validation

Before accepting a submission:

* `frame_offset` values must be monotonic
* `frame_offset` must not exceed submitted segment frame count
* text positions/lengths must fit the complete request text
* duplicate frame offsets preserve input order

Invalid boundaries must either:

* reject the submission explicitly

or, if a specifically documented policy is chosen:

* return/report that they were dropped

Never silently corrupt timing data.

Prefer rejecting invalid input during development because it exposes upstream bugs.

---

# Buffered runway

## 23. Buffered frames are telemetry, not synchronization

Python adaptive chunking and diagnostics may still use current playback runway.
Return `buffered_frames_after_submit` from submission/synthesis results, or expose
an equivalent request-scoped telemetry query if measurements justify it.

Do not require a separate `wait_for_capacity()` ABI or use `buffered_frames` as
a two-step wait/enqueue protocol. One interruptible bounded `submit` operation
owns admission and avoids that race.

---

## 24. Buffer thresholds are sample-rate relative

Backpressure values are expressed conceptually in seconds but stored/compared in frames.

The feasibility check supplies provisional starting values:

```text
high_water_frames = sample_rate × 3
low_water_frames  = sample_rate × 1
capacity_frames   = sample_rate × 4
```

Do not assume Natural and Supertonic share a sample rate. The existing
Supertonic path polls above 12 buffered seconds, while Natural's adaptive
controller uses a `0.68` runway safety factor. These are migration reference
points, not the final native defaults.

---

# Backpressure policy

## 25. Backpressure stays outside low-level device mechanics

Use interruptible bounded admission. High/low-water hysteresis is the intended
first implementation but not an ABI promise. The provisional values above may
be tuned by Package H/J from measurements. The required invariant is:

```text
0 <= low_water_frames < high_water_frames <= capacity_frames
```

Rules:

* structural silence counts toward buffered duration
* pause must not allow synthesis to fill indefinitely
* large Supertonic segments are sliced into bounded submissions without
  changing inference or waveform content
* cancellation, supersession, failure, stop, and close wake blocked producers
  immediately

XAudio2 buffer-completion notifications wake blocked producers. Do not poll
XAudio2 queue state as the normal backpressure mechanism.

---

# Natural Voice synthesis contract

## 26. Natural synthesis operation

Conceptually:

```text
ss_voice_synthesize_to_audio(
    audio_request,
    request_id,
    text,
    text_base_offset
)
```

The call may block until **that one adaptive text chunk has finished synthesizing**.

It must not wait for audio playback to drain.

---

## 27. Natural synthesis return value

Return at least:

```text
status
generated_frames
synthesis_duration
buffered_frames_after_submit
```

This allows Python to preserve:

* `GenerationStatistics`
* adaptive chunk-size calculations
* synthesis telemetry
* existing logging behaviour

If useful, return a fixed result structure rather than several follow-up native queries.

---

## 28. Natural threading rules

* PCM stays native
* word boundaries stay native until playback reaches them
* played-word callbacks originate from the native request event path
* stop remains callable from another Python thread while synthesis is blocked
* native locks must not be held while Python callbacks execute
* stop coordinates:

  * synthesis cancellation
  * playback stop
  * boundary discard
  * blocked producer wakeup
  * exactly one terminal result

---

# Exact Natural Voice identity

## 29. Voice identity uses package + exact SDK voice

Stable Natural Voice identity contains:

```text
package_path
+
sdk_voice_name
```

Package path alone is not sufficient.

This change must be separately reviewable because it affects:

* voice discovery
* Python keys
* WinUI option identity
* persisted settings
* native initialization

---

## 30. Existing selection migration

If an existing persisted setting contains only package path:

* if that package resolves unambiguously to one voice, migrate automatically
* if multiple voices exist in the package, use a deterministic documented fallback, preferably the same voice that legacy behaviour previously selected
* persist the new exact identity once resolved

Do not silently select a random voice.

---

# Playback abstraction

## 31. Stable Python `PcmPlaybackSession`

Create one narrow abstraction that survives migration.

Conceptually:

```text
create(request_id, format, callback)
submit
submit_silence
finish_input
pause
resume
stop
close
```

`submit` performs interruptible bounded admission and may return buffered-frame
telemetry. The abstraction does not expose a separate capacity wait.

Events:

```text
started
played_word
terminal
underrun/error
```

### Supertonic

Python directly uses:

```text
submit
submit_silence
```

because Python owns Supertonic PCM.

### Natural Voice

Python does not submit Natural PCM.

It supplies text/request metadata and the native audio-request handle to native synthesis.

---

# Critical implementation path

# Phase A — Baseline and telemetry

## A1. Behaviour baseline

Preserve:

* Natural speech
* Supertonic speech
* SAPI speech
* playback-time highlighting
* pause/resume
* stop
* repeat-hotkey stop
* superseding speech
* stale-result rejection
* voice/backend switching
* fallback
* shutdown
* OCR/input
* WinUI playback state

## A2. Type-check baseline

Ideally fix the existing small set of `ty` diagnostics now if doing so does not broaden scope.

Otherwise:

* record exact diagnostic count
* record exact files/locations
* after every package require:

  * no count increase
  * no location drift caused by this project
  * no new production diagnostics

Final audio acceptance requires a completely passing type check.

## A3. Baseline telemetry

Record:

* PCM callback count
* callback-size distribution
* total PCM bytes
* maximum pending bytes
* WaveOut loop iterations
* position-query count
* blocks prepared/written
* runway median/P95/max
* first-audio latency median/P95
* stop-to-silence
* highlight callback delay
* capacity wait duration
* underruns
* playback/idle CPU
* thread count during playback
* thread count after shutdown

## A4. Preserve results

Temporary instrumentation may later be deleted.

The baseline results themselves must remain in a short engineering report/release-evidence document so final performance can be compared after old WaveOut is gone.

---

# Phase B — Lifecycle and ownership

Implement:

* authoritative application shutdown
* backend deterministic close/join
* `VoiceController` sole speaker ownership
* immutable request lifetime rules

Moving the physical `PlaybackSession` file under `app` is optional here.

Do it only if trivial.

Logical ownership matters; package relocation must not become a blocker.

If deferred, perform the physical move during post-audio Python cleanup.

---

# Phase C — Interface-design checkpoint

**Do not begin implementation of the new request/audio interfaces until this checkpoint is reviewed and frozen.**

The checkpoint fixes XAudio2 as the Windows playback foundation. Its focused
feasibility evidence validates one persistent engine/mastering voice, one source
voice per request, incremental PCM, latency-corrected word timing, pause/resume,
prompt destruction, supersession, buffer reclamation, and callback quiescence.
See the [XAudio2 feasibility report](architecture-roadmap/reports/package-c-xaudio2-feasibility.md).

Freeze these SelectSpeak-visible outcomes together:

* `uint64 request_id`
* terminal statuses
* callback ordering
* lifecycle semantics
* PCM format
* frame units
* boundary representation
* boundary validation
* submission ownership
* native error model
* opaque handle lifecycle
* bounded producer admission
* optional buffered-frame telemetry meaning
* Natural synthesis result structure
* callback threading/reentrancy
* exact shutdown guarantees

Do not freeze XAudio2's private queue layout, dispatcher topology, hysteresis
algorithm, or exact capacity tuning. Packages D through J must not
independently redesign the visible rules or replace XAudio2 without reopening
Package C.

---

# Phase D — Request/completion model

Implement:

* application-issued `uint64 request_id`
* immutable identity through every layer
* terminal status truth table
* ordered callbacks
* exactly-once terminal delivery
* remove per-request `SpeechWait` threads

Backend generations may remain internally where useful but are no longer the application's request identity.

---

# Phase E — Simplify `PlaybackController`

Simplify only after Phase D is stable.

Target approximately:

```text
Condition
latest pending request | None
active request
request/generation state
pending control command
paused
failed
closed
```

Where safe:

* remove queue draining
* remove redundant pause/resume Event objects

Preserve behaviour exactly.

---

# Phase F — Centralize native ABI

Implement:

* shared ABI declaration
* error/status definitions
* audio handle declarations
* callback definitions
* API version bump
* Python/native version tests
* matching native DLL staging for integration tests

---

# Phase G — Native PCM session abstraction

Implement PcmPlaybackSession against the new native XAudio2 path.

Backend code must not depend directly on Python WaveOutPlayer.

Python WaveOut remains legacy code only until the native path is proven and switched on. Do not build a compatibility adapter between the old and new playback systems.

No:

WaveOut implementation of PcmPlaybackSession
compatibility wrapper
dual playback abstraction
effort spent making WaveOut conform to the new architecture

Instead the migration becomes:

existing WaveOut path
→ remains untouched temporarily

while separately building:

new PcmPlaybackSession
→ native C++
→ XAudio2

Then integration moves Natural/Supertonic onto the new path.

Once the new path passes the Package A comparisons:

delete WaveOut

---

# Phase H — Backpressure

Define bounded, interruptible submission through `PcmPlaybackSession`; implement
its native wakeup and capacity accounting with the XAudio2 request in J.

Natural and Supertonic use the final interface.

No new polling loops.

---

# Phase I — Asynchronous played-word/UI delivery

Do this **before any native played-word callback is introduced**.

Audio/backend callback:

```text
callback
→ validate request_id
→ enqueue UI update
→ return
```

A separate WinUI writer performs pipe I/O.

Do not expand this phase into broad WinUI cleanup.

---
# Phase J — Native PCM engine

Implement the thin SelectSpeak session over XAudio2:

* one persistent XAudio2 engine/mastering voice
* one opaque handle and fresh source voice per request
* normal PCM retained until `OnBufferEnd`; cancelled PCM retained until
  `DestroyVoice()` returns
* callback-to-dispatcher signalling with no Python work on XAudio2 threads
* active-request position with reported-output-latency correction
* event-driven boundary scheduling
* bounded producer signalling
* pause/resume/stop
* deterministic close
* session-specific failure reporting and device-failure translation

Do not implement raw WASAPI, a custom WaveOut engine, source-voice pooling, or a
second general-purpose audio engine. Stop/supersede settlement destroys the
request source voice and does not depend on `FlushSourceBuffers` callback order.


---

## J1. Deterministic fake audio sink

Separate scheduler/session logic from the real XAudio2 sink.

Tests must run without physical speakers.

Required tests include:

* normal prebuffer
* short input below prebuffer
* request-scoped source-voice lifetime
* bounded submission
* pause/resume frame progression
* word timing
* stop during playback
* stop while paused
* stop while capacity blocked
* boundary ordering
* duplicate-boundary ordering
* final-frame boundary
* invalid boundary rejection
* stale request rejection
* submit after stop
* underrun start/end
* XAudio2 voice/device failure
* exactly-once terminal
* callback ordering
* callback reentrancy
* close during playback
* no callback after close
* blocked submission wake on stop
* blocked submission wake on close

Keep a separate real XAudio2 Windows smoke test.

---

# Phase K — Natural Voice integration

Connect native Natural synthesis directly to native audio.

Remove Natural PCM callbacks into Python.

Implement:

* native PCM path
* native boundary scheduling
* Natural synthesis result structure
* stop/cancellation coordination
* callback ordering
* request identity

---

## K1 — Exact Natural Voice identity

Treat exact voice identity as a separately reviewable subpackage.

Implement:

* package path + SDK voice name key
* persistence migration
* UI identity update
* native initialization alignment

Do not mix unrelated voice UI changes into K.

---

# Phase L — Supertonic integration

Keep inference unchanged.

Change transport only:

```text
PCM
boundaries
request_id
    ↓
native bounded submission
```

Native copies data before return.

Use native silence-frame queueing where practical.

---

# Phase M — Dual-path rollout

The Python/native playback switch is strictly:

* development/test-only
* not persisted in user settings
* preferably environment-variable or dependency-injection controlled

Rollout stages:

### M1 — Native opt-in

Old Python playback remains default.

Native path is explicitly enabled for testing.

### M2 — Native default soak

Native becomes default.

Old Python playback remains emergency-selectable for development/testing.

Compare both implementations using the same workloads.

### M3 — Acceptance

Native must pass behavioural/performance acceptance.

### Package N

Deletes:

* old playback
* switch
* fallback support

The application must not permanently support two PCM playback engines.

---

# Phase N — Delete Python WaveOut

Delete:

* Python WaveOut thread
* WinMM ctypes structures
* WinMM ctypes calls
* Python WaveOut buffers
* polling
* boundary polling
* block preparation
* temporary adapter
* dual-path switch
* temporary old-path instrumentation

Do not leave dormant compatibility code.

---

# Phase O — Audio acceptance

Compare against Phase A baseline.

Verify:

* first-audio latency
* buffered runway
* highlighting timing
* stop-to-silence
* CPU usage
* thread count
* underruns
* pause/resume
* cancellation
* repeat-hotkey stop
* superseding requests
* voice/backend switching
* shutdown
* no stale callbacks
* no callbacks after close
* OCR/input unaffected

Require:

* full unit/integration suite passing
* Ruff passing
* full `ty` passing
* native deterministic tests passing
* Windows WaveOut smoke passing
* Natural smoke
* Supertonic smoke
* SAPI smoke
* WinUI highlighting smoke
* shutdown/restart smoke

Update the engineering comparison report with final metrics before deleting temporary instrumentation.

This marks completion of the main audio migration.

---

# Speech-debug decision before native rollout

The native audio API deliberately does not include old debug-marker scheduling.

Before Phase J/K, explicitly choose:

## Option A — Remove speech debug

Preferred if the feature is not currently user-visible.

Remove remaining:

* setting/config plumbing
* application callbacks
* UI no-op methods
* tests for the obsolete feature

Handle existing persisted `speech_debug_enabled` safely.

Mention the user-visible removal in the changelog if appropriate.

## Option B — Temporarily exclude it from native playback

If the feature is intentionally being retained for future work, document that the native rollout does not reproduce the currently non-rendered debug markers.

Do not accidentally discover this discrepancy during dual-path comparison.

Note:

Any WaveOut-specific debug-marker machinery removed with Python WaveOut in Phase N must **not** be requested for deletion a second time in the later debug cleanup.

---

# Separate Project 1 — SAPI event conversion

Do this after Phase O unless measurements justify doing it sooner.

SAPI owns its own audio and does not depend on the native PCM migration.

Eventually replace:

* idle worker polling
* 10 ms playback polling
* repeated status/word queries
* polling completion
* structure-pause polling

with:

* blocking idle wait
* SAPI Word events
* SAPI EndStream events
* explicit pause/resume/stop
* close/cancel wakeup
* condition/timer-based pause-aware delays

Try Python COM events first.

Only consider native SAPI if Python event handling proves unreliable.

---

# Separate Project 2 — Broader WinUI cleanup

Only asynchronous played-word delivery belongs on the critical audio path.

After audio acceptance, consider:

* persistent pipe reads
* remove idle 20 ms polling
* complete reconnect-state restoration
* obsolete Tk-era interface removal
* dead renderer methods
* stale comments/contracts

Keep separate from native PCM implementation.

---

# Separate Project 3 — Post-audio Python architecture cleanup

After Phase O:

## Configuration

* remove unused config view models
* make `_config` authoritative
* move runtime-path policy out of config data
* avoid unnecessary settings rewrites

## Package structure

* physically move `PlaybackSession` under `app` if not already done
* collapse one-module infrastructure package where useful

Do not duplicate the `PlaybackSession` relocation if it was already completed during Phase B.

## Dependency direction

* input capture returns raw text
* app performs speech preparation
* neutral voice models
* config independent of runtime filesystem policy
* clean import cycles

## Entry points

* remove redundant forwarding layers
* move packaging probes out of normal application startup

## Supertonic installation

Consolidate dependency/model/installer readiness into one focused component.

Do not create a generic plugin framework.

---

# Separate Project 4 — Measurement-only optimization

Only investigate with profiling evidence.

Possible future work:

* Supertonic NumPy allocation reduction
* persistent audio device
* WASAPI
* adaptive chunk retuning
* native SAPI if genuinely needed

Do not include these in the native PCM migration.

---

# Package map

The phase and package letters intentionally align.

## Package A — Baseline

* behavioural baseline
* telemetry
* diagnostic baseline
* persistent engineering results

## Package B — Lifecycle/ownership

* application shutdown
* backend close/join
* VoiceController ownership

## Package C — Interface-design checkpoint

* freeze SelectSpeak-visible contracts before coding
* validate and select XAudio2 as the playback foundation

## Package D — Request/completion

* `uint64 request_id`
* statuses
* ordering
* remove wait threads

## Package E — PlaybackController

* simplify synchronization/state

## Package F — Native ABI

* centralize declarations
* errors
* versioning

## Package G — PCM abstraction

* stable `PcmPlaybackSession`

## Package H — Backpressure

* interruptible bounded submission
* optional buffered-frame telemetry

## Package I — Async UI delivery

* non-blocking played-word callbacks

## Package J — Native PCM engine

* request-scoped handles/source voices
* thin XAudio2 playback sink
* deterministic tests

## Package K — Natural integration

* native synthesis → native playback

### Package K1 — Exact Natural identity

* package + SDK voice
* persistence migration

## Package L — Supertonic integration

* PCM/boundary native enqueue

## Package M — Dual-path rollout

* opt-in
* native-default soak
* comparison

## Package N — Delete Python WaveOut

* delete old engine
* delete adapter
* delete rollout switch

## Package O — Audio acceptance

* final validation
* final engineering comparison

---

# Implementation rules for AI agents

## Rule 1 — Check whether code will be deleted

Do not heavily optimize something scheduled for removal.

---

## Rule 2 — Package C is authoritative

Later agents may not silently redesign:

* request IDs
* PCM ownership
* terminal statuses
* callback ordering
* frame units
* handles
* boundary semantics
* backpressure
* errors
* shutdown guarantees

Any required contract change must be identified explicitly before implementation continues.
XAudio2 is the chosen device engine; its internal queue/thread mechanics are not
part of the public contract unless Package C explicitly says otherwise.

---

## Rule 3 — Preserve behaviour over optimization

Performance improvements do not justify regressions in:

* highlighting
* speech timing
* pause/resume
* cancellation
* stop
* shutdown
* UI behaviour

---

## Rule 4 — One source of truth

When ownership moves, remove the previous duplicate owner.

---

## Rule 5 — Native callbacks never perform UI I/O

Callbacks may:

* validate
* update small state
* enqueue work

They must return quickly.

---

## Rule 6 — Never invoke Python while native locks are held

Copy needed callback data.

Release native locks.

Then call Python.

---

## Rule 7 — No callback after close

When session/speaker destruction returns, its callbacks are finished permanently.

---

## Rule 8 — Exactly one terminal result

Every accepted request ends exactly once.

---

## Rule 9 — Transitional code has a deletion package

* rollout switch M is deleted by N
* Python WaveOut is deleted by N
* temporary old-path telemetry disappears after O

Do not leave compatibility paths behind.

---

## Rule 10 — Do not broaden scope

During native WaveOut migration do not also:

* switch to WASAPI
* change PCM formats
* redesign adaptive chunking
* redesign UI rendering
* restructure unrelated Python packages

---

## Rule 11 — Validate every package

Do not wait until Phase O to discover regressions.

---

## Rule 12 — Preserve unrelated working-tree changes

Do not revert or rewrite unrelated modifications.

---

## Rule 13 — Fix regressions in the package that introduced them

Do not compensate for one regression by modifying several neighboring systems.

---

# Final architecture

```text
                     ┌─────────────────────┐
                     │    SelectSpeakApp   │
                     │ application/session │
                     └─────────┬───────────┘
                               │
                     uint64 request_id
                               │
                     ┌─────────▼───────────┐
                     │   VoiceController   │
                     │ speaker ownership   │
                     └─────────┬───────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
           ▼                   ▼                   ▼
     Natural Voice         Supertonic            SAPI
        Python               Python              Python
      coordinator           inference          COM/events
           │                   │
       text/request       PCM/boundaries
           │                   │
           ▼                   ▼
      ┌─────────────────────────────────────────┐
      │          Native SelectSpeak DLL         │
      │                                         │
      │ Natural synthesis                       │
      │ Request-scoped PCM handles              │
      │ SelectSpeak request/boundary semantics  │
      │ Persistent engine; source voice/request │
      │ PCM buffer lifetime                     │
      │ Capacity signalling                     │
      │ Played-frame position                   │
      │ Boundary scheduling                     │
      │ Pause / resume / stop                   │
      └──────────────────┬──────────────────────┘
                         │
               ordered request events
                         │
                         ▼
                  Python application
                         │
                 queued UI updates
                         │
                         ▼
                       WinUI
```

The final division is:

**Python owns application meaning, request identity and speech policy.**

**Native owns Windows PCM mechanics and playback timing.**

**Natural synthesis feeds native playback directly.**

**Supertonic inference stays Python and hands completed PCM segments to native.**

**WinUI only renders asynchronously delivered state.**

The most important implementation rule is that the request/completion/PCM contract is frozen before the migration starts. Everything after that should be replacing implementations behind stable seams rather than repeatedly redesigning those seams.

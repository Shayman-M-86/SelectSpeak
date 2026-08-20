# SelectSpeak Unified Architecture and Implementation Plan

## Goal

Implement the recommendations from both the audio-pipeline audit and the Python simplification audit as one coordinated project.

The implementation must avoid:

* rewriting the same subsystem multiple times
* optimizing code that is about to be deleted
* introducing temporary abstractions that are later removed
* changing application behaviour during architectural cleanup
* bundling unrelated behavioural changes into optimization work
* moving code into C++ simply because C++ is faster

The target architecture is:

```text
Python
  application behaviour
  speech policy
  text preparation
  backend selection
  generation/session state
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
WinUI
  rendering
  player UI
  highlighted text
  settings UI
```

## The audio audit strongly supports this division: move PCM playback into native code, but keep normalization, chunking, backend policy, Supertonic inference and application playback semantics in Python.

# Locked architectural decisions

These decisions should be treated as constraints for every later phase.

## 1. Python remains the application coordinator

Keep these Python-owned:

* text normalization
* adaptive text chunking
* punctuation and structural-pause policy
* backend selection/fallback
* `PlaybackSession`
* repeat-hotkey-to-stop behaviour
* generation/stale-result logic
* Supertonic model inference
* Supertonic boundary estimation
* voice/settings persistence
* application UI-state decisions

Do not migrate these into C++.

## 2. Native code becomes the owner of PCM playback

The final native audio subsystem should own:

* PCM device resources
* audio buffers
* prebuffering
* bounded buffering/backpressure
* played-frame position
* word-boundary scheduling
* pause
* resume
* stop/reset
* completion
* underrun detection
* deterministic audio shutdown

This replaces the implementation currently inside Python `WaveOutPlayer`.

## 3. Natural Voice PCM must eventually stay native

Final Natural Voice flow:

```text
Python text chunk
      │
      ▼
C++ Natural Voice synthesis
      │
      ├── PCM ───────────────► native PCM playback
      │
      └── word boundaries ───► native boundary scheduler
                                      │
                                      ▼
                              Python played-word event
```

Do not continue sending Natural Voice PCM into Python once native playback exists.

## 4. Supertonic remains Python-owned but uses native playback

Final Supertonic flow:

```text
Python Supertonic inference
        │
        ▼
PCM segment + boundaries
        │
        ▼
one native enqueue operation
        │
        ▼
native playback
```

Do not migrate Supertonic inference into C++.

## 5. `PlaybackController` stays, but is simplified

Do not delete it.

It owns useful backend-generation/cancellation semantics shared by all three backends.

It may be simplified internally, but its responsibility remains separate from the application-level `PlaybackSession`.

## 6. `VoiceController` becomes the sole speaker owner

`SelectSpeakApp` should not independently own a speaker while `VoiceController` also manages speakers.

`VoiceController` should ultimately own:

* current speaker
* cached speakers
* activation
* backend identity
* speaker shutdown

## 7. There is one normal application lifecycle owner

`SelectSpeakApp.close()` becomes the normal authoritative cleanup path.

It must be:

* idempotent
* safe after partial startup
* responsible for closing all resources it successfully acquired

Startup should use `try/finally` around the application lifecycle.

`atexit` can remain only as last-resort protection.

## 8. Native ABI configuration happens in one place

`NativeBridge` should configure the DLL ABI once.

Input, OCR, Natural Voice and the future audio wrapper should not independently mutate `ctypes` function declarations on the shared DLL.

## 9. WinUI is the only real renderer

Remove the obsolete Tk-era renderer interface instead of preserving dead compatibility.

The Python→WinUI contract should represent only operations actually supported by WinUI.

## 10. Speech-debug plumbing is removed unless it is deliberately made a real WinUI feature

The current production WinUI implementation ignores these diagnostics.

For this implementation plan, assume it is removed.

Do not migrate debug-marker scheduling into the new native audio player just because the old `WaveOutPlayer` contained it.

Normal logging and underrun diagnostics remain.

The current speech-debug feature is effectively dead code.

---

# Phase 0 — Establish the safety baseline

Do this before structural changes.

## Objectives

Create a known-good behavioural baseline so every later phase can be compared against it.

## Preserve these behaviours explicitly

* Natural Voice speech
* Supertonic speech
* SAPI speech
* first-audio startup behaviour
* text highlighting
* highlighting occurs at playback time, not synthesis time
* pause
* resume
* stop
* repeat-selection hotkey stops existing speech
* replacing speech cancels the previous generation correctly
* stale completion cannot alter current playback
* backend switching
* backend fallback
* voice switching
* normal application shutdown
* startup failure cleanup
* WinUI reconnection
* OCR and text capture remain unaffected

## Validation cleanup

Resolve the existing type-checking failures before large structural work so new diagnostics are distinguishable from existing ones.

The Python audit reported passing tests/Ruff but existing `ty` problems.

## Rule

No architecture changes in this phase.

---

# Phase 1 — Remove dead interfaces and transitional architecture

Do cleanup that will otherwise contaminate the new interfaces.

This phase deliberately happens **before** audio API design.

## 1A. Remove dead speech-debug plumbing

Remove the unused production path for:

* speech-debug setting
* debug-panel production integration
* no-op WinUI debug calls
* `WaveOutPlayer` debug markers
* application forwarding of those markers
* dead renderer methods related only to that feature

Retain ordinary logs and underrun logging.

### Why now

The native audio API should not be designed around a feature that is being deleted.

---

## 1B. Shrink the WinUI renderer contract

Remove unsupported Tk-era surface such as:

* obsolete constructor callbacks
* unsupported resize/chrome/resizable operations
* dead capture-complete calls
* dead backend-loading/ready calls
* dead wait methods
* stale Tk comments
* unnecessary runtime-checkable machinery

Keep structural interfaces useful for tests where appropriate.

### Why now

Later played-word and playback-state callbacks need to target the **actual final UI interface**, not an obsolete abstraction.

---

## 1C. Remove duplicated application configuration state

Make `_config` authoritative rather than separately maintaining values such as:

* clipboard mode
* auto-hide
* speech-debug state

Remove unused `_speech_backend` state if backend identity moves to `VoiceController`.

A single helper can update/replace/persist configuration.

---

# Phase 2 — Establish final lifecycle and ownership

Do this before changing backend threads or audio ownership.

## 2A. Give `SelectSpeakApp` authoritative lifecycle ownership

Introduce one idempotent `close()` path that safely handles:

* partially initialized UI
* hotkeys/input
* OCR
* voice controller
* speakers
* native bridge
* tray
* other owned resources

Normal startup/run becomes conceptually:

```text
construct
start
run
finally
    close
```

Do not rely on three independent shutdown owners.

---

## 2B. Add an explicit `close()` lifecycle to speech backends

Extend the speaker contract so every backend has deterministic shutdown.

Each backend must be able to:

1. reject new work
2. cancel active work
3. wake a blocked worker
4. terminate the worker
5. join the worker
6. release backend-specific resources

Natural Voice:

* native synthesis/audio resources

Supertonic:

* worker/model-owned resources as appropriate

SAPI:

* COM worker/resources

The audits specifically found that the current daemon workers remain blocked rather than being explicitly shut down.

---

## 2C. Give `VoiceController` sole speaker ownership

Move current/cached speaker ownership into `VoiceController`.

Eliminate:

* initial create-then-adopt ceremony
* duplicated current-speaker ownership
* backend identity based on class-name inspection
* unnecessary activation callback parameters
* application-level speaker shutdown loops

`VoiceController.close()` should close all owned speakers.

### Important

Complete this ownership change **before** native playback sessions are attached to speakers.

That avoids rewriting audio cleanup twice.

---

# Phase 3 — Stabilize the final backend completion contract

Do this before replacing audio playback.

## Goal

Remove the need for one `SpeechWait-<generation>` thread per utterance and establish the completion mechanism the native audio player will eventually use.

## Final completion model

Backends report completion using something equivalent to:

```text
backend
generation
status
```

The application remains responsible for deciding whether the completion still belongs to the active `PlaybackSession`.

Generation/stale-result protection stays intact.

## Requirements

Completion must distinguish at least:

* normal completion
* cancellation
* failure

Do not allow stale generations to mutate current UI/application state.

## Why before native audio

The native player will naturally produce completion events.

If the application is still built around temporary waiting threads when native audio arrives, the integration would immediately need another rewrite.

---

# Phase 4 — Simplify `PlaybackController` around the final semantics

Now simplify backend request management.

The current implementation combines:

* condition
* queue
* two events
* generation counters
* active state
* completed state
* pause state

while deliberately throwing away older queued requests.

## Target internal model

Use one synchronization authority containing approximately:

```text
Condition

latest pending request or None
current generation
active generation
completed generation
pending command
paused state
failed state
closed state
```

Replace the queue-drain mechanism with a latest-request slot.

Replace separate pause/resume `Event`s with one pending command/state mechanism if behaviour can be preserved exactly.

## Critical requirement

Do not change:

* latest-request-wins semantics
* cancellation generation behaviour
* pause/resume ordering
* stale generation rejection

## Why here

By this point lifecycle and completion semantics are settled, so the controller can be simplified once against the final model.

---

# Phase 5 — Centralize the native ABI

Do this immediately before adding the audio API.

## NativeBridge becomes responsible for

* DLL loading
* API version verification
* all `argtypes`
* all `restype` declarations
* shared error-buffer helpers
* shutdown access
* capability creation

Individual wrappers remain responsible for:

* callbacks
* Python object lifetime
* subsystem-specific state

but not DLL-global function declaration.

## Also decide/process one-DLL ownership

If production supports only one SelectSpeak native library in a process, make that explicit rather than pretending multiple unrelated DLL paths are supported.

### Why here

The new PCM API should be added directly to the centralized ABI rather than reproducing the current fragmented pattern.

---

# Phase 6 — Define the final PCM playback contract

This is the architectural seam that prevents the audio migration from forcing another backend rewrite.

## Create one stable playback-session interface

Natural Voice and Supertonic should interact with the concept of a PCM playback session rather than directly with Python `WaveOutPlayer` implementation details.

The final contract should support:

* begin session/generation
* enqueue PCM
* enqueue PCM together with word boundaries
* enqueue silence by frame count
* finish input
* wait for buffer capacity
* query buffered duration/frames if genuinely needed
* pause
* resume
* stop
* close/shutdown

Callbacks/events:

* playback started
* played word
* playback completed
* playback error
* underrun diagnostic

## Critical design rule

Design this interface for the **final native implementation**, not around limitations of the old Python `WaveOutPlayer`.

The Python implementation is temporary.

---

# Phase 7 — Introduce bounded audio backpressure

Now address the Natural Voice runaway buffering.

Telemetry found:

* roughly 40 seconds average runway
* over 206 seconds maximum
* no observed underruns

## Desired behaviour

Natural Voice should stop synthesizing additional chunks once playback has a healthy amount of queued audio.

Initial policy can be around:

**8–12 seconds maximum buffered runway**

but keep it configurable/internal so it can be tuned from measurement.

## Waiting must be event/condition driven

Do not add another polling loop.

Conceptually:

```text
if buffered audio is above limit:
    wait until:
        playback consumes enough audio
        OR request is cancelled
        OR session stops
```

## Supertonic

Replace its current 20 ms buffer-capacity polling with the same capacity-wait concept.

## Important anti-rewrite rule

Implement backpressure through the stable playback interface from Phase 6.

Do not embed new backpressure behaviour directly into Python WaveOut internals.

That way the exact same backend logic survives the native migration.

---

# Phase 8 — Implement the native event-driven PCM player

This is the main audio architecture change.

## Preserve behaviour first

Initially preserve:

* current PCM format
* current 100 ms effective block behaviour where useful
* current 200 ms startup prebuffer behaviour
* existing volume semantics
* existing word-highlight timing
* pause/resume behaviour

Do not combine this migration with an audio-quality or latency retuning exercise.

## Native implementation owns

* WaveOut device
* reusable native PCM buffers
* prepared headers
* buffer queue
* device completion signalling
* played-frame accounting
* boundary queue
* capacity signalling
* pause/restart
* reset/stop
* close
* underrun timing

## Make WaveOut event-driven

Use Windows completion events/callbacks instead of Python's current 2–5 ms polling loop.

The existing Python loop can wake hundreds of times per second despite no observed underruns.

## Do not switch to WASAPI yet

The immediate goal is:

**same behaviour, better ownership**

WaveOut is already working.

A WASAPI migration is a separate future optimization and should not be mixed into this structural migration.

---

# Phase 9 — Route Natural Voice directly into native playback

Once native PCM playback is independently validated, connect Natural Voice to it.

## Remove this path

```text
Speech SDK PCM
→ C++ callback
→ Python ctypes callback
→ Python bytes
→ Python bytearray
→ Python 100 ms block
→ ctypes buffer
→ WaveOut
```

The current pipeline creates multiple avoidable PCM copies.

## Replace with

```text
Speech SDK PCM callback
        │
        ▼
native PCM session
```

## Word boundaries

Natural Voice SDK boundary events remain native until the corresponding audio position is reached.

Only then call Python with:

```text
generation
text position
length
```

This leaves approximately one meaningful Python callback per spoken word, which is already low-frequency and worth keeping.

## Stop

Define one deterministic cancellation sequence covering:

* synthesis cancellation
* PCM playback cancellation
* pending boundaries
* completion status

Avoid the current separate loosely coordinated Python playback stop and native synthesis stop.

---

# Phase 10 — Route Supertonic through native playback

Do this only after Natural Voice validates the native player.

## Keep unchanged

* model loading
* ONNX execution
* adaptive chunking
* waveform generation
* silence trimming
* word-boundary estimation

## Change only transport

Instead of feeding Python WaveOut:

```text
prepared PCM segment
+
boundary array
+
generation
        │
        ▼
native enqueue
```

Prefer one enqueue per prepared/adaptive segment rather than Python-created 100 ms audio blocks.

## Silence

Where practical, tell the native player to enqueue a number of silent frames rather than creating large zero-filled Python `bytes`.

---

# Phase 11 — Remove the old Python WaveOut implementation

Only after both Natural Voice and Supertonic use native playback successfully.

Now delete rather than optimize:

* Python WaveOut polling thread
* ctypes WaveOut structs
* ctypes WaveOut function calls
* Python WaveOut header management
* pending PCM bytearray
* Python buffer completion polling
* Python boundary polling
* Python 100 ms block creation
* associated temporary compatibility code

## Important

This is why the earlier recommendations to convert WaveOut lists/bytearrays to `deque` should **not** be treated as a major standalone refactor.

Those optimizations are valid if Python WaveOut remains for a long period, but once native migration is committed they are transitional work.

Only make minimal temporary improvements needed for correctness/migration.

---

# Phase 12 — Decouple UI writes from playback callbacks

Currently a word callback can reach a synchronous named-pipe write and therefore potentially stall the thread reporting audio progress.

## Create one outbound WinUI writer

Application/UI updates enqueue messages.

One bridge-owned writer sends them.

Guarantee ordering for stateful messages.

For highlights:

* stale unsent highlight events may be coalesced if necessary
* the newest highlight is what matters when the UI falls behind

## Result

Native audio event:

```text
played word
   ↓
small Python callback
   ↓
queue UI update
   ↓
return immediately
```

No pipe I/O on the audio callback path.

---

# Phase 13 — Make the rest of the WinUI bridge event-driven

Remove unnecessary idle polling.

The audit found:

* Python UI loop waking around every 20 ms
* pipe read repeatedly cancelled/recreated after idle timeout

## Replace with

* wake event for scheduled Python UI work
* persistent pipe read
* shutdown closes/cancels the read
* one pipe instance if only one WinUI process is supported

Also ensure reconnection restores:

* settings
* shortcut
* current text
* current playback state

not only part of the application state.

---

# Phase 14 — Replace SAPI polling with events

SAPI is separate from the native PCM player because it owns its audio itself.

Currently it polls COM state roughly every 10 ms.

## First implementation choice

Use SAPI word and end-stream events from Python with an appropriate COM message/event mechanism.

Events should drive:

* played-word updates
* stream completion

Pause/resume/stop remain explicit controls.

## Only move SAPI native if necessary

Do not create a native SAPI implementation unless the Python event model proves unreliable or excessively complex.

---

# Phase 15 — Finish Python ownership/dependency simplifications

At this point the audio interfaces are stable. Structural cleanup can happen without touching them again.

## 15A. Remove one-class `audio` package

Move application-level `PlaybackSession` under `app`.

Do not merge it with backend `PlaybackController`; they represent different scopes.

---

## 15B. Collapse the one-module infrastructure package

Move logging to a simpler appropriate module.

---

## 15C. Remove unused config view models

Remove unused:

* `InputConfig`
* `UiConfig`
* associated properties/re-exports

Keep useful narrowed speech configuration.

---

## 15D. Make configuration environment-independent

Move runtime path calculation out of configuration data models.

---

## 15E. Consolidate Supertonic installation modules

Combine the currently scattered optional-dependency/model/installer concerns into one focused Supertonic installation component.

Do not invent a general plugin framework.

---

## 15F. Correct dependency direction

Aim for:

```text
app composes everything

domain/value models
        ↑
speech/input/platform adapters
        ↑
native/platform-specific implementation
```

Specific cleanups:

* input capture should return raw text rather than importing speech normalization
* move `NaturalVoice` value information to a neutral voice model if needed
* config models should not depend on filesystem policy
* clean package-level import cycles

---

## 15G. Collapse redundant entry points

Keep one clear startup path rather than forwarding through several `main()` layers.

---

## 15H. Move packaging probes out of product startup

Release/build verification logic should live with build tooling rather than branching inside normal application startup.

---

# Phase 16 — Smaller safe cleanups

After the architecture is stable, review the remaining low-risk findings.

Examples from the audit include:

* remove ignored backend-loading/ready messages
* remove unused `activity` parameters
* remove unused voice refresh/properties where confirmed
* remove unreachable OCR-null branches
* avoid rewriting settings on startup when unchanged
* use explicit backend identity instead of class-name inspection
* narrow overly broad Natural Voice fallback exception handling
* align Python-version metadata with the versions actually supported/tested

These should be individual, behaviour-preserving cleanups.

---

# Phase 17 — Performance work that requires measurement

Do not mix these into the main migration.

Only investigate after the architecture above is stable.

## Supertonic NumPy

Potentially:

* reduce temporary arrays
* in-place clip/scale where ownership permits
* reuse int16 output storage
* avoid redundant dtype conversions

But model inference likely dominates, so profile first.

## Keeping audio device open

Measure before changing device lifetime.

## WASAPI

Only investigate after event-driven native WaveOut is proven insufficient.

Do not migrate simply because WASAPI is newer.

## Native SAPI

Only if Python SAPI events are problematic.

## Adaptive chunk sizing

Re-evaluate only after bounded backpressure exists, because previous telemetry was distorted by enormous buffered runway.

---

# Things explicitly NOT to optimize/rewrite

Do not:

* move normalization into C++
* move adaptive chunking into C++
* move backend fallback policy into C++
* move repeat-hotkey logic into C++
* move `PlaybackSession` into C++
* move Supertonic inference into C++
* remove one played-word callback purely to reduce crossings
* replace JSON UI messages solely for micro-performance
* optimize voice-option sorting
* optimize tiny dataclass allocations
* combine an entire Natural Voice request into one synthesis operation
* create a large Natural/Supertonic inheritance hierarchy
* merge application `PlaybackSession` and backend `PlaybackController`
* rewrite WaveOut to WASAPI during the native migration
* reintroduce dead speech-debug plumbing into the new audio system

These either provide little benefit or risk altering behaviour.

---

# Work-package boundaries

The agent should treat these as separate implementation units.

Each unit must build/test before proceeding.

## Package A — Baseline

* tests/type-check baseline
* behavioural regression coverage

## Package B — Dead UI/debug cleanup

* speech-debug removal
* WinUI contract cleanup
* config duplicate removal

## Package C — Lifecycle

* `SelectSpeakApp.close()`
* backend `close()`
* deterministic worker shutdown

## Package D — Ownership

* `VoiceController` sole speaker ownership

## Package E — Completion

* completion callbacks/results
* remove `SpeechWait` threads

## Package F — Playback controller

* simplify synchronization/state

## Package G — Native ABI

* centralize DLL declarations/error helpers

## Package H — Playback interface/backpressure

* stable PCM session contract
* Natural bounded runway
* Supertonic condition-driven capacity

## Package I — Native PCM engine

* event-driven WaveOut player
* independent tests

## Package J — Natural integration

* native synthesis → native audio
* native word scheduling

## Package K — Supertonic integration

* segment/boundary enqueue

## Package L — Delete Python WaveOut

* remove transitional audio implementation

## Package M — UI event path

* asynchronous writer
* event-driven bridge

## Package N — SAPI events

* remove polling

## Package O — Python structural cleanup

* packages
* configuration
* dependencies
* entry points
* Supertonic installation

## Package P — Measurement-only optimization

* Supertonic NumPy
* WASAPI
* audio-device persistence
* other measured improvements

---

# Rules for the AI agent while implementing

## Rule 1 — Do not jump ahead

Before changing a subsystem, check whether a later phase replaces it.

If it will be deleted, do not heavily refactor it now.

## Rule 2 — Preserve behaviour over optimization

A measurable performance improvement is not acceptable if it causes intermittent rendering, timing or lifecycle regressions.

## Rule 3 — One source of truth

Whenever ownership is consolidated, remove the previous duplicate owner rather than keeping both synchronized.

## Rule 4 — Avoid transitional APIs becoming permanent

Any compatibility layer introduced during migration should be marked for deletion in the exact later package that supersedes it.

## Rule 5 — Do not broaden scope within a package

Example:

While implementing native WaveOut, do not also:

* switch to WASAPI
* change audio format
* change chunk policy
* change highlighting semantics

## Rule 6 — Validate after every package

Do not wait until the whole architecture migration is complete to test.

## Rule 7 — Preserve unrelated working-tree changes

Do not revert or rewrite unrelated work.

## Rule 8 — Investigate regressions against the package that introduced them

Do not respond to a regression by changing several neighboring systems at once.

---

# Final expected architecture

When all planned work is complete:

```text
                       ┌─────────────────────┐
                       │    SelectSpeakApp   │
                       │ application/session │
                       └─────────┬───────────┘
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
             │ text chunk         │ PCM + boundaries
             ▼                   ▼
       ┌───────────────────────────────────────┐
       │          Native SelectSpeak DLL       │
       │                                       │
       │ Natural synthesis                     │
       │ Native PCM playback                   │
       │ Event-driven WaveOut                   │
       │ PCM buffers/backpressure               │
       │ Played-frame position                  │
       │ Boundary scheduling                    │
       │ Pause / resume / stop                  │
       └──────────────────┬────────────────────┘
                          │
                played-word/state events
                          │
                          ▼
                 Python application
                          │
                    queued UI state
                          │
                          ▼
                       WinUI
```

The important separation is:

**Python owns meaning and policy.**

**Native owns Windows audio mechanics and timing.**

**WinUI owns rendering.**

That is the common direction supported by both audits, while the ordering above prevents the Python simplification work from refactoring components immediately before the audio migration replaces them.

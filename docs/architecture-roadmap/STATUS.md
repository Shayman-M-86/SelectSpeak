# Architecture Roadmap Status

This is the roadmap’s baton: it tells every new agent what is active, what is
ready, and what success unlocks next. Keep it current, concise, and connected to
each package’s rolling report.

Statuses: `Unassessed`, `Ready`, `Active`, `Blocked`, `Complete`.
`Unassessed` means current code has not yet been checked; it does not mean the work
is absent. A new agent resumes `Active`; otherwise it selects the earliest eligible
`Ready` or `Unassessed` package. Keep at most one package `Active`.

| Package | Focus | Gate or sequencing note | Status | Evidence, blocker, or next action |
| --- | --- | --- | --- | --- |
| A | Baseline and telemetry | First package; preserve results for M | Complete | Repeatable Natural/Supertonic workload, temporary telemetry, clean diagnostics, and durable comparison evidence delivered. [Report](reports/package-a-baseline.md) |
| B | Lifecycle and ownership | Use A behaviour baseline | Complete | Sole speaker ownership, partial-safe ordered shutdown, deterministic backend close/join, and session relocation delivered. [Report](reports/package-b-lifecycle.md) |
| C | Interface checkpoint | Explicit review/freeze before D–J interface work | Complete | Request-scoped XAudio2 feasibility passed 29/29 in three final runs; the maintainer explicitly approved and froze the simplified contract on 2026-08-21. [Report](reports/package-c-interface-checkpoint.md) [Contract](reports/package-c-interface-contract.md) [Evidence](reports/package-c-xaudio2-feasibility.md) |
| D | Request and completion | C Complete with contract Frozen | Complete | Application-issued `uint64` identity, ordered request events, stable terminal statuses, exactly-once settlement, and wait-thread removal delivered. [Report](reports/package-d-request-completion.md) |
| E | `PlaybackController` | D stable | Complete | Condition-protected pending/active request state, one control command, atomic dequeue activation, reentrant ordered delivery, and backend migration delivered. [Report](reports/package-e-playback-controller.md) |
| F | Native ABI | C Complete with contract Frozen; matching DLL and tests required | Complete | Centralized version-7 ctypes/C++ declarations, stable statuses and layouts, safe pre-engine audio symbols, matching staged DLL, and ABI integration coverage delivered. [Report](reports/package-f-native-abi.md) |
| G | PCM abstraction | C Complete with contract Frozen | Complete | Native-only request-scoped session, typed PCM/events, UTF-16/frame validation, callback/lifecycle ownership, and G1 removal delivered without touching legacy WaveOut. [Report](reports/package-g-pcm-session.md) |
| H | Bounded admission | G available; coordinate native wakeup/accounting with J | Complete | Frame-denominated provisional thresholds, boundary-preserving slicing, non-polling `submit_bounded`, and control-thread interruption delivered over `PcmPlaybackSession`. Native capacity accounting and the interruptible wait remain Package J. [Report](reports/package-h-bounded-admission.md) |
| I | Async UI delivery | Before native played-word callbacks | Complete | Active-request validation now precedes queued player-thread highlight delivery, so backend/native callbacks never perform named-pipe I/O. [Report](reports/package-i-async-ui-delivery.md) |
| J | Native XAudio2 requests | F–I seams ready | Complete | Persistent COM/XAudio2 runtime, fresh source voice per handle, bounded 100 ms buffering, event-driven boundaries, deterministic settlement, fake-sink coverage, and 3/3 real-device smokes delivered. [Report](reports/package-j-native-xaudio2.md) |
| K | Natural integration | J ready | Complete | Direct native synthesis/playback, telemetry, cancellation, callback quiescence, producer text-range validation, signed-volume fix, and 100%-volume real-device acceptance are delivered. Native discovery finds six installed voices; focused/full Python checks, Ruff, ty, deterministic native checks, staged smoke, and the product-path request pass. [Report](reports/package-k-natural-integration.md) |
| K1 | Exact Natural identity | K complete | Complete | Versioned package + exact SDK voice keys now drive UI selection, native initialization, exact persistence, and deterministic legacy package-only migration. [Report](reports/package-k1-exact-natural-identity.md) |
| L | Supertonic integration | K1 complete | Complete | Supertonic inference remains Python-owned; PCM, structural silence, estimated boundaries, controls, and terminal settlement now flow through request-scoped bounded native sessions. [Report](reports/package-l-supertonic-integration.md) |
| M | Native cutover, cleanup, and acceptance | L complete | Active | SAPI retirement is now in progress alongside the native-only cutover. WaveOut deletion, 207 Python tests, Ruff, ty, 5/5 native CTest, and silent real-device XAudio2 smoke already pass. [Report](reports/package-m-native-cutover.md) |

## Cross-package decisions

- M is the single final audio-migration package: native cutover, Phase A comparison,
  WaveOut deletion, and clean-tree acceptance. No dual-path rollout, playback
  switch, adapter, or fallback is permitted.

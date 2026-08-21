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
| A | Baseline and telemetry | First package; preserve results for O | Complete | Repeatable Natural/Supertonic workload, temporary telemetry, clean diagnostics, and durable comparison evidence delivered. [Report](reports/package-a-baseline.md) |
| B | Lifecycle and ownership | Use A behaviour baseline | Complete | Sole speaker ownership, partial-safe ordered shutdown, deterministic backend close/join, and session relocation delivered. [Report](reports/package-b-lifecycle.md) |
| C | Interface checkpoint | Explicit review/freeze before D–J interface work | Complete | Request-scoped XAudio2 feasibility passed 29/29 in three final runs; the maintainer explicitly approved and froze the simplified contract on 2026-08-21. [Report](reports/package-c-interface-checkpoint.md) [Contract](reports/package-c-interface-contract.md) [Evidence](reports/package-c-xaudio2-feasibility.md) |
| D | Request and completion | C Complete with contract Frozen | Ready | Implement application-issued `uint64 request_id`, terminal status/order, exactly-once completion, and remove per-request speech-wait threads. |
| E | `PlaybackController` | D stable | Unassessed | Simplify state without pulling in audio migration. |
| F | Native ABI | C Complete with contract Frozen; matching DLL and tests required | Unassessed | Identify and centralize current ABI declarations. |
| G | PCM abstraction | C Complete with contract Frozen | Unassessed | Establish the stable Python playback seam. |
| G1 | Optional WaveOut adapter | G stable; create only if rollout compatibility needs it; deleted by N | Unassessed | Avoid rewriting backpressure or events in code scheduled for deletion. |
| H | Bounded admission | G available; coordinate native wakeup/accounting with J | Unassessed | Add interruptible bounded submission without polling; tune provisional thresholds from evidence. |
| I | Async UI delivery | Before native played-word callbacks | Unassessed | Keep scope to non-blocking delivery. |
| J | Native XAudio2 requests | F–I seams ready | Unassessed | Implement one persistent runtime and one source voice/handle per request, with deterministic fake-sink tests and a real-device smoke. |
| K | Natural integration | J ready | Unassessed | Connect native synthesis directly to native playback. |
| K1 | Exact Natural identity | Separately reviewable; coordinate with K | Unassessed | Limit work to package + SDK voice identity and migration. |
| L | Supertonic integration | J ready | Unassessed | Change transport only; keep inference unchanged. |
| M | Dual-path rollout | K/L integrated | Unassessed | Run opt-in, native-default soak, and comparison. |
| N | Delete Python WaveOut | M acceptance passed | Unassessed | Remove the old engine, adapter, and rollout switch. |
| O | Audio acceptance | Compare with A | Unassessed | Capture final metrics before N removes instrumentation needed for comparison. |

## Cross-package decisions

- During M, schedule O's final measurement capture before N removes any required
  temporary instrumentation. N may then delete the old engine and instrumentation,
  followed by O's remaining clean-tree acceptance checks and final report.

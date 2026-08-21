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
| C | Interface checkpoint | Explicit review/freeze before D–J interface work | Ready | Reconcile the unified-plan contracts with current Python/native seams, record the freeze artifact, then obtain the explicit freeze decision. |
| D | Request and completion | C frozen | Unassessed | Trace identity and completion through the direct path. |
| E | `PlaybackController` | D stable | Unassessed | Simplify state without pulling in audio migration. |
| F | Native ABI | C frozen; matching DLL and tests required | Unassessed | Identify and centralize current ABI declarations. |
| G | PCM abstraction | C frozen | Unassessed | Establish the stable Python playback seam. |
| G1 | Temporary WaveOut adapter | G stable; deleted by N | Unassessed | Implement only what G requires. |
| H | Backpressure | G/G1 available; C policy frozen | Unassessed | Add high/low-water capacity without polling. |
| I | Async UI delivery | Before native played-word callbacks | Unassessed | Keep scope to non-blocking delivery. |
| J | Native PCM engine | F–I seams ready | Unassessed | Include deterministic fake-sink tests and WaveOut smoke. |
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

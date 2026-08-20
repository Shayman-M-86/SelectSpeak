# Architecture Roadmap Execution

Use this guide to continue the
[unified architecture roadmap](../SelectSpeak_Unified_Plan.md). The package
letters describe implementation boundaries; they do not require one agent session
each. [STATUS.md](STATUS.md) is the cursor that tells each new agent where to
resume.

## Generic continuation prompt

Give every implementation agent this same prompt:

> Continue executing the SelectSpeak architecture roadmap. Read
> `docs/SelectSpeak_Unified_Plan.md`,
> `docs/architecture-roadmap/EXECUTION.md`, and
> `docs/architecture-roadmap/STATUS.md`. Use STATUS.md to select or resume the
> current package; do not ask me to choose one unless a recorded gate or
> architectural decision genuinely requires my input. Perform the bounded
> preflight, then Proceed, Adapt, or Escalate according to EXECUTION.md. Make the
> smallest coherent change that advances the selected package, validate it
> proportionally, preserve unrelated working-tree changes, update the package
> report and STATUS.md, and leave a concise handoff. Do not begin work beyond a
> blocked or unmet gate. Do not commit or publish unless explicitly requested.

## Selecting the current package

Use this order:

1. Resume the package marked `Active`.
2. Otherwise select the earliest roadmap package marked `Ready` whose gate is
   satisfied.
3. Otherwise select the earliest `Unassessed` package whose preceding gate is
   satisfied and perform its preflight.
4. Do not skip an earlier `Blocked` package when it gates later work. Report the
   concrete decision needed instead.
5. If status and code disagree, investigate the discrepancy and correct the
   ledger using current evidence.

Mark the selected package `Active` when implementation begins. Keep at most one
package `Active` unless the roadmap explicitly calls for independent concurrent
work.

## Bounded preflight

Before editing, establish:

- the observable result the assignment must produce
- how current code performs that responsibility
- whether the work is absent, partial, complete, or based on a stale assumption
- the direct callers, callees, ownership path, interfaces, and tests involved
- whether affected code is transitional and which later package deletes it
- whether the work conflicts with a frozen Package C contract or a package gate

Investigate proportionally:

| Change | Inspect by default |
| --- | --- |
| Small test, configuration, or cleanup | Target files, implementation under test, and nearby tests |
| Behaviour or ownership | Target implementation, direct dependencies, ownership path, and relevant tests |
| Native or cross-layer contract | That specific path through the necessary Python, C++, and UI layers |

Expand only when concrete code evidence shows that the change reaches farther.
Packages A, C, and O are intentionally broad. Cross-layer packages such as D, F,
G, J, K, and L normally require tracing their specific interface end to end.

## Decide how to proceed

- **Proceed** — the package still matches current code closely enough to implement
  as written.
- **Adapt** — the objective remains valid, but bounded implementation details must
  change while preserving architectural intent and frozen contracts.
- **Escalate** — stop for a decision because a frozen contract must change, a
  material assumption is false, scope expands substantially, ownership would be
  duplicated, or major work would be spent on code scheduled for deletion.

If work is already complete, validate the package outcomes and record the evidence
instead of reimplementing it. Minor differences normally belong under `Adapt`, not
`Escalate`.

## Scope and validation

- Make the smallest coherent change that completely satisfies the assignment.
- Do not clean up neighboring code, redesign later packages, or build speculative
  abstractions.
- Do not optimize transitional code beyond what its migration seam requires.
- Package C contracts are authoritative after explicit review and freeze; do not
  silently redesign them.
- Preserve user-visible behaviour unless the assigned package changes it.
- If behaviour regresses broadly or implementation drifts substantially, compare
  the affected path with the known-good feature-branch commit recorded in the
  unified plan before making broad corrective changes.
- Run tests directly related to changed behaviour, followed by the normal checks
  for the affected area.
- Use full-system checks when required by the package, cross-layer risk, or targeted
  failures. State clearly what could not be run.

## Handoff

When work begins on a package, create or update its one small durable report at:

```text
reports/package-[id]-short-name.md
```

The report is a rolling outcome and handoff artifact, not a session transcript.
Keep it brief:

- **Found:** important differences between roadmap assumptions and current code
- **Changed:** the main implementation results
- **Validation:** checks and outcomes
- **Remaining:** only genuine unfinished work, blockers, or later-package gates

Link the report from [STATUS.md](STATUS.md) and update that package's status,
blocker, and next action after every working session. Use the same four headings
in the agent's final response. When another agent resumes the package, it updates
the existing report rather than creating another session file.

If a package produces a contract freeze, baseline measurements, performance
comparison, or other substantial evidence, store that evidence as its own artifact
under `reports/` and link it from the package report. Do not create daily logs,
raw reasoning records, or command-by-command transcripts.

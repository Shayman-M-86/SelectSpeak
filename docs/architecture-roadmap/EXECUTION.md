# Let’s Execute the Architecture Roadmap

This guide helps each agent pick up the baton, understand the current package,
and turn the roadmap into working, validated software. The
[unified architecture roadmap](../SelectSpeak_Unified_Plan.md) provides the
direction. [STATUS.md](STATUS.md) shows exactly where the work stands.

Package letters are implementation boundaries, not session limits. An agent keeps
working on the current package while safe, actionable work remains.

## The mission

Move the selected package to a real outcome:

1. **Pick up the current work.** Resume `Active`, or select the earliest eligible
   package from `STATUS.md`.
2. **Understand the live implementation.** Trace the code and tests that directly
   carry the responsibility.
3. **Choose the right route.** Proceed, Adapt, or Escalate based on evidence.
4. **Build the package.** Make the code, test, configuration, or measurement
   changes needed to satisfy its outcomes.
5. **Prove the result.** Run focused checks and the broader validation justified
   by the change.
6. **Leave a clear trail.** Update the rolling package report and `STATUS.md` so
   the next agent can continue immediately.

Keep moving until the package is **Complete** or a concrete decision outside the
agent’s authority makes it **Blocked**. A preflight, investigation, partial
baseline, or report is useful progress, but it is not a stopping point while
implementable package work remains.

## Choosing the current package

Use this order:

1. Resume the package marked `Active`.
2. Otherwise, take the earliest `Ready` package whose gate is satisfied.
3. Otherwise, preflight the earliest eligible `Unassessed` package.
4. When an earlier `Blocked` package gates the path, surface the exact decision
   needed to unlock it.
5. When status and code disagree, investigate the difference and bring the ledger
   back in line with current evidence.

Mark implementation work `Active` and keep one package active at a time unless the
roadmap explicitly identifies independent concurrent work.

## A quick, useful preflight

Build a confident picture of:

- the observable result this package must deliver
- the code that currently owns the responsibility
- the exact gap between today’s implementation and the package outcome
- direct callers, callees, ownership paths, interfaces, and relevant tests
- transitional code and the later package responsible for removing it
- frozen Package C contracts and gates that shape the implementation

Match the investigation to the work:

| Change | Useful default depth |
| --- | --- |
| Small test, configuration, or cleanup | Target files, implementation under test, and nearby tests |
| Behaviour or ownership | Target implementation, direct dependencies, ownership path, and relevant tests |
| Native or cross-layer contract | The specific path through the necessary Python, C++, and UI layers |

Follow concrete dependencies when they lead farther. Packages A, C, and O are
intentionally broad; D, F, G, J, K, and L usually need an end-to-end look at their
specific interface.

## Choose the route and act

- **Proceed** — the roadmap matches the live implementation. Build the package as
  designed.
- **Adapt** — the goal is right and implementation details have evolved. Adjust
  the route while preserving the architectural destination and frozen contracts.
- **Escalate** — a genuine design decision is needed because a frozen contract,
  package gate, ownership model, or major roadmap assumption must change. Present
  the concrete evidence and the smallest decision that unlocks progress.

When the package is already partly implemented, validate what exists and finish
the remaining outcomes. When it is already complete, prove that with current
evidence and close it confidently.

## Build with focus

- Deliver the smallest coherent implementation that fully satisfies the package.
- Keep neighboring systems stable and preserve unrelated working-tree changes.
- Give transitional code exactly the seam it needs for migration, with its
  deletion package kept visible.
- Treat reviewed Package C contracts as the shared foundation for later work.
- Preserve today’s working user experience unless the package intentionally
  changes a behaviour.
- When several behaviours regress or the implementation loses its bearings,
  compare the affected path with the known-good feature-branch commit recorded in
  the unified plan and recover the proven semantics.
- Keep commits and publishing as deliberate user-controlled actions.

## Validate like the result matters

Start with tests closest to the changed behaviour. Follow with the normal checks
for the affected area, then use integration or full-system validation when the
package or risk calls for it.

Record what passed, what failed, and what the environment could not exercise. A
targeted check is valuable evidence; label it accurately rather than presenting it
as complete project validation.

## Package report and handoff

Create or update one rolling report for the active package:

```text
docs/architecture-roadmap/reports/package-[id]-short-name.md
```

Keep it crisp and useful:

- **Found:** discoveries that changed or confirmed the approach
- **Changed:** concrete implementation and artifact outcomes
- **Validation:** checks, results, and meaningful limitations
- **Remaining:** exact package work still actionable, or the gate that blocks it

Link the report from [STATUS.md](STATUS.md) and update both after every working
session. A later agent updates the same package report instead of creating a new
session diary.

Store contract freezes, baseline measurements, performance comparisons, and other
substantial evidence beside the package reports and link them. These artifacts
should help future implementation; concise results are far more valuable than raw
reasoning or command transcripts.

## Definition of done

A package is `Complete` when:

- its roadmap outcomes are implemented or proven already present
- relevant tests and checks support the result
- important limitations and later-package dependencies are explicit
- its package report captures the durable outcome
- `STATUS.md` points the next agent to the next eligible work

If safe, actionable work from the package remains, keep implementing it. The
report records the journey; it never substitutes for delivering the package.

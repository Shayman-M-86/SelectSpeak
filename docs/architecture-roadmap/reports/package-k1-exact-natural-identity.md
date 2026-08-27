# Package K1 — Exact Natural Voice Identity

## Found

- `NaturalVoice` already carried both its Windows package path and exact SDK
  voice name, and native initialization already accepts both. The missing seam
  was identity: WinUI option keys and persisted `preferred_voice` values used
  only the package path.
- A legacy package-only setting is ambiguous when a package exposes multiple
  SDK voices. The deterministic migration rule is the lowest case-insensitive
  SDK voice name in that package; the resolved exact key is persisted at
  Natural Voice startup.

## Changed

- Added an opaque, versioned Natural Voice key encoding package path plus SDK
  voice name. It is used consistently for WinUI option identity and persisted
  Natural preferences.
- Voice options carry the exact SDK name; selection now reselects the native
  engine by both package path and SDK name.
- Exact preferences choose the matching SDK voice. Legacy package-only
  preferences choose the documented deterministic fallback and are rewritten
  through the existing settings save path on startup.
- Refreshing voices now keeps the active voice only when that exact identity is
  absent, rather than treating another SDK voice in the same package as equal.

## Validation

- Focused app/settings/Natural Voice/option tests: 36 passed.
- Full Python suite: 211 passed. Ruff and `ty check` passed.

## Remaining

- Package K1 is complete. Package L is next: preserve Supertonic inference and
  change only its PCM/boundary transport to the native request session.

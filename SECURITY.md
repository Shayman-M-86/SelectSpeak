# Security policy

## Supported versions

Security fixes are provided for the latest released version of SelectSpeak.
Older builds should be upgraded before a report is investigated.

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue. Use
[GitHub's private vulnerability reporting form](https://github.com/Shayman-M-86/my-TTS/security/advisories/new)
and include:

- the affected SelectSpeak version;
- the Windows version and relevant configuration;
- reproduction steps and expected impact;
- logs or proof-of-concept material with personal text removed.

Reports will be acknowledged as soon as practical. The maintainer will validate
the issue, coordinate a fix and release, and credit the reporter unless
anonymity is requested. If private vulnerability reporting is temporarily
unavailable, open a public issue containing only a request for private contact,
without vulnerability details.

## Security boundaries

SelectSpeak processes selected text locally and does not intentionally transmit
it. Installer and optional-feature downloads are pinned or SHA-256 verified.
The Natural Voice bridge is a local compatibility layer for speech components
already installed by Windows. It uses internal, version-sensitive Windows
speech interfaces rather than a stable public Microsoft API; this behavior is
documented in the README and should be considered when assessing reports.

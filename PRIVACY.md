# Privacy policy

Last updated: 14 August 2026

SelectSpeak is a local Windows text-to-speech application. It does not include
advertising, analytics, telemetry, user accounts, or an automatic update
checker. The project does not operate a server that receives selected text,
clipboard contents, screenshots, generated speech, settings, or diagnostic
logs.

## Information processed locally

SelectSpeak processes selected text, optional clipboard text, and pixels chosen
with the OCR shortcut on the user's device. OCR uses Windows' local
`Windows.Media.Ocr` API. Speech is generated with a local Windows voice or the
optional local Supertonic model. This content is not sent over the network by
SelectSpeak.

The following data may be stored under `%LOCALAPPDATA%\SelectSpeak`:

- application and speech settings in `settings.json`;
- the optional Supertonic model under `models`;
- local diagnostic logs under `logs` when logging is enabled.

Logging is disabled by default. If a user enables it for troubleshooting, logs
may contain previews of selected or clipboard text and should be treated as
sensitive. SelectSpeak does not upload logs automatically.

## Network connections

Network access is limited to installation or feature acquisition requested by
the user or installer:

- Setup downloads pinned Microsoft Speech SDK runtime packages from
  `api.nuget.org`. It copies three required runtime DLLs into SelectSpeak's own
  application directory and does not install a system-wide SDK.
- When Supertonic is selected, SelectSpeak may download the matching Setup
  executable and checksum from the project's GitHub Releases page. Setup may
  then download hash-verified Supertonic dependency and model archives from the
  same release.
- A developer installation, or recovery from a missing optional model, may
  download Supertonic model files from Hugging Face.

These requests necessarily disclose ordinary connection metadata, such as the
device's IP address, to the service being contacted. They do not include text
selected for speech. The relevant service policies are the
[Microsoft Privacy Statement](https://www.microsoft.com/privacy/privacystatement),
[GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement),
and [Hugging Face Privacy Policy](https://huggingface.co/privacy).

## Retention and deletion

Normal uninstall removes the application but preserves
`%LOCALAPPDATA%\SelectSpeak` so settings and optional models survive an upgrade
or reinstall. A user can permanently remove that directory after quitting and
uninstalling SelectSpeak. Data kept only in memory is released when the
application exits.

## Changes and questions

Material changes to this policy will be committed with the source and noted in
release information. Privacy questions may be raised through the project's
[GitHub issue tracker](https://github.com/Shayman-M-86/my-TTS/issues); do not
include private text or diagnostic logs in a public issue.

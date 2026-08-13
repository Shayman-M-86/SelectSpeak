# Third-party notices

The local Narrator voice discovery, configuration, and cancellation ordering in
this directory were adapted from
[NaturalVoiceSAPIAdapter](https://github.com/gexgd0419/NaturalVoiceSAPIAdapter),
Copyright (c) 2024 gexgd0419, under the MIT License. The upstream license is
reproduced in `LICENSE.NaturalVoiceSAPIAdapter.txt`.

Current Windows speech-runtime credential discovery was adapted from
[TTS-anywhere](https://github.com/yosef0H4/TTS-anywhere), Copyright (c) 2026
yosef0H4, under the MIT License. Its license is reproduced in
`LICENSE.TTS-anywhere.txt`. SelectSpeak discovers the installed Windows DLL and
extracts the credential in memory; it does not copy the DLL or persist the
credential.

Microsoft's Speech SDK and installed Natural Voice packages are separate
Microsoft components. The upstream MIT license does not grant redistribution
rights for those binaries or voice models. This bridge expects them to be
obtained separately during a local build or already installed on Windows.

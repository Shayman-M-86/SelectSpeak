# Third-party notices

Current Windows speech-runtime credential discovery was adapted from
[TTS-anywhere](https://github.com/yosef0H4/TTS-anywhere), Copyright (c) 2026
yosef0H4, under the MIT License. Its license is reproduced in
`LICENSE.TTS-anywhere.txt`. SelectSpeak discovers the installed Windows DLL and
extracts the credential in memory; it does not copy the DLL or persist the
credential.

Microsoft's Speech SDK and installed Natural Voice packages are separate
Microsoft components. The TTS-anywhere MIT license does not grant
redistribution rights for those binaries or voice models. This bridge uses
voice packages already installed through Windows.

# Third-party notices

## Bundled in `bl2_access/helper/prism64/`

**Prism**: `prism.dll`. The Platform-agnostic Reader Interface for Speech and Messages.
Licensed under the Mozilla Public License 2.0. Source code: <https://github.com/ethindp/prism>.
The DLL is distributed unmodified.

Prism's screen reader backends are shipped alongside it, unmodified, as distributed with Prism's Windows build:
`SpeechCore.dll`, `SRAL.dll`, `tolk.dll` and `UniversalSpeech.dll`. Each is covered by its own project's licence; see the
Prism repository for where each comes from.

## Downloaded by the installer (not included in this repository)

**willow2-mod-manager v3.8**, the Borderlands 2 Python SDK and mod manager: <https://github.com/bl-sdk/willow2-mod-manager>.
It's downloaded from its own GitHub release and checked against a pinned SHA-256 checksum.

**Microsoft Visual C++ Redistributable (x86)**: downloaded from Microsoft only if it's missing and you agree. The
installer checks that it's signed by Microsoft before running it.

**Python 3.12 (64-bit)**: installed with winget only if it's missing and you agree.

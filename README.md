# Borderlands Access

A mod that makes Borderlands 2 playable without sight. It reads the game's menus aloud through your screen reader (NVDA,
via Prism), and adds directional sounds for enemies, aiming, loot, containers, interactive objects, quest items, walls,
ledges and jumps. It also has a guidance beacon, interaction prompts, lock-on aiming, lock-on navigation and full
controller support.

> **Beta.** Borderlands Access is in beta and still changing quickly. Much of it has only been tested in the first area
> of the game (Windshear Waste), and some features rely on best guesses about how the game works internally, so expect
> rough edges: wrong or missing announcements, routes that lead somewhere unhelpful, or a feature that stays silent. If
> something doesn't work, please open an issue and attach `sdk_mods\bl2_access\logs\diagnostic.log` from your game
> folder. It records what the mod saw and did.

## Install

1. Download `BorderlandsAccess-0.2.1.zip` from the [latest release](../../releases/latest) and extract the whole zip.
2. Close Borderlands 2, then double-click **Install.cmd** in the extracted folder.

The installer reads out each step as plain text, so your screen reader can follow it, and asks before anything that
changes your PC outside the game folder. It:

1. Finds Borderlands 2 in your Steam libraries.
2. Installs the Borderlands 2 mod manager, [willow2-mod-manager](https://github.com/bl-sdk/willow2-mod-manager) v3.8, into
   the game folder, unless it's already installed. The download is checked against a known SHA-256 checksum.
3. Offers to install the Microsoft Visual C++ x86 runtime if it's missing. The mod manager needs it.
4. Offers to install 64-bit Python with winget if it's missing. Speech through Prism needs it.
5. Copies the mod into the game's `sdk_mods` folder. Your mod settings are kept.
6. Sets Steam to skip the 2K launcher, which isn't accessible. This closes Steam and reopens it.

Then start NVDA, and start Borderlands 2 from Steam. You should hear "Borderlands Access loaded".

To see what the installer would do without changing anything, run `Install.cmd -CheckOnly`. Other options are listed at
the top of `install.ps1`.

## Using the mod

In the game, press your **modifier button three times quickly** (Back by default) for the spoken accessibility settings
and the sound glossary, or press Equals on the keyboard. Hold the modifier and press Start to hear every controller
shortcut. The full guide is in [bl2_access/README.md](bl2_access/README.md).

## Repository layout

| Path | What it is |
|---|---|
| `bl2_access/` | The mod itself, as it goes in `sdk_mods` |
| `install.ps1`, `Install.cmd` | The installer |
| `tools/build_release.ps1` | Builds the release zip into `dist/` |
| `tests/` | Offline test suites that run the mod against a simulated game |

Run the tests with `python tests/run_all.py`. They need Windows, because the mod's audio uses winmm.

## Credits

Speech goes through [Prism](https://github.com/ethindp/prism) (MPL-2.0). The mod runs on the
[willow2-mod-manager](https://github.com/bl-sdk/willow2-mod-manager) SDK. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

# Changelog

## 0.1.0

First release.

- **Speech**: NVDA output through Prism, using a 64-bit helper process, because Borderlands 2 is 32-bit.
- **Menus read aloud**: the main, pause and options menus, sliders and spinners, dialogs, the character select screen with
  class descriptions, and status menu tab names. The inventory, vendors and bank read the full item card: name, rarity,
  type, level, stats with better, worse or same comparisons, special effects, value and requirements. The skill tree reads
  each skill's name, points and description.
- **Combat**:
  - Steady directional enemy tones that track your aim. Pitch shows whether an enemy is above or below your crosshair,
    and the tone turns to a fast buzzing pulse when your crosshair is on the enemy.
  - Lock-on aim, as an alternative to aim assist.
- **World sounds**: steady directional sounds for loot by type, containers, interactive objects and quest items. Wall,
  ledge and jump cues, NPC chimes, and a low-health heartbeat.
- **Navigation**:
  - A scanner with categories, including quest objectives with map markers.
  - A steady beacon with an "on course" tone, which follows the game's walking route where the level has one.
  - Lock-on navigation, which turns you to face the objective.
  - Interaction prompts that name the button to press.
- **Settings**: a spoken accessibility settings menu (press the modifier three times) and a sound glossary with a 0–300%
  volume for every sound.
- **Installer**: installs the mod manager v3.8 (checksum-verified), checks the Visual C++ runtime and Python, installs
  the mod, and sets Steam to skip the 2K launcher.

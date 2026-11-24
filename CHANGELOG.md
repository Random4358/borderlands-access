# Changelog

## 0.2.0

- **Line tests that work**: the game's own line tests give fixed answers through the mod manager, so the mod now calls
  the engine's line test code directly (an experimental setting, on by default, with a crash guard that switches it off
  if the first call ever fails). Wall clicks, ledge warnings, jump cues, the "blocked" messages and the route planner
  work again.
- **Routes**:
  - The route planner climbs: stairs and ramps, ledges low enough to jump onto, and drops down, saying "Jump up here" or
    "Drop down here". A marker on a ledge is only reached at its height.
  - Learned paths: where you, enemies and NPCs walk is saved for each level and used for routes, along with the level's
    path nodes. The mod comes with starter paths for Windshear Waste, so a new install doesn't start from nothing; what
    you learn is added to them.
  - Corners are no longer cut so tightly that you snag on them.
- **Missions**: the readout says the objectives of the mission's live stage ("Now: …") with that stage's summary, instead
  of every unfinished objective. Markers are named by the live objective. If a marker is above or below you, you're told
  how far and what's near it, instead of a false "Arrived"; arriving says what's there.
- **Combat**:
  - Lock-on aim and aim assist now turn your view (the game's own turn function did nothing), and pick an enemy even
    when you're zoomed in.
  - Cover is judged from what the game actually draws.
  - While enemy tones play, the beacon and object sounds step back.
- **Sounds**:
  - Loot sounds are steady tones, not beeps. Weapons ring and gear has a hollow tone, both rising in pitch with rarity.
    Ammo, health, money and quest items each have their own sound, and no object sound overlaps the beacon's pitch.
  - New "Loot sound style" option: the game's own drop sounds on repeat instead of steady tones.
  - The beacon is the loudest sound outside a fight.
- **Containers**: opened containers drop off the scanner and stop sounding. The mod learns the game's own "opened" marker.
- **Interaction**:
  - Prompts measure distance across the floor, so things right in front of you are announced.
  - New "Use assist" setting: Use opens the announced object even if your crosshair isn't quite on it.
  - Within reach but not facing it, you're told which way to turn.
- **Controls**: modifier + B reads your status (health, shield, weapon and ammo, level and experience, money, eridium,
  unspent skill points), and modifier + X repeats the last speech. The X button is recognised properly.
- **Skill tree**: "Skills" is said once instead of on every button press. Each skill reads your points, what it does and
  its numbers, and the tab says how many points you have to spend.
- **Settings**: every setting has an explanation, read after its name and value.
- **Fixes**: the mod failing to load (0.2.0 development builds), enemies wrongly reported as behind cover, a wrongly
  learned drop sound, and "Arrived" not triggering at objects at floor level.

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

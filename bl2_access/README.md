# Borderlands Access

An accessibility mod for Borderlands 2 that helps blind players. It gives you:

- **Screen reader speech** through NVDA. It uses the Prism library, which picks NVDA when NVDA is running, and it can also talk to NVDA directly. Text goes to a braille display too, if you have one.
- **Enemy tones.** Each nearby enemy plays a steady tone that tells you where it is compared with where you're aiming: panned left or right, higher-pitched when it's above your crosshair and lower when below, louder when closer, and muffled when it's behind you or behind cover. The tone changes as your aim gets close, and becomes a fast buzzing pulse when your crosshair is on the enemy. The older repeating beeps are still available as an option.
- **Targeting.** A click and the enemy's name when your crosshair lands on an enemy. While you hold aim (left trigger or right mouse) you can have aim assist, which gently pulls your aim toward the enemy nearest your crosshair, or lock-on, which keeps your aim on one enemy.
- **Snap aim.** One button turns you to face the nearest visible enemy. Press it again within 2 seconds to cycle to the next enemy.
- **Navigation sounds.** Soft clicks tell you there's a wall ahead, to your left or to your right. A falling tone warns you about a ledge ahead. A heartbeat plays when your health is low.
- **Points of interest.** You can step through nearby NPCs, chests, vending machines, switches and loot. Each one is announced with its distance and a clock direction (12 o'clock is straight ahead). You can also turn on an audio **beacon** that guides you to the one you picked.
- **Menu reading.** The highlighted entry is read aloud in the main menu, pause menu, options menus and the mod menu, with its position ("2 of 6"). Choice settings read their current value, sliders read their value and range, and changing a setting speaks the new value. Options menus also read each setting's help text. Pop-up dialogs read their title, message and highlighted button, and tutorial pop-ups are read aloud. Moving, selecting and going back each make a sound. Back + B or Back + X (or F8) re-reads the highlighted entry.
- **Full controller support.** Every feature works from the controller as a button combo, and also from keyboard keys.

## Install

The easy way: run **Install.cmd** from the release zip. It does all of the steps below for you, asks before changing anything outside the game folder, and skips anything that's already installed. To install by hand instead:

1. Install the **Borderlands 2 Python SDK / mod manager** (willow2-mod-manager):
   <https://github.com/bl-sdk/willow2-mod-manager/releases>. Extract the zip into the Borderlands 2 game folder
   (`C:\Program Files (x86)\Steam\steamapps\common\Borderlands 2`). If the manager's install guide asks you to, also install the
   **x86** Visual C++ redistributable.
2. Copy this whole `bl2_access` folder into the game's `sdk_mods` folder. Copy it as a **folder**, not as a `.sdkmod` zip, because Windows can't load DLLs from inside a zip.
3. Prism is already included, in `helper\prism64\`. Prism only comes as a 64-bit Windows build, and Borderlands 2 is 32-bit, so
   the mod runs Prism in a small helper (`helper\prism_bridge.py`) using the 64-bit Python installed on your PC. The mod
   sends it text over a local-only network socket, and Prism passes it on to NVDA. The helper closes when the game closes.
   - You need a 64-bit Python 3 installed. The mod finds it automatically in the usual install folders. If yours is somewhere
     else, put the full path to `pythonw.exe` in `helper\python_path.txt`.
   - Fallback: if the helper can't start, the mod looks for NVDA's 32-bit `nvdaControllerClient32.dll` in `lib\`.
4. Start NVDA, then start the game. You should hear "Borderlands Access loaded. Speech through Prism (NVDA)".
5. If the mod doesn't start enabled, open the mod menu (Mods, on the main menu), pick Borderlands Access and enable it.
   Use **Test speech and sounds** to check that everything works.
6. **Skip the 2K launcher.** It's inaccessible, and starting `Borderlands2.exe` directly loses Steam's controller support.
   Run `skip_launcher.ps1` from this folder once (right-click it, Run with PowerShell). It closes Steam, adds the launch option
   `-nolauncher` to Borderlands 2 (it backs up Steam's settings file first), and reopens Steam. It says "Done" when it has finished.
   From then on, starting the game from Steam goes straight into the game, with the controller working.
   You can also do this by hand in Steam: Borderlands 2, Properties, General, Launch Options: `-nolauncher`.

## Controls

**Controller:** hold **Back / View** and press a button. A quick tap of Back by itself still does its normal job in the game.
You can choose a different modifier button in the mod options.

| Back + … | Action |
|---|---|
| A | Aim at nearest enemy (press again to cycle) |
| X | Repeat last speech (in menus: re-read the highlighted entry) |
| Y | List nearby enemies with directions |
| B | Status: health, shield, weapon, magazine and spare ammo, level and experience to the next level, money, eridium, unspent skill points (in menus: re-read the highlighted entry) |
| D-pad right / left | Next / previous scanner category: Quest objectives, People, Weapons and gear, Ammo and health, Money, Containers, Vendors, Travel, Doors and switches, Other |
| D-pad down / up | Next / previous item in that category |
| Left trigger | Beacon on/off for the selected item |
| Right trigger | Summary of everything nearby, by category |
| Left stick click | Level your view to the horizon |
| Right stick click | Heading and current area |
| Right bumper | Enemy radar on/off |
| Left bumper | Wall sounds on/off |
| Start | Speak this list |

**Quest objectives** is the first scanner category. Its first entry is your active mission: its name, the objectives still to
do with progress (for example "Kill bandits, 3 of 5"), or who to turn it in to. If the mission contact or turn-in person is
nearby, they're the next entry, and you can put the beacon on them. Quest items and mission objects found nearby follow.

Objectives the game marks with a waypoint are entries too, at any distance: for example "Kill Boom, 80 metres, 2 o'clock".
Markers for your tracked mission come first, nearest first; other missions' markers follow with the mission name in front.
The beacon works on all of them, and on the mission summary itself, which leads you to the nearest objective marker. If the
game hasn't placed a marker yet (some objectives have none until you talk to someone), the beacon tells you so.

**Status menu** (Back button): the mod says the tab's name (Map, Inventory, Skills, Mission log, Badass rank) as you switch
tabs with the bumpers. It learns each tab's name the first time you press a button on that tab, so on a new install a tab
may only be named after your first button press there. In the **inventory** (and at vendors and the bank) moving the
highlight reads the whole item card: name, rarity, manufacturer and type, level, whether it's equipped, every stat (for
example "Damage 11, Accuracy 89.3"), special effects, value, and any level requirement. When the game compares the item
with the one you have equipped, each stat says "better", "worse" or "same". An empty equipped slot says "Empty slot". In the **skill tree** it reads the skill's
name, how many points you have in it out of the maximum, and its description. F8, Back + B or Back + X repeats the last one.

**Beacon and lock-on navigation**: the beacon (Back + left trigger, or F11, on a scanner entry) is a steady tone:
- **Direction**: panned the way to go, and muffled when that's behind you. Within about 7 degrees of the right way it
  turns brighter ("on course"): walk forward.
- **Distance**: it pulses faster as you get closer, and says "Arrived" when you get there.
- **Height**: the pitch is a little higher when the target is above you and lower when below.
- **Route**: it leads you around walls and obstacles, through doorways and gaps, and away from drops, instead of
  straight at the target. Where the level's navigation mesh gives a walking route, it follows that. Otherwise the mod
  plans its own: it searches the area around you, a metre at a time, testing with line traces where you can walk, and
  finds the way through. It takes well under a second, and the search is spread over frames so the game doesn't
  stutter. The beacon then leads you along that route. When it has one it says "Route found" and the length. If it can't see the whole way yet, for example to a target inside a building whose door it hasn't found, it says "Heading toward it, searching for the way in", leads you as close as it can, and searches a wider area from there. Far from the target it plans in larger steps, and within 35 m in one-metre steps that find doorways. It also handles stairs. If you keep walking without getting any further along the route, or get snagged, it says "Recalculating" and plans again from where you are.

**Lock-on navigation** (off by default; Navigation options, or the accessibility settings) turns you to face the way to go
when you hold the modifier and click the right stick, or press the apostrophe key. It turns toward the beacon's target if
you've picked one, otherwise the nearest marker of your tracked mission, along the route when there is one, with your view
level. It says, for example, "Facing Kill Boom, 30 metres". When lock-on navigation is off, that button says your heading
as before.

**When you're blocked**: if you push into something and don't move, the mod says what's in the way. "Low obstacle.
Jump over" means it's low enough to jump, and the jump cue plays. Otherwise you hear "Blocked" and where the way through is, as a
clock direction, for example "Blocked. Way through at 10 o'clock". It looks all the way round you, and prefers the way the
beacon's route goes. The beacon also picks a way around straight
away. Turn the spoken part off with "Say when you're blocked" in the Navigation options.

**Combat**: the enemy tones are designed for aiming, not just for knowing enemies are there.
- **Left or right**: the tone is panned by where the enemy is compared with your crosshair. Turn toward it until it's
  centred. It's only centred when your crosshair is within the enemy's width: even slightly off, it jumps clearly to that
  side, so you can hear the last few degrees.
- **Up or down**: the pitch is exactly the middle note when the enemy is level with your crosshair. A little above or
  below, it jumps a semitone higher or lower at once, and keeps rising or falling up to an octave at 30 degrees.
- **How close your aim is**: a soft, mellow tone means the enemy is off to the side. Within about 15 degrees it pulses
  slowly, within about 6 degrees it pulses quicker and brighter, and when your crosshair is on the enemy it switches to a
  buzzy, fast-pulsing high tone: fire. The pulse speeding up tells you you're closing in.
- The tones follow your aim within about a twentieth of a second.
- **Distance and cover**: closer enemies are louder. Enemies behind you or behind cover are muffled.

The nearest 3 enemies play at once by default ("Radar max enemies"). **Aiming help while aiming down sights** (Targeting
options) has three settings:
- **Aim assist** (the default) gently pulls your aim toward the enemy nearest your crosshair.
- **Lock-on** keeps your aim on one enemy for as long as you hold aim and can see it. It picks the enemy nearest your
  crosshair and says "Locked on" and its name. Back + A (F5) switches to the next enemy. If that enemy goes behind cover,
  it moves to the next one you can see.
- **Off** gives no help.

**Object sounds**: the nearest few things around you (within 15 m, 4 at once by default) each play their own steady
sound for as long as they're there. Each sound is panned to where the object is, gets louder as you get closer, and is
muffled when the object is behind you, so you can turn until it's centred and walk to it.
- **Weapons**: a steady ring, like a held bell. The rarer the gun, the higher it rings: common, uncommon, rare, epic,
  legendary, then pearlescent and better.
- **Shields, grenade mods, class mods and relics**: a steady hollow tone, rising with rarity the same way.
- **Ammo**: a low, steady hum.
- **Health**: a soft, warm two-note chord.
- **Money and eridium**: a soft steady tone, a little higher than the weapons.
- **Other loot on the ground**: a soft, low steady tone.
- **Chests, lockers and other containers**: a woody low throb. It stops once you've opened the container, if the game
  reports that.
- **Doors, switches, vendors and fast travel stations**: a steady hollow tone.
- **Quest items and mission objects**: a steady, low two-note chord. These always get a sound before anything else.

No object sound goes above about 1.6 kHz, so nothing is shrill. Nothing else uses the middle of the pitch range, which is kept for the beacon, and the beacon is always the loudest
sound. Object sounds get quieter while the beacon or enemy tones are playing, the beacon's own target doesn't also play
its object sound, and several things of the same kind side by side play as one.

**Loot sound style** (Object sounds options): if you'd rather not have held tones, choose "Game's drop sounds". Each item
on the ground then repeats the sound the game played when it dropped, every 1 to 3 seconds (more often as you get
closer), played on the item so the game's own 3D sound places it. The mod learns these sounds as loot drops near you and
remembers them for that kind and rarity of item (in game_sounds.json), so after one rare gun has dropped, every rare gun
uses its sound. Until a sound has been learned, the item plays a short burst of its tone at the same pace instead. The
game's sounds follow the game's own sound effects volume, not the mod's sliders.

A sound fades out when you pick the item up, open the container, or move out of range, and every object sound goes quiet
while a menu is open. Each type can be switched off, and the range, number at once and volume set, in the Object sounds
options. Back + right trigger (Page Up) also says which object sounds are playing.

**Interaction prompts**: when you're within about 2 m of something you can use and facing it, you hear a soft double
tick, then its name and the button to press:
- Chests and containers: "Red chest. Press X to open".
- Doors, switches and fast travel: "Press X to use".
- Vendors: "Press X to shop".
- Gear on the ground: "Press X to pick up, hold X to equip".
- Characters: "Talk to Doc Mercy. Press X".

Button names follow whatever you last pressed, so after using the keyboard you hear "Press E". Each thing is announced once
until you walk away from it. Money and ammo get no prompt, because you pick them up by walking over them. Turn prompts off
in the Navigation options ("Interaction prompts").

Menu sounds only play on screens that have options. Cinematics and loading screens are silent.

**NPC sounds**: friendly characters nearby (within 25 m by default, nearest 2) make a soft two-note chime, panned to
where they are, faster and louder as you get closer, and muffled when they're behind you. It's deliberately nothing like
the enemy radar beep. When you're right next to someone (about 2.5 m), facing them, with nothing in the way, the mod says
"Talk to" and their name, once; walk away and come back to hear it again. NPC sounds only turn on when the game can tell
friend from foe, so enemies never get the friendly chime. Range, number of characters and both features can be changed in
the Navigation options.

**Jump cues**: a rising "boing" plays while you're moving when there's an obstacle ahead you can jump over, or a gap you
can jump across. A drop with no landing in reach still gets the falling ledge warning. You can turn on spoken
"Jump over" / "Jump the gap", and set how tall a jumpable obstacle can be, in the Navigation options.

**Keyboard** (you can rebind these in the mod menu): F1 current mission, F5 aim at enemy, F6 status, F7 enemies, F8 repeat, `[` / `]` previous/next
scanner category, F9/F10 previous/next item, F11 beacon, Page Up summary of nearby things, Home heading, End level view, Page Down turn around, Insert radar,
Delete walls, Backslash targeting, F4 help, F3 stop speech, F2 menu trace (a tool for finding menu hooks, see below).

## Accessibility settings menu

Press your **modifier button three times quickly** (Back by default, or whichever button you chose as "Controller
modifier button") to open the mod's own spoken settings menu. On the keyboard, press **Equals**. It has every mod option
and a sound glossary, all read aloud. While it's open the game doesn't get your button presses and the mod's world sounds
are quiet, but the game isn't paused, so open it somewhere safe.

| Button (keyboard) | What it does |
|---|---|
| D-pad up / down (arrow keys) | Previous / next setting in the group |
| Bumpers (Q / E) | Previous / next group |
| D-pad left / right (arrow keys) | Change the value. Sound volumes play the sound at the new volume |
| A (Enter or Space) | Switch on or off, press a button, or play the sound |
| Y (Tab) | Describe the setting again, with its range or choices. (Each setting's explanation is also read automatically after its name and value; moving on cuts it off. Turn that off with Read option descriptions.) |
| X (R) | Reset to the default |
| B, or the modifier button (Escape) | Close and save |

A single tap of the modifier still reaches the game as before (Back still opens the map), a third of a second later than
it used to, because the mod waits to see whether a second and third tap follow.

### Sound glossary

The last group, **Sound glossary and volumes**, lists every sound the mod makes with what it means. Moving onto a sound
plays it. Each has its own volume from 0% (off) to 300%, on top of the main cue volume. The same volumes are also in the
mod's options under the Mods menu.

| Sound | What it means |
|---|---|
| Enemy tone, off target | Steady tone for each nearby enemy. Panned to where it is compared with your aim, higher when it's above your crosshair, lower when below, louder when closer. |
| Enemy tone, nearly on target | The enemy tone turns brighter and pulses as your aim gets close: a slow pulse within about 15 degrees, a quicker, brighter pulse within about 6 degrees. |
| Enemy tone, on target | A buzzy, fast-pulsing high tone: your crosshair is on the enemy. Fire. |
| Enemy radar beep | Repeating beep for each nearby enemy, used when the enemy sound style is set to radar beeps. |
| Target lock | A rising two-note click when your crosshair lands on an enemy, or lock-on picks one. |
| On-target tick | Ticks while your crosshair stays on an enemy, in radar beep style only. |
| Target lost | A falling tone when your crosshair leaves an enemy, in radar beep style only. |
| Low health heartbeat | A heartbeat when your health is low. Faster when it's very low. |
| Friendly character chime | A soft two-note chime for friendly characters nearby. |
| Beacon | A steady pulsing tone that leads you to the item or objective you picked, panned the way to go. It pulses faster as you get closer and is muffled when the way to go is behind you. |
| Beacon, on course | The beacon turns brighter when you're facing the way to go. Walk forward. |
| Wall click | A soft click when there's a wall close in front of or beside you. |
| Ledge warning | A falling tone when there's a drop ahead of you. |
| Jump cue | A rising boing when there's something you can jump over, or a gap you can jump across. |
| Weapons and gear on the ground | A bright two-note shimmer for guns, shields, grenade mods, class mods and relics lying nearby. |
| Ammo and health on the ground | A low, soft hum that gently swells. |
| Money and eridium on the ground | A high sparkle. |
| Other loot on the ground | A plain steady tone. |
| Chests and containers | A woody low buzz for chests, lockers and crates you haven't opened. |
| Doors, switches, vendors and travel | A mid warble for doors, switches, vending machines and fast travel stations. |
| Quest items | A pulsing two-tone chord for quest items and mission objects. |
| Menu move | A short tick when you move the highlight in a menu. |
| Menu select | Two rising notes when you pick something in a menu. |
| Menu back | Two falling notes when you go back in a menu. |
| Menu opened | Three rising notes when a menu opens. |
| Menu closed | Three falling notes when a menu closes. |
| Switched on | Two rising notes when something is switched on, such as the beacon or radar. |
| Switched off | Two falling notes when something is switched off. |
| Interaction prompt | A soft double tick when you're close enough to use something, just before it's named with the button to press. |
| Modifier button | A tiny click when you hold the modifier button for a shortcut. |
| Error | A low buzz when an action can't be done. |

## Cutscene descriptions

During cutscenes the mod describes what's happening on screen, fitted between the lines of dialogue where it can.
Descriptions are written so far for the opening intro and four character introduction videos (Marcus, Scooter, Tannis
and Dr. Zed). Turn them off with "Cutscene descriptions" in the Cutscenes options.

Each cutscene's description is a small file in `descriptions\`, so more can be added without changing the mod.

**Helping write more:** most of the game's story scenes are played live by the engine, so the only way to describe them
is to capture them once. Turn on "Cutscene capture, for writing descriptions" (Cutscenes options) and play as normal.
During each cutscene the game takes a screenshot every second, and `logs\cutscene_capture.txt` records which cutscene
and how far into it each one was. Send the screenshots and that file, and descriptions can be written from them. Leave
capture off otherwise.

## Options

Every option is in the mod menu, in these groups: General (volume, speech output, test button), Controller and menus,
Enemy radar (range, how many enemies, whether enemies behind cover are included), Targeting (spoken names, aim assist
strength), and Navigation (wall distance, ledges, low-health threshold).

## Known limitations and what to test first

This is version 0.2.1. These have been confirmed working inside Borderlands 2: speech through Prism, the main, options and slider menus, dialogs, character select, status menu tab names, inventory item cards, the direct engine line tests, the route planner, lock-on aim, the interaction prompts and the mission stage readout. The rest has been tested against a simulated game. Some of the game's internal names it relies on are best guesses. Every one of them is wrapped so that if one is wrong, only that feature stops working and the game doesn't crash. Errors are printed to the SDK console (press `~` in game) with a `[Borderlands Access]` prefix.

- **Untested in the game so far: inventory, vendor and skill tree reading, tab names and objective markers.** Rarity
  names are worked out from the colour of the item's name; only "common" has been seen in a trace so far. The mission log tab
  and fast travel may still be silent. If a menu doesn't read, use the trace tool:
  1. Open the menu, for example the inventory.
  2. Press **F2**. You'll hear "Menu trace started".
  3. Move the highlight over a few items, then press **F2** again.
  4. Send `sdk_mods\bl2_access\logs\trace.log` to whoever is building the mod. It shows which game functions ran and
     what text they carried, which is what a reader for that menu needs.

  Console commands do the same from the `~` console: `bla_trace menus`, `bla_trace <ClassName>`, `bla_trace off`, and
  `bla_dump <ClassName>`, which lists a class's functions and properties.
- **Main and pause menu reading calibrates itself.** These menus don't report which entry is highlighted. The first
  time you move the highlight, the mod checks which number on the menu changed and uses that from then on. The console
  shows `menu selection property for ...` when this works. Options menus report the highlighted entry directly, so they
  don't need this.
- **Friend or foe** detection uses `IsEnemy` when the game provides it. Otherwise every AI counts as an enemy, which you
  can turn off in the options.
- **Shield and magazine readouts** use property names that may differ in BL2. If they're missing, the status readout skips them.
- **The input hook** (`WillowUIInteraction:InputKey`) is the same one the SDK's own keybind system uses. The
  **tick hook** names come from SDK conventions and haven't been confirmed. If the radar and wall sounds do nothing at
  all, check those first, in `hooks.py`.
- **Distances** assume about 100 game units per metre. Change `UU_PER_METRE` in `game.py` if they sound wrong.
- The **Prism stdcall** option only matters if you ever put a 32-bit `prism.dll` in `lib\` (it then loads inside the game
  instead of through the helper). Leave it off otherwise.

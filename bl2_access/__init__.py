"""Borderlands Access: screen reader output, audio radar and controller combos for blind players."""

from __future__ import annotations

from typing import Any

from mods_base import (
    BoolOption,
    ButtonOption,
    DropdownOption,
    GroupedOption,
    SliderOption,
    build_mod,
    keybind,
)

from . import audio as snd
from . import controls, hooks, trace
from .audio import audio as audio_engine
from .controls import ACTIONS, MODIFIER_CHOICES, menus, state
from .features import features as feats
from .menu_reader import reader
from .speech import speech as speaker

__version__ = "0.1.0"

# ----------------------------------------------------------------------------- options

opt_volume = SliderOption("Cue volume", 80, 0, 100, description="Volume of all accessibility sounds.")
opt_speech = DropdownOption(
    "Speech output", "Prism (uses NVDA when running)", ["Prism (uses NVDA when running)", "NVDA direct"],
    description="How text is sent to your screen reader. Changes apply when the mod is re-enabled.",
)
opt_prism_stdcall = BoolOption(
    "Prism stdcall", False,
    description="Advanced: only turn on if speech crashes the game with Prism.",
)
opt_modifier = DropdownOption(
    "Controller modifier button", "Back / View", list(MODIFIER_CHOICES),
    description="Hold this button and press another button for accessibility actions.",
)
opt_menu_sounds = BoolOption("Menu navigation sounds", True)
opt_menu_announce = BoolOption("Announce menus", True)
opt_menu_reader = BoolOption("Read menu entries aloud", True)
opt_diagnostics = BoolOption(
    "Diagnostic logging", True,
    description="Writes key presses and menu events to logs\\diagnostic.log so problems can be fixed. Applies on next launch.",
)
opt_direct_trace = BoolOption("Direct engine line tests (experimental)", True)
opt_auto_trace = BoolOption(
    "Trace menu functions at startup", False,
    description="Developer tool: hooks hundreds of game functions and logs them to logs\\trace.log. Can crash the game during level loads, so leave off unless asked. F2 starts a trace by hand.",
)
opt_menu_desc = BoolOption("Read option descriptions", True, description="In options menus, read the help text after each entry.")

opt_radar = BoolOption("Enemy radar", True, description="Sounds for nearby enemies, panned to where they are compared with your aim, louder when closer, muffled when behind you or behind cover.")
opt_enemy_sound = DropdownOption(
    "Enemy sound style", "Steady tones", ["Steady tones", "Radar beeps"],
    description="Steady tones: each enemy plays a continuous tone. Higher pitch when it's above your crosshair, lower when below. It turns brighter when you're close to aiming at it, and becomes a fast buzzing pulse when your crosshair is on it. Radar beeps: the older repeating beeps.",
)
opt_enemy_volume = SliderOption("Enemy tone volume", 70, 10, 100, step=5)
opt_radar_range = SliderOption("Radar range (metres)", 40, 10, 150)
opt_radar_max = SliderOption("Radar max enemies", 3, 1, 6)
opt_radar_hidden = BoolOption("Radar includes enemies behind cover", True)
opt_all_ai = BoolOption("Treat all AI as enemies", True, description="Fallback if friend/foe detection is unavailable.")

opt_targeting = BoolOption("Targeting sounds", True, description="Lock-on chime and ticking while your crosshair is on an enemy.")
opt_speak_target = BoolOption("Speak enemy name on lock-on", True)
opt_aim_assist = SliderOption("Aim assist strength (while aiming)", 40, 0, 100)
opt_aim_mode = DropdownOption(
    "Aiming help while aiming down sights", "Aim assist", ["Aim assist", "Lock-on", "Off"],
    description="Aim assist: your view is gently pulled toward the enemy nearest your crosshair. Lock-on: your view follows one enemy for as long as you hold aim and can see it; Back + A switches enemy. Off: no help.",
)

opt_walls = BoolOption("Wall sounds", True, description="Soft clicks when a wall is ahead, left or right.")
opt_wall_dist = SliderOption("Wall detection distance (metres)", 3, 1, 8)
opt_npc_sounds = BoolOption("NPC sounds", True, description="A soft chime for friendly characters nearby: panned to where they are, faster when closer, muffled when behind you.")
opt_npc_range = SliderOption("NPC sound range (metres)", 25, 5, 60)
opt_npc_max = SliderOption("NPC sounds max characters", 2, 1, 5)
opt_use_assist = BoolOption("Use assist", True, description="When an interaction prompt has just told you about something in reach, pressing Use (X, or E on the keyboard) uses that thing even if your crosshair isn't exactly on it.")
opt_interact = BoolOption("Interaction prompts", True, description="When you're close to something you can use and facing it, a soft double tick, then its name and the button to press, for example: Red chest. Press X to open. Uses keyboard key names if you last used the keyboard.")
opt_lock_nav = BoolOption("Lock-on navigation", False, description="When on, hold the modifier and click the right stick (or press the apostrophe key) to turn and face the way to your objective: the beacon's target if you've picked one, otherwise the nearest marker of your tracked mission. It follows the game's walking route when there is one. When off, that button says your heading.")
opt_npc_talk = BoolOption("Say who you can talk to", True, description="Says 'Talk to' and the character's name when you're next to them and facing them.")
opt_ledges = BoolOption("Ledge warnings", True)
opt_loot_style = DropdownOption("Loot sound style", "Steady tones", ["Steady tones", "Game's drop sounds"], description="Steady tones: each item on the ground has a held tone (weapons ring higher the rarer they are). Game's drop sounds: each item instead repeats the sound the game played when it dropped, every couple of seconds, more often as you get closer. Items whose drop sound hasn't been heard yet play a short burst of the mod's tone instead. Drop sounds are learned as loot drops near you and remembered for that kind and rarity of item.")
opt_loot_sounds = BoolOption("Loot sounds", True, description="Steady sounds for loot on the ground, a different one for weapons and gear, ammo and health, money, and other loot. They pan to where the item is and get louder as you get closer.")
opt_container_sounds = BoolOption("Container sounds", True, description="A steady low buzz for chests, lockers and other containers you haven't opened.")
opt_interactive_sounds = BoolOption("Interactive object sounds", True, description="A steady warble for doors, switches, vendors and fast travel stations.")
opt_quest_item_sounds = BoolOption("Quest item sounds", True, description="A pulsing two-tone sound for quest items and mission objects. These always get a sound before other objects.")
opt_object_range = SliderOption("Object sound range (metres)", 15, 3, 40)
opt_object_max = SliderOption("Object sounds at once", 4, 1, 6)
opt_object_volume = SliderOption("Object sound volume", 70, 10, 100, step=5)
opt_speak_blocked = BoolOption("Say when you're blocked", True, description="When you push against something and don't move, says what's in the way and which side is open, for example: Blocked, open to the left. Or: Low obstacle, jump over.")
opt_jump = BoolOption("Jump cues", True, description="A rising 'boing' when there's an obstacle you can jump over, or a gap you can jump across.")
opt_jump_height = SliderOption("Jump cue obstacle height (cm)", 100, 50, 200, step=10, description="How tall an obstacle can be and still count as jumpable.")
opt_speak_jump = BoolOption("Speak jump cues", False, description="Also say 'Jump over' or 'Jump the gap'.")
opt_low_health = BoolOption("Low health heartbeat", True)
opt_low_health_pct = SliderOption("Low health threshold (%)", 30, 5, 75)


def _test(_: Any = None) -> None:
    audio_engine.play("ui", snd.ui("open", feats.s.volume))
    for pan in (-1.0, 0.0, 1.0):
        audio_engine.play("radar", snd.enemy_ping(pan, feats.s.volume, 1.0, False, True))
    speaker.say(f"Borderlands Access {__version__}. Speech is working through {speaker.backend.name if speaker.backend else 'console only'}.")


opt_test = ButtonOption("Test speech and sounds", on_press=_test)

# Help text for every setting: read after the setting's name and value in the accessibility
# settings (and by Y there), and shown in the mod manager's own menu. Every option must have
# one (the tests check).
TRACE_NOTE = (" This depends on the game's line tests; if they don't work in your setup it stays silent rather"
              " than guess.")
HELP = [   # (option, text): options can't be dict keys (the mod manager's options are unhashable)
    (opt_volume, "Master volume for every sound the mod makes: object sounds, enemy tones, the beacon and menu sounds. It doesn't change the game's own sounds or your screen reader."),
    (opt_test, "Plays a few test sounds from the left, centre and right, and says which speech output is working."),
    (opt_modifier, "Hold this button and press another one for the mod's shortcuts, for example modifier and B for your status. Press it three times quickly to open these settings. A single tap still does its normal job in the game."),
    (opt_menu_sounds, "Short sounds when you move, select or go back in the game's menus and in these settings."),
    (opt_menu_announce, "Says the name of each menu or screen as it opens, for example Options or Inventory."),
    (opt_menu_reader, "Reads the highlighted entry aloud as you move through the game's menus, with its position, for example 2 of 6."),
    (opt_menu_desc, "Reads each entry's help text after its name: in the game's options menus, and here, where every setting's explanation follows its name and value. Move on to skip it. Y repeats it here."),
    (opt_enemy_volume, "How loud enemy sounds are compared with the mod's other sounds."),
    (opt_radar_range, "How far away, in metres, an enemy can be and still make a sound."),
    (opt_radar_max, "The most enemies that make a sound at the same time. The nearest ones are chosen."),
    (opt_radar_hidden, "When on, enemies behind cover still make a sound, muffled. When off, only enemies you can see do."),
    (opt_all_ai, "If the game can't say which characters are hostile, treat every computer-controlled character as an enemy so none are missed. Friendly characters may then sound like enemies."),
    (opt_targeting, "In the radar beep style: a chime when your crosshair lands on an enemy, ticking while it stays there, and a falling tone when it leaves. In the steady tone style the enemy's own tone changes instead."),
    (opt_speak_target, "Says the enemy's name when your crosshair lands on it or lock-on picks it, for example: Locked on Bandit."),
    (opt_aim_assist, "How strongly your view is pulled toward the enemy nearest your crosshair while you aim down sights. 0 is no pull, 100 the strongest. Only used when aiming help is set to Aim assist."),
    (opt_walls, "Soft clicks when a wall is close ahead of you, or to your left or right." + TRACE_NOTE),
    (opt_wall_dist, "How close, in metres, a wall has to be before it clicks."),
    (opt_npc_range, "How far away, in metres, a friendly character can be and still chime."),
    (opt_npc_max, "The most friendly characters that chime at the same time. The nearest ones are chosen."),
    (opt_npc_talk, "Says 'Talk to', the character's name and the button to press when you're right next to someone and facing them."),
    (opt_lock_nav, "When on, hold the modifier and click the right stick (or press the apostrophe key) to turn and face the way to your objective: the beacon's target if you've picked one, otherwise the nearest marker of your tracked mission. It follows known walking paths when there are any, and when you're close, looks right at the thing so the game's Use works. When off, that button says your heading."),
    (opt_ledges, "A falling tone when there's a drop ahead of you." + TRACE_NOTE),
    (opt_loot_sounds, "Sounds for loot on the ground: weapons, shields and other gear, ammo, health, money and other items each have their own. They're panned to where the item is and get louder as you get closer. Loot sound style chooses steady tones or the game's own drop sounds."),
    (opt_container_sounds, "A woody low throb for chests, lockers and other containers you haven't opened yet."),
    (opt_interactive_sounds, "A steady hollow tone for doors, switches, vendors and fast travel stations."),
    (opt_quest_item_sounds, "A steady two-note chord for quest items and mission objects. These always get a sound before other things."),
    (opt_object_range, "How far away, in metres, an object can be and still make a sound."),
    (opt_object_max, "The most object sounds playing at once. Quest items come first, then the nearest things."),
    (opt_object_volume, "How loud object sounds are compared with the mod's other sounds. The beacon is always louder."),
    (opt_speak_blocked, "When you push against something and don't move, says what's in the way and which side is open, for example: Blocked, open to the left. Or: Low obstacle, jump over." + TRACE_NOTE),
    (opt_jump, "A rising boing when there's an obstacle you can jump over, or a gap you can jump across." + TRACE_NOTE),
    (opt_low_health, "A heartbeat when your health falls below the threshold, faster when it's very low."),
    (opt_direct_trace, "Wall clicks, ledge warnings, jump cues, the blocked messages, cover and route finding need line tests: checks of whether a straight line through the level is clear. The game's own way of doing them gives fixed answers through the mod manager, so this calls the engine's line test code directly. If the game ever stops during the very first direct call, it switches itself off for good. Turn it off if you have crashes you think are caused by it."),
    (opt_low_health_pct, "The heartbeat starts when your health is below this percentage of your maximum."),
]
for _opt, _text in HELP:
    _opt.description = _text


# Sound glossary: one volume per sound, 0 to 300%. The descriptions say what each sound means.
SOUND_OPTS = {
    key: SliderOption(f"{name} volume", 100, 0, 300, step=10, description=f"{desc} Volume in percent, 0 to 300.")
    for key, name, desc in snd.SOUNDS
}

OPTIONS = [
    GroupedOption("General", [opt_volume, opt_speech, opt_prism_stdcall, opt_test, opt_diagnostics, opt_direct_trace, opt_auto_trace]),
    GroupedOption("Controller and menus", [opt_modifier, opt_menu_sounds, opt_menu_announce, opt_menu_reader, opt_menu_desc]),
    GroupedOption("Enemy radar", [opt_radar, opt_enemy_sound, opt_enemy_volume, opt_radar_range, opt_radar_max, opt_radar_hidden, opt_all_ai]),
    GroupedOption("Targeting", [opt_targeting, opt_speak_target, opt_aim_mode, opt_aim_assist]),
    GroupedOption("Object sounds", [opt_loot_sounds, opt_loot_style, opt_container_sounds, opt_interactive_sounds, opt_quest_item_sounds,
                                    opt_object_range, opt_object_max, opt_object_volume]),
    GroupedOption("Navigation", [opt_npc_sounds, opt_npc_range, opt_npc_max, opt_npc_talk, opt_interact, opt_use_assist, opt_lock_nav, opt_walls, opt_wall_dist, opt_ledges, opt_jump, opt_jump_height, opt_speak_jump, opt_speak_blocked, opt_low_health, opt_low_health_pct]),
    GroupedOption("Sound glossary and volumes", list(SOUND_OPTS.values())),
]

_TOGGLE_OPTIONS = {"radar": opt_radar, "walls": opt_walls, "targeting": opt_targeting}


def sync_settings() -> None:
    s = feats.s
    for key, opt in SOUND_OPTS.items():
        snd.GAINS[key] = opt.value / 100
    s.volume = opt_volume.value / 100
    s.radar = opt_radar.value
    s.radar_range = opt_radar_range.value * 100
    s.radar_max = int(opt_radar_max.value)
    s.radar_hidden = opt_radar_hidden.value
    s.treat_all_ai_as_enemies = opt_all_ai.value
    s.targeting = opt_targeting.value
    s.speak_target = opt_speak_target.value
    s.aim_assist = opt_aim_assist.value / 100
    s.aim_mode = {"Lock-on": "lock", "Off": "off"}.get(opt_aim_mode.value, "assist")
    s.enemy_tones = opt_enemy_sound.value != "Radar beeps"
    s.enemy_volume = opt_enemy_volume.value / 100
    s.walls = opt_walls.value
    s.wall_distance = opt_wall_dist.value * 100
    s.ledges = opt_ledges.value
    s.npc_sounds = opt_npc_sounds.value
    s.npc_range = opt_npc_range.value * 100
    s.npc_max = int(opt_npc_max.value)
    s.npc_talk = opt_npc_talk.value
    s.interact_prompts = opt_interact.value
    s.use_assist = opt_use_assist.value
    s.lock_nav = opt_lock_nav.value
    s.jump = opt_jump.value
    s.speak_blocked = opt_speak_blocked.value
    s.loot_sounds = opt_loot_sounds.value
    s.loot_style = "game" if str(opt_loot_style.value).startswith("Game") else "steady"
    s.container_sounds = opt_container_sounds.value
    s.interactive_sounds = opt_interactive_sounds.value
    s.quest_item_sounds = opt_quest_item_sounds.value
    s.object_range = opt_object_range.value * 100
    s.object_max = int(opt_object_max.value)
    s.object_volume = opt_object_volume.value / 100
    s.jump_height = float(opt_jump_height.value)
    s.speak_jump = opt_speak_jump.value
    s.low_health = opt_low_health.value
    s.low_health_pct = float(opt_low_health_pct.value)
    state.modifier = MODIFIER_CHOICES.get(opt_modifier.value, "XboxTypeS_Back")
    state.menu_sounds = opt_menu_sounds.value
    menus.announce = opt_menu_announce.value
    reader.enabled = opt_menu_reader.value
    reader.read_descriptions = opt_menu_desc.value
    try:
        from .native_trace import direct as _direct

        _direct.enabled = bool(opt_direct_trace.value)
    except Exception:
        pass
    try:
        from .mod_menu import modmenu as _mm

        _mm.auto_describe = lambda: bool(opt_menu_desc.value)
    except Exception:
        pass


def _on_toggle(attr: str, value: bool) -> None:
    opt = _TOGGLE_OPTIONS.get(attr)
    if opt is not None:
        opt.value = value
        try:
            mod.save_settings()
        except Exception:
            pass


controls.on_toggle = _on_toggle

# ----------------------------------------------------------------------------- keyboard

_KEYS = {
    "snap_aim": "F5", "status": "F6", "enemies": "F7", "repeat": "F8",
    "poi_prev": "F9", "poi_next": "F10", "beacon": "F11", "poi_rescan": "PageUp",
    "cat_prev": "LeftBracket", "cat_next": "RightBracket", "mission": "F1",
    "heading": "Home", "level": "End", "turn": "PageDown",
    "radar": "Insert", "walls": "Delete", "targeting": "Backslash",
    "help": "F4", "stop": "F3", "trace": "F2", "settings": "Equals", "face": "Quote",
}


def _make_bind(action: str, key: str):
    label, _fn = ACTIONS[action]
    return keybind(label, key, callback=lambda: controls.run_action(action))


_BIND_ACTIONS = [(a, _make_bind(a, k)) for a, k in _KEYS.items()]
KEYBINDS = [b for _, b in _BIND_ACTIONS]


def _keyboard_action_for(key: str) -> str | None:
    """Which action's shortcut is bound to this key right now (respects rebinding)."""
    for action, bind in _BIND_ACTIONS:
        try:
            if bind.key == key:
                return action
        except Exception:
            continue
    return None


controls.keyboard_action_for = _keyboard_action_for

# ----------------------------------------------------------------------------- lifecycle


def _on_tick_sync() -> None:
    sync_settings()


def on_enable() -> None:
    if opt_diagnostics.value:
        trace.diag_start()
    sync_settings()
    audio_engine.start()
    prefer = "nvda" if opt_speech.value == "NVDA direct" else "prism"
    backend = speaker.start(prefer, prism_stdcall=opt_prism_stdcall.value)
    hooks.PRE_TICK = _on_tick_sync
    hooks.register()
    try:   # learn the game's loot drop sounds (for the "Game's drop sounds" style)
        from .game_sounds import sounds as game_sounds

        game_sounds.register()
    except Exception as e:  # noqa: BLE001
        print(f"[Borderlands Access] game loot sounds unavailable: {e}")
    reader.register()
    from .mod_menu import modmenu

    modmenu.configure(OPTIONS, SOUND_OPTS, lambda: mod.save_settings(), lambda: feats.s.volume)
    try:
        from .status_reader import status

        status.register()
    except Exception as e:  # noqa: BLE001
        print(f"[Borderlands Access] status menu reader unavailable: {e}")
    trace.register_commands()
    try:  # one-time list of mission/objective/waypoint classes, for adding objective markers
        from . import quests

        written = quests.write_class_inventory()
        if written:
            trace.note(f"wrote {written}")
    except Exception as e:  # noqa: BLE001
        print(f"[Borderlands Access] class inventory failed: {e}")
    if opt_auto_trace.value:
        try:
            trace.auto_start()
        except Exception as e:  # noqa: BLE001
            print(f"[Borderlands Access] auto trace failed: {e}")
    speaker.say(f"Borderlands Access loaded. Speech through {backend}. Hold Back and press Start for help.")


def on_disable() -> None:
    from .mod_menu import modmenu

    modmenu.is_open = False
    hooks.unregister()
    try:
        from .game_sounds import sounds as game_sounds

        game_sounds.unregister()
    except Exception:
        pass
    reader.unregister()
    try:
        from .status_reader import status

        status.unregister()
    except Exception:
        pass
    trace.unregister_commands()
    trace.diag_stop()
    speaker.say("Borderlands Access disabled")
    speaker.close()
    try:
        from .object_sounds import objects
        from .combat_sounds import tones

        objects.stop(fade=False)
        tones.stop(fade=False)
    except Exception:
        pass
    try:
        from .waygraph import graph

        if graph.dirty:
            graph.save()
    except Exception:
        pass
    audio_engine.close()


mod = build_mod(options=OPTIONS, keybinds=KEYBINDS, hooks=[], on_enable=on_enable, on_disable=on_disable)

# The mod manager starts new mods disabled until they're switched on in the Mods menu, which a
# blind player can't read yet. So on the very first launch (no settings file saved), enable
# ourselves; after that the saved on/off state is respected.
try:
    if mod.settings_file is not None and not mod.settings_file.exists():
        mod.enable()
except Exception as _e:  # noqa: BLE001
    print(f"[Borderlands Access] could not auto-enable: {_e}")

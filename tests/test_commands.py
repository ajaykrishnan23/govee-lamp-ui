import pytest

from lamp.commands import Command, parse_command

PRESETS = ["warm white", "reading", "study", "sunset", "campfire", "ocean", "cozy", "party", "night light"]


@pytest.mark.parametrize("text,expected", [
    ("off", Command("off")),
    ("lights off", Command("off")),
    ("Turn it off", Command("off")),
    ("turn off the lights.", Command("off")),
    ("on", Command("on")),
    ("turn on", Command("on")),
    ("brightness 40", Command("brightness", 40)),
    ("40%", Command("brightness", 40)),
    ("set brightness to 75", Command("brightness", 75)),
    ("brighter", Command("brighter")),
    ("dim", Command("dimmer")),
    ("dimmer", Command("dimmer")),
    ("stop", Command("stop")),
    ("sync to my music", Command("song_on")),
    ("song mode", Command("song_on")),
    ("stop the music lights", Command("song_off")),
    ("campfire", Command("preset", "campfire")),
    ("Campfire mode", Command("preset", "campfire")),
    ("night light", Command("preset", "night light")),
    ("Make it the campfire mood.", Command("preset", "campfire")),
    ("switch to ocean", Command("preset", "ocean")),
    ("put on party mode", Command("preset", "party")),
    ("make it feel like studying in a library at night", None),
    ("warm cozy cuddly lights", None),
    ("turn it off in 20 minutes", None),
    ("", None),
])
def test_parse_command(text, expected):
    assert parse_command(text, PRESETS) == expected

import pytest

from lamp.effects import Timeline, state_at
from lamp.lamp import LightState
from lamp.presets import BUILTINS, Preset, PresetStore


def flashes_per_sec(tl: Timeline, bulb: str) -> float:
    """Max count of brightness rises within any 1s window (sampled at 10ms)."""
    start = {"top": LightState(rgb=(0, 0, 0)), "bottom": LightState(rgb=(0, 0, 0))}
    samples = [state_at(tl, t, start)[bulb] for t in range(0, min(tl.duration_ms, 10_000), 10)]
    levels = [s.brightness * (1 if s.on else 0) for s in samples]
    rises = [i for i in range(1, len(levels)) if levels[i] - levels[i - 1] > 30]
    return max((sum(1 for r in rises if i <= r < i + 100) for i in range(len(levels))), default=0)


def test_builtin_names():
    assert {p.name for p in BUILTINS} >= {
        "warm white", "reading", "study", "sunset", "campfire", "ocean", "cozy", "party", "night light"}


@pytest.mark.parametrize("p", BUILTINS, ids=lambda p: p.name)
def test_builtins_are_valid(p):
    assert p.builtin
    assert (p.static is None) != (p.timeline is None)
    if p.timeline:
        for bulb in ("top", "bottom"):
            assert flashes_per_sec(p.timeline, bulb) <= 4


def test_save_get_roundtrip_case_insensitive(tmp_path):
    store = PresetStore(tmp_path / "presets.json")
    store.save(Preset(name="Deep Focus", static={"all": {"kelvin": 5000, "brightness": 80}}))
    again = PresetStore(tmp_path / "presets.json")
    assert again.get("deep focus").static == {"all": {"kelvin": 5000, "brightness": 80}}
    assert again.get("DeepFocus") is not None
    assert any(p.name == "Deep Focus" for p in again.list())


def test_list_builtins_first(tmp_path):
    store = PresetStore(tmp_path / "presets.json")
    store.save(Preset(name="mine", static={"all": {"rgb": (1, 2, 3)}}))
    names = [p.name for p in store.list()]
    assert names[: len(BUILTINS)] == [p.name for p in BUILTINS]
    assert names[-1] == "mine"


def test_cannot_overwrite_builtin(tmp_path):
    store = PresetStore(tmp_path / "presets.json")
    with pytest.raises(ValueError):
        store.save(Preset(name="Campfire", static={"all": {"rgb": (1, 2, 3)}}))


def test_delete(tmp_path):
    store = PresetStore(tmp_path / "presets.json")
    store.save(Preset(name="mine", static={"all": {"rgb": (1, 2, 3)}}))
    store.delete("mine")
    assert store.get("mine") is None
    with pytest.raises(ValueError):
        store.delete("campfire")


def test_preset_requires_exactly_one_kind():
    with pytest.raises(ValueError):
        Preset(name="x")

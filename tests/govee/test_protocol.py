import json

from lamp.govee.protocol import (
    BulbInfo,
    BulbStatus,
    brightness_msg,
    color_msg,
    kelvin_msg,
    parse_scan,
    parse_status,
    scan_msg,
    status_msg,
    turn_msg,
)

SCAN_RESPONSE = json.dumps({
    "msg": {"cmd": "scan", "data": {
        "ip": "192.168.1.23", "device": "1F:80:C5:32:32:36:72:4E", "sku": "Hxxxx",
        "bleVersionHard": "3.01.01", "bleVersionSoft": "1.03.01",
        "wifiVersionHard": "1.00.10", "wifiVersionSoft": "1.02.03",
    }}
}).encode()

STATUS_RESPONSE = json.dumps({
    "msg": {"cmd": "devStatus", "data": {
        "onOff": 1, "brightness": 100, "color": {"r": 255, "g": 0, "b": 0}, "colorTemInKelvin": 7200,
    }}
}).encode()


def data(msg: bytes) -> dict:
    return json.loads(msg)["msg"]["data"]


def test_turn_msg_shape():
    assert json.loads(turn_msg(True)) == {"msg": {"cmd": "turn", "data": {"value": 1}}}
    assert data(turn_msg(False)) == {"value": 0}


def test_brightness_clamps():
    assert data(brightness_msg(0))["value"] == 1
    assert data(brightness_msg(150))["value"] == 100
    assert data(brightness_msg(42))["value"] == 42


def test_color_msg_uses_rgb():
    assert data(color_msg(255, 0, 10)) == {"color": {"r": 255, "g": 0, "b": 10}, "colorTemInKelvin": 0}
    assert data(color_msg(300, -5, 10))["color"] == {"r": 255, "g": 0, "b": 10}


def test_kelvin_clamps():
    assert data(kelvin_msg(1500))["colorTemInKelvin"] == 2000
    assert data(kelvin_msg(12000))["colorTemInKelvin"] == 9000


def test_scan_and_status_msgs():
    assert json.loads(scan_msg()) == {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}
    assert json.loads(status_msg())["msg"]["cmd"] == "devStatus"


def test_parse_scan():
    assert parse_scan(SCAN_RESPONSE) == BulbInfo("192.168.1.23", "1F:80:C5:32:32:36:72:4E", "Hxxxx")


def test_parse_scan_garbage_returns_none():
    assert parse_scan(b"not json") is None
    assert parse_scan(STATUS_RESPONSE) is None


def test_parse_status():
    assert parse_status(STATUS_RESPONSE) == BulbStatus(True, 100, (255, 0, 0), 7200)
    assert parse_status(SCAN_RESPONSE) is None

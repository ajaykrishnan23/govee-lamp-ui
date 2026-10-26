import asyncio
import socket

import pytest

from lamp.govee.transport import GoveeTransport


class Capture(asyncio.DatagramProtocol):
    def __init__(self):
        self.packets: list[tuple[float, bytes]] = []
        self.loop = asyncio.get_running_loop()

    def datagram_received(self, data, addr):
        self.packets.append((self.loop.time(), data))


@pytest.fixture
async def capture():
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(Capture, local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    yield proto, port
    transport.close()


@pytest.fixture
async def govee():
    t = GoveeTransport(max_updates_per_sec=10)
    await t.start()
    yield t
    await t.close()


async def test_send_delivers_bytes(govee, capture):
    proto, port = capture
    govee.control_port = port
    govee.send("127.0.0.1", b"hello")
    await asyncio.sleep(0.05)
    assert [p for _, p in proto.packets] == [b"hello"]


async def test_send_latest_coalesces(govee, capture):
    proto, port = capture
    govee.control_port = port
    for i in range(50):
        govee.send_latest("127.0.0.1", "color", f"m{i}".encode())
    await asyncio.sleep(0.2)
    assert 1 <= len(proto.packets) <= 3
    assert proto.packets[-1][1] == b"m49"


async def test_send_latest_rate_limits_per_ip(govee, capture):
    proto, port = capture
    govee.control_port = port
    for i in range(10):
        govee.send_latest("127.0.0.1", "color", f"m{i}".encode())
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.15)
    times = [t for t, _ in proto.packets]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= 0.09 for g in gaps), gaps


async def test_send_latest_keeps_different_keys(govee, capture):
    proto, port = capture
    govee.control_port = port
    govee.send_latest("127.0.0.1", "color", b"c")
    govee.send_latest("127.0.0.1", "brightness", b"b")
    await asyncio.sleep(0.3)
    assert sorted(p for _, p in proto.packets) == [b"b", b"c"]


async def test_send_to_unreachable_ip_does_not_raise(govee, capture):
    proto, port = capture
    # closed port on localhost (ICMP unreachable) and a non-routable address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    closed = s.getsockname()[1]
    s.close()
    govee.control_port = closed
    govee.send("127.0.0.1", b"x")
    govee.send("10.255.255.1", b"x")
    govee.send_latest("10.255.255.1", "color", b"x")
    await asyncio.sleep(0.05)
    govee.control_port = port
    govee.send("127.0.0.1", b"after")
    await asyncio.sleep(0.05)
    assert [p for _, p in proto.packets] == [b"after"]


async def test_query_status_timeout_returns_none(govee, capture):
    _, port = capture
    govee.control_port = port  # capture never replies
    assert await govee.query_status("127.0.0.1", timeout=0.1) is None

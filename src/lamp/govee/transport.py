"""Async UDP transport for the Govee LAN API.

One socket sends commands to bulbs on :4003; another listens on :4002 for
scan replies and devStatus replies. `send_latest` coalesces rapid updates so
each bulb gets at most `max_updates_per_sec` flushes per second.
"""
import asyncio
import logging
import socket

from .protocol import (
    CONTROL_PORT,
    LISTEN_PORT,
    MULTICAST_GROUP,
    SCAN_PORT,
    BulbInfo,
    BulbStatus,
    parse_scan,
    parse_status,
    scan_msg,
    status_msg,
)

log = logging.getLogger(__name__)


class _Sender(asyncio.DatagramProtocol):
    def error_received(self, exc):
        log.debug("udp send error: %s", exc)


class _Listener(asyncio.DatagramProtocol):
    def __init__(self, owner: "GoveeTransport"):
        self.owner = owner

    def datagram_received(self, data, addr):
        self.owner._on_reply(data, addr[0])

    def error_received(self, exc):
        log.debug("udp listen error: %s", exc)


class GoveeTransport:
    def __init__(self, max_updates_per_sec: float):
        self.interval = 1.0 / max_updates_per_sec
        self.control_port = CONTROL_PORT
        self.listen_port = LISTEN_PORT
        self._send_tr: asyncio.DatagramTransport | None = None
        self._listen_tr: asyncio.DatagramTransport | None = None
        self._pending: dict[str, dict[str, bytes]] = {}
        self._flushers: dict[str, asyncio.Task] = {}
        self._last_flush: dict[str, float] = {}
        self._status_waiters: dict[str, list[asyncio.Future]] = {}
        self._scan_results: dict[str, BulbInfo] | None = None
        self._discover_lock = asyncio.Lock()

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        self._send_tr, _ = await loop.create_datagram_endpoint(_Sender, sock=sock)
        try:
            lsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            lsock.bind(("0.0.0.0", self.listen_port))
            self._listen_tr, _ = await loop.create_datagram_endpoint(lambda: _Listener(self), sock=lsock)
        except OSError as e:
            log.warning("could not listen on :%s (%s); discovery/status disabled", self.listen_port, e)

    async def close(self) -> None:
        for t in self._flushers.values():
            t.cancel()
        for tr in (self._send_tr, self._listen_tr):
            if tr:
                tr.close()

    def send(self, ip: str, msg: bytes) -> None:
        if not self._send_tr:
            return
        try:
            self._send_tr.sendto(msg, (ip, self.control_port))
        except OSError as e:
            log.debug("send to %s failed: %s", ip, e)

    def send_latest(self, ip: str, key: str, msg: bytes) -> None:
        self._pending.setdefault(ip, {})[key] = msg
        task = self._flushers.get(ip)
        if task is None or task.done():
            self._flushers[ip] = asyncio.get_running_loop().create_task(self._flush(ip))

    async def _flush(self, ip: str) -> None:
        loop = asyncio.get_running_loop()
        while self._pending.get(ip):
            wait = self._last_flush.get(ip, -1e9) + self.interval - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            batch = self._pending.pop(ip, {})
            self._last_flush[ip] = loop.time()
            for msg in batch.values():
                self.send(ip, msg)

    async def query_status(self, ip: str, timeout: float = 1.0) -> BulbStatus | None:
        fut = asyncio.get_running_loop().create_future()
        self._status_waiters.setdefault(ip, []).append(fut)
        self.send(ip, status_msg())
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            waiters = self._status_waiters.get(ip, [])
            if fut in waiters:
                waiters.remove(fut)

    async def discover(self, timeout: float = 3.0) -> list[BulbInfo]:
        async with self._discover_lock:  # overlapping scans would share one results dict
            return await self._discover(timeout)

    async def _discover(self, timeout: float) -> list[BulbInfo]:
        self._scan_results = {}
        if self._send_tr:
            for _ in range(2):
                # multicast per the docs, plus broadcast as a fallback for routers that drop multicast
                for dest in (MULTICAST_GROUP, "255.255.255.255"):
                    try:
                        self._send_tr.sendto(scan_msg(), (dest, SCAN_PORT))
                    except OSError as e:
                        log.warning("scan send to %s failed: %s", dest, e)
                await asyncio.sleep(timeout / 2)
        found, self._scan_results = list(self._scan_results.values()), None
        return found

    def _on_reply(self, data: bytes, src_ip: str) -> None:
        if self._scan_results is not None and (info := parse_scan(data)):
            self._scan_results[info.mac] = info
            return
        if status := parse_status(data):
            for fut in self._status_waiters.pop(src_ip, []):
                if not fut.done():
                    fut.set_result(status)


async def discover(timeout: float = 3.0) -> list[BulbInfo]:
    """One-off discovery with a temporary transport."""
    t = GoveeTransport(max_updates_per_sec=10)
    await t.start()
    try:
        return await t.discover(timeout)
    finally:
        await t.close()

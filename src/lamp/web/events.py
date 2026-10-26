"""Fan-out of live updates to Server-Sent Event subscribers."""
import asyncio
import json
from typing import AsyncIterator

_CLOSE = object()
MAX_BACKLOG = 200


class EventBus:
    def __init__(self):
        self._queues: set[asyncio.Queue] = set()

    def publish(self, type: str, data) -> None:
        event = {"type": type, "data": json.dumps(data)}
        for q in list(self._queues):
            if q.qsize() > MAX_BACKLOG:
                # a stalled client: drop its backlog and end its stream so the browser
                # reconnects and gets a fresh snapshot
                self._queues.discard(q)
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(_CLOSE)
                continue
            q.put_nowait(event)

    def listen(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        return q

    async def subscribe(self, initial: list[tuple[str, object]] = ()) -> AsyncIterator[str]:
        q = self.listen()
        try:
            for type, data in initial:
                yield f"event: {type}\ndata: {json.dumps(data)}\n\n"
            while True:
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15)
                    if e is _CLOSE:
                        return
                    yield f"event: {e['type']}\ndata: {e['data']}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            self._queues.discard(q)

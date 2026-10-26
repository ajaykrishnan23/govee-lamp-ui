"""Fan-out of live updates to Server-Sent Event subscribers."""
import asyncio
import json
from typing import AsyncIterator


class EventBus:
    def __init__(self):
        self._queues: set[asyncio.Queue] = set()

    def publish(self, type: str, data) -> None:
        event = {"type": type, "data": json.dumps(data)}
        for q in list(self._queues):
            if q.qsize() > 200:  # a stuck client shouldn't grow memory forever
                self._queues.discard(q)
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
                    yield f"event: {e['type']}\ndata: {e['data']}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            self._queues.discard(q)

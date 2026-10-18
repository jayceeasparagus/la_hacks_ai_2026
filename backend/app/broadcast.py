"""WebSocket fan-out: worker threads publish `{type, data}`; clients never block them.

`publish` may be called from any thread. The message is serialized in the caller's
thread and handed to the event loop with call_soon_threadsafe. Each client has a
bounded queue; when it is full the oldest `state` message is dropped first, then
the oldest message of any type, so a slow client only loses its own updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

log = logging.getLogger(__name__)
QUEUE_SIZE = 200


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


class _Client:
    def __init__(self, websocket: WebSocket, size: int):
        self.websocket = websocket
        self.size = size
        self.queue: deque[tuple[str, str]] = deque()  # (type, json text)
        self.ready = asyncio.Event()
        self.dropped = 0

    def put(self, kind: str, text: str) -> None:
        if len(self.queue) >= self.size:
            for index, (queued_kind, _) in enumerate(self.queue):
                if queued_kind == 'state':
                    del self.queue[index]
                    break
            else:
                self.queue.popleft()
            self.dropped += 1
        self.queue.append((kind, text))
        self.ready.set()


class Broadcaster:
    def __init__(self, queue_size: int = QUEUE_SIZE):
        self.queue_size = queue_size
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[_Client] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def unbind(self) -> None:
        self._loop = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, kind: str, data: Any) -> None:
        """Thread safe and non-blocking; silently does nothing without a running loop."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            text = json.dumps({'type': kind, 'data': to_jsonable(data)})
        except (TypeError, ValueError):
            log.exception('Could not serialize %s message', kind)
            return
        try:
            loop.call_soon_threadsafe(self._fanout, kind, text)
        except RuntimeError:  # loop closed between the check and the call
            pass

    def _fanout(self, kind: str, text: str) -> None:
        for client in list(self._clients):
            client.put(kind, text)

    async def serve(self, websocket: WebSocket, snapshot: Callable[[], dict]) -> None:
        """Accept, send `snapshot` first, then stream published messages until disconnect."""
        await websocket.accept()
        client = _Client(websocket, self.queue_size)
        # Registering and queueing the snapshot happen without an await in between,
        # so the snapshot is always the first message and no update is missed.
        self._clients.add(client)
        try:
            try:
                data = snapshot()
            except Exception:
                log.exception('Could not build the WebSocket snapshot')
                data = {'running': False, 'cameras': [], 'rule_states': []}
            client.queue.appendleft(('snapshot', json.dumps({'type': 'snapshot',
                                                             'data': to_jsonable(data)})))
            client.ready.set()
            sender = asyncio.create_task(self._send_loop(client))
            receiver = asyncio.create_task(self._receive_loop(websocket))
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    log.debug('WebSocket closed: %r', task.exception())
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            self._clients.discard(client)
            if client.dropped:
                log.info('WebSocket client dropped %d queued messages (slow client)', client.dropped)

    async def _send_loop(self, client: _Client) -> None:
        while True:
            await client.ready.wait()
            while client.queue:
                _, text = client.queue.popleft()
                await client.websocket.send_text(text)
            client.ready.clear()

    async def _receive_loop(self, websocket: WebSocket) -> None:
        try:
            while True:
                await websocket.receive_text()  # clients send nothing we need
        except (WebSocketDisconnect, RuntimeError):
            return

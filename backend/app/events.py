"""Bounded WebSocket fan-out; camera threads never wait for browser clients."""

import asyncio
from dataclasses import dataclass
import threading


@dataclass(eq=False)
class Subscriber:
    loop: object
    queue: asyncio.Queue
    overflowed: bool = False


class EventHub:
    def __init__(self, capacity=64):
        self.capacity = capacity
        self._clients = set()
        self._lock = threading.Lock()

    def subscribe(self):
        client = Subscriber(asyncio.get_running_loop(), asyncio.Queue(self.capacity))
        with self._lock:
            self._clients.add(client)
        return client

    def unsubscribe(self, client):
        with self._lock:
            self._clients.discard(client)

    @staticmethod
    def _offer(client, message):
        if client.overflowed:
            return
        if client.queue.full():
            client.overflowed = True
            while not client.queue.empty():
                client.queue.get_nowait()
            client.queue.put_nowait({'type': '__overflow__'})
            return
        client.queue.put_nowait(message)

    def publish(self, kind, data):
        message = {'type': kind, 'data': data}
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.loop.call_soon_threadsafe(self._offer, client, message)
            except RuntimeError:
                self.unsubscribe(client)

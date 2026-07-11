"""SSE イベントバス。

ワーカーが publish したイベントを、/events を購読している全クライアントへ
配信する。イベント形式は docs/news-picker-spec.md §9。
"""
from __future__ import annotations

import asyncio
import json


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """配信先イベントループを登録する (起動時に一度呼ぶ)。"""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        """全購読者へ配信。詰まっている購読者はそのイベントを取りこぼす。

        同期エンドポイント (スレッドプール) からも呼ばれる。asyncio.Queue は
        スレッドセーフではないため、ループ外からは call_soon_threadsafe で
        ループスレッドに委譲する (直接 put_nowait するとループが起床せず
        配信が次のイベントまで遅延する)。
        """
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            loop.call_soon_threadsafe(self._publish, event)
        else:
            self._publish(event)

    def _publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


def format_sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

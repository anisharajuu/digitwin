"""Live frame stream."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..simulation.engine import TwinEngine

router = APIRouter(tags=["stream"])


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    """Push every tick to the console.

    Each subscriber gets a small bounded queue. If a client cannot keep up its
    oldest frame is dropped rather than buffered - a twin that stalls because
    a browser tab went to sleep is worse than a browser tab that misses a
    second of history.
    """
    await websocket.accept()
    engine: TwinEngine | None = getattr(websocket.app.state, "engine", None)
    if engine is None:  # pragma: no cover
        await websocket.close(code=1013)
        return

    queue = engine.subscribe()
    try:
        # Send current state immediately so the console paints without
        # waiting a full tick for the next broadcast.
        await websocket.send_text(engine.frame().model_dump_json())
        while True:
            frame = await queue.get()
            await websocket.send_text(frame.model_dump_json())
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except RuntimeError:
        # Socket closed underneath us mid-send.
        pass
    finally:
        engine.unsubscribe(queue)
        with contextlib.suppress(RuntimeError):
            await websocket.close()

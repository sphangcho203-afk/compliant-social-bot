from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .jobs import JobQueue
from .media.ffmpeg import FFmpegEngine
from .content.persona import sanitize_caption


async def render_worker(queue: JobQueue, engine: FFmpegEngine, render_dir: Path) -> None:
    while True:
        job = await queue.claim("render")
        if not job:
            await asyncio.sleep(2)
            continue

        try:
            payload = json.loads(job["payload_json"])
            source = Path(payload["source"])
            output = render_dir / f'{job["id"]}.mp4'
            await engine.render_vertical(source, output)
            await queue.enqueue(
                "publish",
                {
                    "path": str(output),
                    "platform": payload["platform"],
                    "caption": sanitize_caption(payload["caption"]),
                },
            )
            await queue.finish(job["id"])
        except Exception as exc:
            await queue.fail(job["id"], repr(exc), retry=int(job["attempts"]) < 4)

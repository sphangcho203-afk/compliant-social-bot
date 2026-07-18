from __future__ import annotations

import asyncio
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


class FFmpegEngine:
    async def run(self, *args: str) -> None:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-y", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise FFmpegError(stderr.decode("utf-8", errors="replace")[-4000:])

    async def render_vertical(self, source: Path, output: Path) -> None:
        filters = [
            "scale=1080:1920:force_original_aspect_ratio=increase",
            "crop=1080:1920",
            "fps=30",
            "format=yuv420p",
        ]
        await self.run(
            "-i", str(source),
            "-vf", ",".join(filters),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output),
        )

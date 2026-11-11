"""Extract key frames from a video using ffmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path


def _probe_duration(video: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def extract_frames(video: Path, n: int = 4, max_side: int = 1280) -> list[bytes]:
    """Extract ``n`` frames evenly spaced across the video, as JPEG bytes."""
    try:
        duration = _probe_duration(video)
    except Exception:
        duration = 0.0

    if duration > 0:
        step = duration / (n + 1)
        timestamps = [step * (i + 1) for i in range(n)]
    else:
        timestamps = [0.0] * n

    frames: list[bytes] = []
    for ts in timestamps:
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{ts:.2f}",
            "-i", str(video),
            "-frames:v", "1",
            "-vf", f"scale='min({max_side},iw)':-2",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-",
        ]
        out = subprocess.run(cmd, capture_output=True, check=True)
        frames.append(out.stdout)
    return frames

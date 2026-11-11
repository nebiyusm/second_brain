"""Download videos with yt-dlp."""
from __future__ import annotations

from pathlib import Path

import yt_dlp


def download(url: str, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    outtmpl = str(out / "%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "noplaylist": True,
    }

    # TikTok/Instagram often require login cookies. Drop a `cookies.txt`
    # (Netscape format) in the project root and it will be used automatically.
    cookies = Path("cookies.txt")
    if cookies.exists():
        ydl_opts["cookiefile"] = str(cookies)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    path: str | None = None
    requested = info.get("requested_downloads")
    if requested and isinstance(requested, list) and requested:
        path = requested[0].get("filepath")
    if not path:
        path = info.get("_filename")
    if not path:
        raise RuntimeError("yt-dlp did not return a file path")

    return {
        "path": Path(path),
        "title": info.get("title", ""),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "webpage_url": info.get("webpage_url", url),
    }

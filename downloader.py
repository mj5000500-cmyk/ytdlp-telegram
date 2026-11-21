"""
downloader.py - yt-dlp wrapper with portable/system ffmpeg, ffprobe, and deno.

Part of the "ytdl-telegram" project.
Redirects directly to downloader_v4.
"""
from downloader_v4 import (
    TOOLS_DIR,
    IS_WINDOWS,
    find_tool_path,
    check_required_tools,
    get_video_info,
    DownloadResult,
    YTDownloader,
)

__all__ = [
    "TOOLS_DIR",
    "IS_WINDOWS",
    "find_tool_path",
    "check_required_tools",
    "get_video_info",
    "DownloadResult",
    "YTDownloader",
]

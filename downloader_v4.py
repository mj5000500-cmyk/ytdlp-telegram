"""
downloader_v4.py - yt-dlp wrapper with portable/system ffmpeg, ffprobe, and deno.

Part of the "ytdl-telegram" project.
Features:
- Cross-platform support: Windows and Linux / Google Colab
- Portable tools detection (./tools folder) with system PATH fallback
- Passes js_runtimes with Deno for YouTube extraction without node.js
- Single-source-of-truth state tracking: uses SQLite jobs.db
- Prefers AVC1 (H.264) video codec for Telegram streaming compatibility
- Extracts rich video metadata (formats, resolutions, estimated MB size, thumbnail)
- Real-time download progress hook (percentage, bytes, speed in B/s, ETA in seconds)
- Supports in-chat / project root cookies.txt for age/member restricted videos
"""

import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass

# Locate script directory and portable tools directory
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_TOOLS_DIR = os.getenv("TOOLS_DIR")
TOOLS_DIR = Path(ENV_TOOLS_DIR).resolve() if ENV_TOOLS_DIR else (SCRIPT_DIR / "tools")

IS_WINDOWS = platform.system() == "Windows"

# Prepend portable tools to system PATH if present
tools_str = str(TOOLS_DIR)
current_path = os.environ.get("PATH", "")
if tools_str not in current_path:
    os.environ["PATH"] = tools_str + os.pathsep + current_path

# Import yt_dlp
try:
    import yt_dlp
except ImportError:
    yt_dlp = None


def find_tool_path(tool_name: str, tools_dir: Optional[Path] = None) -> Optional[str]:
    """
    Finds executable path from tools directory or system PATH.
    Works seamlessly across Windows (.exe) and Linux / Google Colab.
    """
    td = tools_dir or TOOLS_DIR
    candidates = [f"{tool_name}.exe", tool_name] if IS_WINDOWS else [tool_name, f"{tool_name}.exe"]
    for c in candidates:
        target = td / c
        if target.is_file():
            return str(target)
    for c in candidates:
        system_found = shutil.which(c)
        if system_found:
            return system_found
    return None


def check_required_tools(tools_dir: Optional[Path] = None) -> None:
    """Verifies that ffmpeg and ffprobe are available. Warns if deno is missing."""
    td = tools_dir or TOOLS_DIR
    ffmpeg_p = find_tool_path("ffmpeg", td)
    ffprobe_p = find_tool_path("ffprobe", td)
    missing = []
    if not ffmpeg_p:
        missing.append("ffmpeg")
    if not ffprobe_p:
        missing.append("ffprobe")

    if missing:
        print("\n" + "=" * 60)
        print("  [ERROR] Missing required media tool(s)!")
        print(f"  Target tools folder: {td}")
        print("\n  Missing:")
        for m in missing:
            print(f"    [X] {m}")
        if IS_WINDOWS:
            print(f"\n  Please place ffmpeg.exe and ffprobe.exe into: {td}")
        else:
            print("\n  On Linux / Google Colab, run: !apt-get install -y ffmpeg")
        print("=" * 60 + "\n")
        sys.exit(1)


def get_video_info(
    url: str,
    cookies_file: Optional[str] = None,
    tools_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Extracts rich video metadata and available download formats with estimated MB sizes.
    Used for sending interactive thumbnail previews and quality selection buttons in Telegram.
    """
    if yt_dlp is None:
        return None

    td = tools_dir or TOOLS_DIR
    ffmpeg_p = find_tool_path("ffmpeg", td)
    deno_p = find_tool_path("deno", td)

    # Resolve cookies
    cf = cookies_file or os.getenv("COOKIES_FILE")
    if not cf and os.path.exists("cookies.txt"):
        cf = "cookies.txt"

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "remote_components": ["ejs:github"],
    }

    if ffmpeg_p:
        ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_p).parent)
    if deno_p:
        ydl_opts["js_runtimes"] = {"deno": {"path": deno_p}}
    if cf and os.path.exists(cf):
        ydl_opts["cookiefile"] = cf

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"Error extracting metadata from {url}: {e}")
        return None

    if not info:
        return None

    # Handle playlist detection
    if "entries" in info and info.get("entries") is not None:
        entries = [e for e in info.get("entries", []) if e]
        playlist_title = info.get("title") or "YouTube Playlist"
        return {
            "is_playlist": True,
            "title": playlist_title,
            "count": len(entries),
            "url": url,
        }

    vid_id = info.get("id", "")
    title = info.get("title", "Unknown Title")
    uploader = info.get("uploader") or info.get("channel") or "Unknown Channel"
    duration = int(info.get("duration") or 0)
    thumbnail = info.get("thumbnail") or ""

    # Format duration string (HH:MM:SS or MM:SS)
    m, s = divmod(duration, 60)
    h, m = divmod(m, 60)
    duration_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    formats = info.get("formats", [])

    # Calculate best audio stream size
    best_audio = None
    for f in formats:
        if f.get("acodec") != "none" and f.get("vcodec") == "none":
            if not best_audio or (f.get("abr") or 0) > (best_audio.get("abr") or 0):
                best_audio = f

    a_size = 0
    if best_audio:
        a_size = (
            best_audio.get("filesize")
            or best_audio.get("filesize_approx")
            or int((best_audio.get("abr") or 128) * 1000 / 8 * duration)
        )

    # Check common target heights
    target_heights = [2160, 1440, 1080, 720, 480, 360]
    qualities: Dict[str, Dict[str, Any]] = {}

    for th in target_heights:
        best_v = None
        for f in formats:
            if f.get("height") == th and f.get("vcodec") != "none":
                # Prefer avc1/h264 codec if multiple
                is_avc = str(f.get("vcodec", "")).startswith("avc1")
                if not best_v:
                    best_v = f
                elif is_avc and not str(best_v.get("vcodec", "")).startswith("avc1"):
                    best_v = f
                elif (f.get("vbr") or 0) > (best_v.get("vbr") or 0):
                    best_v = f

        if best_v:
            v_size = (
                best_v.get("filesize")
                or best_v.get("filesize_approx")
                or int((best_v.get("vbr") or 1000) * 1000 / 8 * duration)
            )
            tot_mb = (v_size + a_size) / (1024 * 1024)
            tag = f"{th}p"
            qualities[str(th)] = {
                "label": tag,
                "size_mb": round(tot_mb, 1),
                "height": th,
                "is_audio": False,
            }

    # MP3 Audio option
    audio_mb = round(a_size / (1024 * 1024), 1) if a_size else 0.0
    qualities["audio"] = {
        "label": "MP3 Audio",
        "size_mb": audio_mb,
        "height": 0,
        "is_audio": True,
    }

    return {
        "is_playlist": False,
        "id": vid_id,
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "duration_str": duration_str,
        "thumbnail": thumbnail,
        "qualities": qualities,
        "url": url,
    }


@dataclass
class DownloadResult:
    """Represents the outcome of a download operation."""
    id: str
    title: str
    path: Optional[str] = None
    size: int = 0
    duration: float = 0.0
    success: bool = True
    error: Optional[str] = None


class YTDownloader:
    """Downloader engine using yt-dlp Python API with portable and system tools support."""

    def __init__(
        self,
        dest_dir: Optional[str] = None,
        cookies_file: Optional[str] = None,
        tools_dir: Optional[Path] = None,
        concurrent_fragments: int = 8,
    ):
        self.tools_dir = tools_dir or TOOLS_DIR
        check_required_tools(self.tools_dir)

        # Base download directory
        self.dest_dir = dest_dir or os.getenv("DOWNLOAD_DIR", "downloads")
        os.makedirs(self.dest_dir, exist_ok=True)

        # Optional cookies.txt
        env_cookie = os.getenv("COOKIES_FILE")
        self.cookies_file = cookies_file or env_cookie
        if not self.cookies_file and os.path.exists("cookies.txt"):
            self.cookies_file = "cookies.txt"

        self.concurrent_fragments = concurrent_fragments

    def _build_options(
        self,
        quality: str = "1080",
        is_audio: bool = False,
        playlist_items: Optional[str] = None,
        playlist_reverse: bool = False,
        live_from_start: bool = False,
    ) -> Dict[str, Any]:
        """Builds yt-dlp options dictionary with portable/system tools paths."""
        tag = "audio" if is_audio else f"{quality}p"

        clean_dest = os.path.abspath(self.dest_dir).replace("\\", "/")
        outtmpl = f"{clean_dest}/%(playlist_title&{{}}|.).60s/%(title).70s [%(id)s] [{tag}].%(ext)s"

        ffmpeg_p = find_tool_path("ffmpeg", self.tools_dir)
        deno_p = find_tool_path("deno", self.tools_dir)

        ydl_opts: Dict[str, Any] = {
            "outtmpl": {"default": outtmpl},
            "overwrites": True,
            "concurrent_fragment_downloads": self.concurrent_fragments,
            "remote_components": ["ejs:github"],
            "quiet": False,
            "no_warnings": False,
            "ignoreerrors": True,
        }

        if ffmpeg_p:
            ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_p).parent)

        if deno_p:
            ydl_opts["js_runtimes"] = {"deno": {"path": deno_p}}

        # Always check cookies dynamically so new cookies uploaded in chat take effect immediately
        cf = self.cookies_file or os.getenv("COOKIES_FILE")
        if not cf and os.path.exists("cookies.txt"):
            cf = "cookies.txt"
        if cf and os.path.exists(cf):
            ydl_opts["cookiefile"] = cf

        if live_from_start:
            ydl_opts["live_from_start"] = True

        if is_audio:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ]
        else:
            q_val = int(quality) if quality.isdigit() else 1080
            ydl_opts["format"] = (
                f"bestvideo[height<={q_val}][vcodec^=avc1]+bestaudio/best[height<={q_val}]/"
                f"bestvideo[height<={q_val}]+bestaudio/best[height<={q_val}]/"
                f"bestvideo[height<={q_val}]+bestaudio/"
                f"best[height<={q_val}]/"
                f"bestvideo+bestaudio/best"
            )
            ydl_opts["merge_output_format"] = "mp4"

        if playlist_items:
            ydl_opts["playlist_items"] = playlist_items

        if playlist_reverse:
            ydl_opts["playlistreverse"] = True

        return ydl_opts

    def download(
        self,
        urls: List[str],
        quality: str = "1080",
        is_audio: bool = False,
        playlist_items: Optional[str] = None,
        playlist_reverse: bool = False,
        live_from_start: bool = False,
        on_progress: Optional[Callable[..., None]] = None,
    ) -> List[DownloadResult]:
        """
        Downloads one or more URLs and returns a list of DownloadResult objects.
        Optional on_progress callback receives:
            (percentage, current_bytes, total_bytes, speed_bytes_per_sec, eta_seconds).
        """
        results: List[DownloadResult] = []
        finished_files: Dict[str, str] = {}

        def progress_hook(d: Dict[str, Any]) -> None:
            status = d.get("status")
            if status == "downloading" and on_progress:
                downloaded = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                pct = (downloaded / total * 100) if total else 0.0
                speed = d.get("speed") or 0.0
                eta = d.get("eta") or 0.0
                try:
                    on_progress(pct, downloaded, total, speed, eta)
                except TypeError:
                    try:
                        on_progress(pct, downloaded, total)
                    except Exception:
                        pass
                except Exception:
                    pass

            elif status == "finished":
                fn = d.get("filename")
                info = d.get("info_dict", {})
                vid_id = info.get("id")
                if vid_id and fn:
                    finished_files[vid_id] = os.path.abspath(fn)

        def postprocessor_hook(d: Dict[str, Any]) -> None:
            if d.get("status") == "finished":
                info = d.get("info_dict", {})
                vid_id = info.get("id")
                filepath = info.get("filepath") or d.get("filepath") or info.get("_filename")
                if vid_id and filepath:
                    finished_files[vid_id] = os.path.abspath(filepath)

        ydl_opts = self._build_options(
            quality=quality,
            is_audio=is_audio,
            playlist_items=playlist_items,
            playlist_reverse=playlist_reverse,
            live_from_start=live_from_start,
        )

        ydl_opts["progress_hooks"] = [progress_hook]
        ydl_opts["postprocessor_hooks"] = [postprocessor_hook]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for url in urls:
                try:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        results.append(
                            DownloadResult(
                                id="",
                                title=url,
                                success=False,
                                error="Could not extract metadata",
                            )
                        )
                        continue

                    entries = info.get("entries")
                    if entries is not None:
                        video_list = [e for e in entries if e]
                    else:
                        video_list = [info]

                    for v in video_list:
                        vid_id = v.get("id", "")
                        vid_title = v.get("title", "Unknown")
                        vid_duration = float(v.get("duration") or 0.0)

                        expected_fn = ydl.prepare_filename(v)
                        base, _ = os.path.splitext(expected_fn)
                        expected_merged = f"{base}.mp3" if is_audio else f"{base}.mp4"

                        final_path: Optional[str] = None

                        if os.path.exists(expected_merged) and os.path.getsize(expected_merged) > 0:
                            final_path = os.path.abspath(expected_merged)
                        elif vid_id in finished_files:
                            candidate = finished_files[vid_id]
                            if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                                c_name = os.path.basename(candidate)
                                if (is_audio and c_name.endswith(".mp3")) or (not is_audio and c_name.endswith(".mp4")):
                                    final_path = candidate
                                else:
                                    if os.path.exists(expected_merged):
                                        final_path = os.path.abspath(expected_merged)
                                    else:
                                        final_path = candidate

                        if final_path and os.path.exists(final_path):
                            f_size = os.path.getsize(final_path)
                            results.append(
                                DownloadResult(
                                    id=vid_id,
                                    title=vid_title,
                                    path=final_path,
                                    size=f_size,
                                    duration=vid_duration,
                                    success=True,
                                )
                            )
                        else:
                            results.append(
                                DownloadResult(
                                    id=vid_id,
                                    title=vid_title,
                                    success=False,
                                    error="Merged output file not found on disk",
                                )
                            )

                except Exception as e:
                    results.append(
                        DownloadResult(
                            id="",
                            title=url,
                            success=False,
                            error=str(e),
                        )
                    )

        return results

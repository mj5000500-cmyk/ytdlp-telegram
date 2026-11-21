"""
bot_v2.py - Interactive Telegram Bot Controller for ytdl-telegram.

Features:
- Auto-fetches YouTube link details (Title, Channel, Duration, Thumbnail)
- Displays Interactive Inline Buttons with available qualities and accurate MB sizes
- Real-time live status displaying:
    * Download Progress Bar, Download Speed (MB/s), and ETA
    * Fast Parallel Upload Progress Bar, Upload Speed (MB/s), and ETA
- Telegram in-chat Cookies management:
    * Send 'cookies.txt' file directly to the chat to set/update cookies
    * /cookies - view cookie status (lines count, YouTube entries, size)
    * /clearcookies - delete cookies file
- Dual Upload Modes (bot / user account session)
- Full Playlist support with interactive quality selection & sequential processing
- Native Video Attributes (width, height, duration) + auto-generated thumbnails
- Cross-platform support: Windows & Google Colab / Linux
- Rotating file logging in logs/bot.log
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request

# Setup directories
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LOGS_DIR = BASE_DIR / "logs"
DOWNLOADS_DIR = BASE_DIR / "downloads"
COOKIES_PATH = BASE_DIR / "cookies.txt"

LOGS_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Attempt to load .env relative to script directory
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

# -------------------------------------------------------------
# Rotating File Logger Configuration
# -------------------------------------------------------------
logger = logging.getLogger("ytdl_telegram")
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(asctime)s [%(levelname)s]: %(message)s", datefmt="%H:%M:%S")
console_handler.setFormatter(console_formatter)

log_file_path = LOGS_DIR / "bot.log"
file_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(file_formatter)

if not logger.handlers:
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

import yt_dlp
from telethon import TelegramClient, events, errors, Button
from telethon.tl.custom import Message

from downloader_v4 import (
    YTDownloader,
    TOOLS_DIR,
    check_required_tools,
    get_video_info,
    find_tool_path,
    IS_WINDOWS,
)
from state_v2 import StateManager, Job
from uploader_v4 import TelegramUploader, CRYPTG_STATUS, UPLOAD_MODE

# -------------------------------------------------------------
# Configuration & Security Verification
# -------------------------------------------------------------
raw_api_id = os.getenv("TELEGRAM_API_ID")
raw_api_hash = os.getenv("TELEGRAM_API_HASH")
raw_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
raw_allowed_uid = os.getenv("ALLOWED_USER_ID")

if not raw_api_id or not raw_api_hash or not raw_bot_token:
    logger.error("Telegram credentials (API_ID, API_HASH, BOT_TOKEN) are missing in .env!")
    sys.exit(1)

if not raw_allowed_uid or not str(raw_allowed_uid).strip().lstrip("-").isdigit():
    logger.error("ALLOWED_USER_ID is not configured in .env! (e.g. ALLOWED_USER_ID=123456789)")
    sys.exit(1)

API_ID = int(raw_api_id.strip())
API_HASH = raw_api_hash.strip()
BOT_TOKEN = raw_bot_token.strip()
ALLOWED_USER_ID = int(raw_allowed_uid.strip())

bot = TelegramClient("ytdl_telegram_bot_session", API_ID, API_HASH)
state = StateManager()

# Regex to detect YouTube links
YT_LINK_REGEX = re.compile(
    r'(https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/|playlist\?list=)|youtu\.be/)[\w\-?&=%#]+)'
)

# In-memory cache for inspected video information
video_cache: Dict[str, Dict[str, Any]] = {}
active_single_downloads: Dict[str, bool] = {}


# -------------------------------------------------------------
# Helper: Progress Bar Generator
# -------------------------------------------------------------
def make_progress_bar(percent: float, length: int = 10) -> str:
    filled = int((max(0.0, min(100.0, percent)) / 100.0) * length)
    return "█" * filled + "░" * (length - filled)


# -------------------------------------------------------------
# Background Pipeline Worker (For Queued Playlists)
# -------------------------------------------------------------
class BackgroundWorker:
    """Manages the background download/upload loop for playlists and batch jobs."""

    def __init__(self, bot_client: TelegramClient, state_mgr: StateManager):
        self.bot = bot_client
        self.state = state_mgr
        self.is_running = False
        self.is_paused = False
        self.cancel_requested = False
        self.current_job: Optional[Job] = None
        self.status_msg: Optional[Message] = None
        self.last_edit_time = 0.0
        self._status_lock = asyncio.Lock()
        self.worker_task: Optional[asyncio.Task] = None
        self.target_chat_id = ALLOWED_USER_ID
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def trigger(self) -> None:
        if not self.is_running:
            self.cancel_requested = False
            self.worker_task = asyncio.create_task(self.run_loop())

    def pause(self) -> None:
        self.is_paused = True
        logger.info("Worker pause requested by user.")

    def resume(self) -> None:
        self.is_paused = False
        logger.info("Worker resume requested by user.")
        self.trigger()

    def cancel(self) -> None:
        self.cancel_requested = True
        cleared = self.state.cancel_queued_jobs()
        logger.warning("Worker cancellation requested. Cleared %d pending queued jobs.", cleared)

    def dispatch_status(self, coro) -> None:
        try:
            curr_loop = asyncio.get_running_loop()
            if curr_loop == self.loop:
                curr_loop.create_task(coro)
                return
        except RuntimeError:
            pass

        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def update_live_status(
        self,
        current_num: int,
        total_num: int,
        title: str,
        stage: str,
        percent: float,
        transferred_str: str = "",
        speed_mbps: float = 0.0,
        eta_seconds: float = 0.0,
        force: bool = False,
    ) -> None:
        now = time.time()
        if not force and (now - self.last_edit_time < 3.0) and percent < 100.0:
            return
        if self._status_lock.locked():
            return

        async with self._status_lock:
            self.last_edit_time = time.time()
            bar = make_progress_bar(percent)
            short_title = title if len(title) <= 50 else title[:47] + "..."
            extra = f" ({transferred_str})" if transferred_str else ""

            speed_line = ""
            if speed_mbps > 0.0 or eta_seconds > 0.0:
                eta_str = f"{int(eta_seconds // 60)}m {int(eta_seconds % 60):02d}s"
                speed_line = f"\n🚀 **Speed:** `{speed_mbps:4.2f} MB/s` | ⏳ **ETA:** `{eta_str}`"

            text = (
                f"🎬 **[{current_num}/{total_num}] {short_title}**\n\n"
                f"⚙️ **Stage:** {stage}\n"
                f"📊 **Progress:** `[{bar}]` {percent:5.1f}%{extra}"
                f"{speed_line}\n"
                f"⏱️ _Updating live every 3s..._"
            )

            try:
                if not self.status_msg:
                    self.status_msg = await self.bot.send_message(self.target_chat_id, text)
                else:
                    await self.status_msg.edit(text)
            except errors.MessageNotModifiedError:
                pass
            except errors.FloodWaitError as fwe:
                logger.warning("FloodWait encountered in status edit: sleeping %ds", fwe.seconds)
                await asyncio.sleep(fwe.seconds + 1)
            except Exception as e:
                logger.debug("Status edit error: %s", e)

    async def run_loop(self) -> None:
        self.is_running = True
        self.loop = asyncio.get_running_loop()
        logger.info("Pipeline background worker started.")

        recovered = self.state.reset_interrupted_jobs()
        if recovered > 0:
            logger.info("Recovered %d interrupted job(s) back to queue.", recovered)

        uploader = TelegramUploader()
        downloader = YTDownloader()
        await uploader.connect()

        processed_in_this_run = 0

        try:
            while not self.cancel_requested:
                if self.is_paused:
                    await asyncio.sleep(1.0)
                    continue

                job = self.state.get_next_pending_job()
                if not job:
                    logger.info("No more pending jobs in queue.")
                    break

                self.current_job = job
                processed_in_this_run += 1
                stats = self.state.get_stats()
                cur_num = stats["uploaded"] + 1
                tot_num = stats["total"]

                logger.info(
                    "Processing [%d/%d]: '%s' (ID: %s, Quality: %s)",
                    cur_num, tot_num, job.title, job.video_id, job.quality
                )

                downloaded_file: Optional[str] = None
                if job.file_path and os.path.isfile(job.file_path) and os.path.getsize(job.file_path) > 0:
                    downloaded_file = job.file_path
                    logger.info("Using existing downloaded file for '%s'", job.video_id)
                else:
                    self.state.mark_downloading(job.video_id)
                    await self.update_live_status(
                        current_num=cur_num,
                        total_num=tot_num,
                        title=job.title,
                        stage="📥 Downloading from YouTube",
                        percent=0.0,
                        force=True,
                    )

                    dl_start_time = time.time()
                    last_dl_tick = [0.0]

                    def dl_progress(pct: float, cur_bytes: int, tot_bytes: int, spd_bps: float = 0.0, eta_s: float = 0.0) -> None:
                        now = time.time()
                        if (now - last_dl_tick[0] < 2.5) and pct < 100.0:
                            return
                        last_dl_tick[0] = now
                        elapsed = max(0.01, now - dl_start_time)
                        if not spd_bps:
                            spd_bps = cur_bytes / elapsed
                        speed_mb = spd_bps / (1024 * 1024)
                        if not eta_s:
                            rem_bytes = max(0, tot_bytes - cur_bytes)
                            eta_s = (rem_bytes / spd_bps) if spd_bps > 0 else 0

                        cur_mb = cur_bytes / (1024 * 1024)
                        tot_mb = tot_bytes / (1024 * 1024)
                        t_str = f"{cur_mb:.1f}/{tot_mb:.1f} MB"

                        self.dispatch_status(
                            self.update_live_status(
                                current_num=cur_num,
                                total_num=tot_num,
                                title=job.title,
                                stage="📥 Downloading from YouTube",
                                percent=pct,
                                transferred_str=t_str,
                                speed_mbps=speed_mb,
                                eta_seconds=eta_s,
                            )
                        )

                    is_audio = (job.quality.lower() == "audio")
                    watch_url = f"https://www.youtube.com/watch?v={job.video_id}"

                    loop = asyncio.get_running_loop()
                    dl_results = await loop.run_in_executor(
                        None,
                        lambda: downloader.download(
                            urls=[watch_url],
                            quality=job.quality,
                            is_audio=is_audio,
                            on_progress=dl_progress,
                        ),
                    )

                    if self.cancel_requested:
                        logger.warning("Pipeline cancelled during download phase.")
                        break

                    if not dl_results or not dl_results[0].success or not dl_results[0].path:
                        err = dl_results[0].error if dl_results else "Download returned no path"
                        retries = self.state.record_failure(job.video_id, f"Download error: {err}")
                        logger.error("Download failed for '%s' (Attempt %d/3): %s", job.video_id, retries, err)
                        continue

                    downloaded_file = dl_results[0].path
                    self.state.mark_downloaded(job.video_id, downloaded_file)

                # PHASE 2: UPLOAD
                upload_stage_name = f"📤 Fast Parallel Upload [{uploader.upload_mode.upper()} Mode]"
                self.state.mark_uploading(job.video_id)
                await self.update_live_status(
                    current_num=cur_num,
                    total_num=tot_num,
                    title=job.title,
                    stage=upload_stage_name,
                    percent=0.0,
                    force=True,
                )

                def up_progress(pct: float, cur_bytes: int, tot_bytes: int, spd_mbps: float, eta_s: float) -> None:
                    cur_mb = cur_bytes / (1024 * 1024)
                    tot_mb = tot_bytes / (1024 * 1024)
                    t_str = f"{cur_mb:.1f}/{tot_mb:.1f} MB"
                    self.dispatch_status(
                        self.update_live_status(
                            current_num=cur_num,
                            total_num=tot_num,
                            title=job.title,
                            stage=upload_stage_name,
                            percent=pct,
                            transferred_str=t_str,
                            speed_mbps=spd_mbps,
                            eta_seconds=eta_s,
                        )
                    )

                upload_res = await uploader.upload_file(
                    filepath=downloaded_file,
                    caption=job.title,
                    on_progress=up_progress,
                )

                if self.cancel_requested:
                    logger.warning("Pipeline cancelled during upload phase.")
                    break

                if not upload_res.success:
                    retries = self.state.record_failure(
                        job.video_id,
                        f"Upload error: {upload_res.error}",
                        keep_file_path=True,
                    )
                    logger.error("Upload failed for '%s': %s", job.video_id, upload_res.error)
                    continue

                msg_ids = ",".join(str(m) for m in upload_res.message_ids)
                self.state.mark_uploaded(job.video_id, telegram_message_id=msg_ids)
                logger.info("Successfully uploaded '%s' (Msg IDs: %s)", job.video_id, msg_ids)

            if processed_in_this_run > 0:
                final_stats = self.state.get_stats()
                failed_jobs = self.state.get_failed_jobs()

                summary_text = (
                    "🎉 **Batch Complete!**\n\n"
                    f"✅ **Succeeded:** {final_stats['uploaded']}\n"
                    f"❌ **Failed:** {len(failed_jobs)}\n"
                    f"📁 **Total Tracked:** {final_stats['total']}\n"
                )
                if failed_jobs:
                    summary_text += "\n⚠️ **Failed Titles:**\n"
                    for f in failed_jobs[:10]:
                        summary_text += f"• `{f.video_id}` — {f.title[:35]}...\n"

                await self.bot.send_message(self.target_chat_id, summary_text)

        except Exception as e:
            logger.exception("Error in worker loop: %s", e)
        finally:
            await uploader.disconnect()
            self.is_running = False
            self.current_job = None
            self.status_msg = None


worker = BackgroundWorker(bot_client=bot, state_mgr=state)


# -------------------------------------------------------------
# Single Video Download & Upload Worker (Interactive Buttons)
# -------------------------------------------------------------
async def process_single_video_interactive(
    chat_id: int,
    status_msg: Message,
    video_id: str,
    quality_key: str,
    video_info: Dict[str, Any],
) -> None:
    """Processes a single video requested through inline buttons."""
    title = video_info.get("title", "YouTube Video")
    url = video_info.get("url") or f"https://www.youtube.com/watch?v={video_id}"
    is_audio = (quality_key == "audio")
    quality_label = "MP3 Audio" if is_audio else f"{quality_key}p"

    uploader = TelegramUploader()
    downloader = YTDownloader()
    await uploader.connect()

    last_edit = [0.0]

    async def update_card(stage: str, percent: float, trans_mb: str, speed_mb: float, eta_sec: float, force: bool = False):
        now = time.time()
        if not force and (now - last_edit[0] < 2.5) and percent < 100.0:
            return
        last_edit[0] = now

        bar = make_progress_bar(percent)
        eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60):02d}s" if eta_sec > 0 else "--:--"

        text = (
            f"🎬 **{title}**\n"
            f"⚙️ **Quality:** `{quality_label}`\n\n"
            f"📍 **Stage:** {stage}\n"
            f"📊 **Progress:** `[{bar}]` {percent:5.1f}% ({trans_mb})\n"
            f"🚀 **Speed:** `{speed_mb:4.2f} MB/s` | ⏳ **ETA:** `{eta_str}`"
        )
        try:
            await status_msg.edit(text)
        except errors.MessageNotModifiedError:
            pass
        except Exception as e:
            logger.debug("Interactive status edit error: %s", e)

    try:
        # Phase 1: Download
        await update_card(
            stage="📥 Downloading from YouTube...",
            percent=0.0,
            trans_mb="0.0 MB",
            speed_mb=0.0,
            eta_sec=0.0,
            force=True,
        )

        dl_start_time = time.time()

        def dl_progress(pct: float, cur_bytes: int, tot_bytes: int, spd_bps: float = 0.0, eta_s: float = 0.0) -> None:
            now = time.time()
            elapsed = max(0.01, now - dl_start_time)
            if not spd_bps:
                spd_bps = cur_bytes / elapsed
            spd_mb = spd_bps / (1024 * 1024)
            if not eta_s:
                rem = max(0, tot_bytes - cur_bytes)
                eta_s = rem / spd_bps if spd_bps > 0 else 0.0
            cur_mb = cur_bytes / (1024 * 1024)
            tot_mb = tot_bytes / (1024 * 1024)
            t_str = f"{cur_mb:.1f}/{tot_mb:.1f} MB"

            asyncio.run_coroutine_threadsafe(
                update_card("📥 Downloading from YouTube...", pct, t_str, spd_mb, eta_s),
                bot.loop,
            )

        loop = asyncio.get_running_loop()
        dl_results = await loop.run_in_executor(
            None,
            lambda: downloader.download(
                urls=[url],
                quality=quality_key if not is_audio else "1080",
                is_audio=is_audio,
                on_progress=dl_progress,
            ),
        )

        if not dl_results or not dl_results[0].success or not dl_results[0].path:
            err = dl_results[0].error if dl_results else "Download failed"
            await status_msg.edit(f"❌ **Download Failed:** {err}")
            return

        downloaded_file = dl_results[0].path
        file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)

        # Phase 2: Upload
        upload_stage = f"📤 Fast Uploading to Telegram [{uploader.upload_mode.upper()} Mode]..."
        await update_card(
            stage=upload_stage,
            percent=0.0,
            trans_mb=f"0.0/{file_size_mb:.1f} MB",
            speed_mb=0.0,
            eta_sec=0.0,
            force=True,
        )

        def up_progress(pct: float, cur_bytes: int, tot_bytes: int, spd_mbps: float, eta_sec: float) -> None:
            cur_mb = cur_bytes / (1024 * 1024)
            tot_mb = tot_bytes / (1024 * 1024)
            t_str = f"{cur_mb:.1f}/{tot_mb:.1f} MB"
            asyncio.run_coroutine_threadsafe(
                update_card(upload_stage, pct, t_str, spd_mbps, eta_sec),
                bot.loop,
            )

        upload_res = await uploader.upload_file(
            filepath=downloaded_file,
            caption=f"🎬 {title}\n⚙️ {quality_label}",
            target_chat=chat_id,
            on_progress=up_progress,
        )

        if not upload_res.success:
            await status_msg.edit(f"❌ **Upload Failed:** {upload_res.error}")
            return

        # Done!
        await status_msg.edit(
            f"✅ **Completed & Uploaded!**\n\n"
            f"🎬 **Title:** {title}\n"
            f"⚙️ **Quality:** `{quality_label}`\n"
            f"📁 **Size:** `{file_size_mb:.1f} MB`\n"
            f"⚡ **Average Upload Speed:** `{upload_res.average_speed_mbps:.2f} MB/s`\n"
            f"⏱️ **Upload Time:** `{upload_res.elapsed_seconds:.1f}s`"
        )

    except Exception as e:
        logger.exception("Interactive task error: %s", e)
        await status_msg.edit(f"❌ **Unexpected Error:** {e}")
    finally:
        active_single_downloads.pop(video_id, None)
        await uploader.disconnect()


# -------------------------------------------------------------
# Telegram Event Handlers
# -------------------------------------------------------------
@bot.on(events.NewMessage)
async def handle_incoming_message(event: events.NewMessage.Event) -> None:
    """Security filter: ignores any user other than ALLOWED_USER_ID."""
    if event.sender_id != ALLOWED_USER_ID:
        logger.warning(
            "Ignored unauthorized message from sender_id: %s (Username: @%s)",
            event.sender_id,
            getattr(event.sender, "username", "none"),
        )
        return

    text = (event.raw_text or "").strip()

    # ---------------------------------------------------------
    # 1. FILE UPLOAD: Handle cookies.txt upload
    # ---------------------------------------------------------
    if event.message.file and (event.message.file.name or "").endswith(".txt"):
        fn = event.message.file.name or "cookies.txt"
        loading_msg = await event.reply(f"📥 Receiving `{fn}` as YouTube cookies...")
        try:
            await event.message.download_media(file=COOKIES_PATH)
            with open(COOKIES_PATH, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            total_lines = len(lines)
            yt_entries = sum(1 for line in lines if "youtube.com" in line.lower())
            fsize_kb = os.path.getsize(COOKIES_PATH) / 1024

            await loading_msg.edit(
                f"🍪 **YouTube Cookies Successfully Updated!**\n\n"
                f"• **Filename:** `cookies.txt`\n"
                f"• **File Size:** `{fsize_kb:.1f} KB`\n"
                f"• **Total Lines:** `{total_lines}`\n"
                f"• **YouTube Entries:** `{yt_entries}`\n\n"
                f"✅ _yt-dlp will now use these cookies for all subsequent downloads._"
            )
            logger.info("Cookies updated from file by owner. Found %d YouTube entries.", yt_entries)
            return
        except Exception as e:
            logger.error("Failed saving cookies file: %s", e)
            await loading_msg.edit(f"❌ **Failed to save cookies file:** {e}")
            return

    # ---------------------------------------------------------
    # 2. COMMANDS (Starting with '/')
    # ---------------------------------------------------------
    if text.startswith("/"):
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        args = parts[1:]

        logger.info("Received command: %s (Args: %s)", cmd, args)

        # /start or /help
        if cmd in ("/start", "/help"):
            help_msg = (
                "🤖 **Welcome to ytdl-telegram Bot!**\n\n"
                "**Quick Usage:**\n"
                "• **Send any YouTube link directly** to fetch details, thumbnail, and select quality with MB size!\n\n"
                "**Cookies Management:**\n"
                "• Send your `cookies.txt` file into this chat to set cookies\n"
                "• `/cookies` - Check current cookies status\n"
                "• `/clearcookies` - Delete stored cookies\n\n"
                "**Batch & Playlist Commands:**\n"
                "• `/playlist <url> [quality] [items]` - Enqueue whole playlist\n"
                "  _e.g. `/playlist https://... 1080 1-10`_\n"
                "• `/single <url> [quality]` - Enqueue single video directly\n"
                "• `/status` - Current queue counts & active worker status\n"
                "• `/pause` | `/resume` - Pause or resume the worker queue\n"
                "• `/retry_failed` - Retry failed queue jobs\n"
                "• `/cancel` - Stop active task and clear queue\n"
                "• `/folder` - Disk space, upload mode & tool status"
            )
            await event.reply(help_msg)
            return

        # /cookies
        elif cmd == "/cookies":
            if COOKIES_PATH.exists() and os.path.getsize(COOKIES_PATH) > 0:
                with open(COOKIES_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                total_lines = len(lines)
                yt_entries = sum(1 for line in lines if "youtube.com" in line.lower())
                fsize_kb = os.path.getsize(COOKIES_PATH) / 1024
                mtime = datetime.fromtimestamp(os.path.getmtime(COOKIES_PATH)).strftime("%Y-%m-%d %H:%M:%S")

                await event.reply(
                    f"🍪 **YouTube Cookies Status: ACTIVE**\n\n"
                    f"• **Path:** `{COOKIES_PATH}`\n"
                    f"• **File Size:** `{fsize_kb:.1f} KB`\n"
                    f"• **Total Lines:** `{total_lines}`\n"
                    f"• **YouTube Entries:** `{yt_entries}`\n"
                    f"• **Last Modified:** `{mtime}`\n\n"
                    f"✅ _All downloads actively utilize these cookies._"
                )
            else:
                await event.reply(
                    "🍪 **YouTube Cookies Status: NOT SET**\n\n"
                    "No `cookies.txt` file found.\n"
                    "👉 To add cookies, simply export cookies from your browser and send the `cookies.txt` file directly into this chat!"
                )
            return

        # /clearcookies
        elif cmd == "/clearcookies":
            if COOKIES_PATH.exists():
                try:
                    os.remove(COOKIES_PATH)
                    await event.reply("✅ `cookies.txt` has been removed. Downloads will run without cookies.")
                except Exception as e:
                    await event.reply(f"❌ Failed to delete cookies: {e}")
            else:
                await event.reply("ℹ️ No cookies file currently exists.")
            return

        # /setcookies (via pasted text)
        elif cmd == "/setcookies":
            raw_data = text[len("/setcookies"):].strip()
            if not raw_data:
                await event.reply("⚠️ **Usage:** `/setcookies <paste Netscape cookies text>`\nOr simply send the `cookies.txt` file as an attachment.")
                return
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(raw_data)
            await event.reply("✅ Cookies saved from message text!")
            return

        # /status
        elif cmd == "/status":
            stats = state.get_stats()
            worker_state_str = "🟢 Running" if worker.is_running else "⚪ Idle"
            if worker.is_paused:
                worker_state_str = "⏸️ Paused"

            status_text = (
                f"📊 **ytdl-telegram Status**\n\n"
                f"**Worker State:** {worker_state_str}\n"
            )
            if worker.current_job:
                status_text += f"🎬 **Active Job:** `{worker.current_job.video_id}` — {worker.current_job.title[:40]}...\n\n"

            status_text += (
                f"• **Uploaded:** {stats['uploaded']}\n"
                f"• **Queued:** {stats['queued']}\n"
                f"• **Downloading:** {stats['downloading']}\n"
                f"• **Downloaded (Ready):** {stats['downloaded']}\n"
                f"• **Uploading:** {stats['uploading']}\n"
                f"• **Failed:** {stats['failed']}\n"
                f"• **Total Tracked:** {stats['total']}"
            )
            await event.reply(status_text)
            return

        # /pause
        elif cmd == "/pause":
            if not worker.is_running:
                await event.reply("⚪ Worker is currently idle.")
            else:
                worker.pause()
                await event.reply("⏸️ **Pipeline paused.** Current video will complete, then processing will halt.")
            return

        # /resume
        elif cmd == "/resume":
            if worker.is_running and not worker.is_paused:
                await event.reply("🟢 Pipeline is already actively running.")
            else:
                worker.resume()
                await event.reply("▶️ **Pipeline resumed.** Continuing queue processing...")
            return

        # /retry_failed
        elif cmd == "/retry_failed":
            reset_cnt = state.retry_all_failed()
            if reset_cnt == 0:
                await event.reply("ℹ️ No failed jobs found in database to retry.")
            else:
                worker.resume()
                await event.reply(f"🔄 Reset **{reset_cnt}** failed job(s) back to queue. Worker triggered!")
            return

        # /cancel (and support common typo /cancle)
        elif cmd in ("/cancel", "/cancle"):
            worker.cancel()
            await event.reply("🛑 **Cancelled.** Pending queued jobs have been cleared.")
            return

        # /cleardb or /resetall
        elif cmd in ("/cleardb", "/resetall", "/clearqueue"):
            worker.cancel()
            deleted = state.clear_database()
            await event.reply(f"🗑️ **Database Cleared!** Removed {deleted} job record(s). You can now enqueue any playlist or video freshly from scratch.")
            return

        # /folder
        elif cmd == "/folder":
            dest_dir = os.getenv("DOWNLOAD_DIR", "downloads")
            os.makedirs(dest_dir, exist_ok=True)
            total, used, free = shutil.disk_usage(dest_dir)
            free_gb = free / (1024 ** 3)
            total_gb = total / (1024 ** 3)

            ffmpeg_ok = bool(find_tool_path("ffmpeg"))
            ffprobe_ok = bool(find_tool_path("ffprobe"))
            deno_ok = bool(find_tool_path("deno"))
            tools_status = f"ffmpeg:{'✅' if ffmpeg_ok else '❌'} ffprobe:{'✅' if ffprobe_ok else '❌'} deno:{'✅' if deno_ok else '❌'}"

            conns = os.getenv("UPLOAD_CONNECTIONS", "4")
            cookies_st = "✅ Active" if COOKIES_PATH.exists() else "⚪ Not set"

            folder_info = (
                "📁 **System & Configuration Info**\n\n"
                f"• **OS Environment:** `{'Windows' if IS_WINDOWS else 'Linux / Colab'}`\n"
                f"• **Download Folder:** `{os.path.abspath(dest_dir)}`\n"
                f"• **Free Disk Space:** `{free_gb:.2f} GB` / `{total_gb:.2f} GB`\n"
                f"• **Upload Mode:** `{UPLOAD_MODE.upper()}`\n"
                f"• **Upload Connections:** `{conns} parallel workers`\n"
                f"• **cryptg Hardware Accel:** `{CRYPTG_STATUS}`\n"
                f"• **Cookies:** `{cookies_st}`\n"
                f"• **Tools:** `{tools_status}`\n"
                f"• **Log File:** `{os.path.abspath(log_file_path)}`"
            )
            await event.reply(folder_info)
            return

        # /playlist <url> [quality] [items]
        elif cmd == "/playlist":
            if not args:
                await event.reply("⚠️ **Usage:** `/playlist <url> [quality] [items]`\n_e.g. `/playlist https://... 1080 1-10`_")
                return

            url = args[0]
            quality = args[1] if len(args) > 1 else "1080"
            items = args[2] if len(args) > 2 else None

            init_msg = await event.reply("🔍 Scanning playlist metadata...")
            try:
                from pipeline import discover_and_enqueue_url
                loop = asyncio.get_running_loop()
                title, new_cnt, tot_cnt = await loop.run_in_executor(
                    None,
                    lambda: discover_and_enqueue_url(url=url, state=state, quality=quality, playlist_items=items),
                )
                await init_msg.edit(
                    f"📋 **Playlist Enqueued!**\n\n"
                    f"• **Title:** {title}\n"
                    f"• **New Videos:** {new_cnt}\n"
                    f"• **Total Detected:** {tot_cnt}\n"
                    f"• **Quality:** {quality}\n\n"
                    f"🚀 Starting background processing..."
                )
                worker.trigger()
            except Exception as e:
                logger.error("Failed to enqueue playlist: %s", e)
                await init_msg.edit(f"❌ **Failed to enqueue playlist:** {e}")
            return

        # /single <url> [quality]
        elif cmd == "/single":
            if not args:
                await event.reply("⚠️ **Usage:** `/single <url> [quality]`\n_e.g. `/single https://... 720`_")
                return
            url = args[0]
            quality = args[1] if len(args) > 1 else "1080"
            init_msg = await event.reply("🔍 Inspecting video metadata...")
            try:
                from pipeline import discover_and_enqueue_url
                loop = asyncio.get_running_loop()
                title, new_cnt, tot_cnt = await loop.run_in_executor(
                    None,
                    lambda: discover_and_enqueue_url(url=url, state=state, quality=quality),
                )
                await init_msg.edit(
                    f"🎬 **Video Enqueued!**\n\n"
                    f"• **Title:** {title}\n"
                    f"• **Quality:** {quality}\n\n"
                    f"🚀 Starting background processing..."
                )
                worker.trigger()
            except Exception as e:
                logger.error("Failed to enqueue video: %s", e)
                await init_msg.edit(f"❌ **Failed to enqueue video:** {e}")
            return

    # ---------------------------------------------------------
    # 3. YOUTUBE LINK DETECTION (Interactive Mode)
    # ---------------------------------------------------------
    match = YT_LINK_REGEX.search(text)
    if match:
        yt_url = match.group(1)
        loading_msg = await event.reply("🔍 **Fetching video details & available formats...**")

        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, lambda: get_video_info(yt_url))

        if not info:
            await loading_msg.edit("❌ **Could not extract video details.** Please verify the URL or try updating cookies.")
            return

        # If it's a playlist
        if info.get("is_playlist"):
            pl_title = info.get("title", "YouTube Playlist")
            pl_count = info.get("count", 0)
            buttons = [
                [
                    Button.inline("📹 1080p", data=f"pl:1080:{yt_url[:40]}".encode()),
                    Button.inline("📹 720p", data=f"pl:720:{yt_url[:40]}".encode()),
                ],
                [
                    Button.inline("📹 480p", data=f"pl:480:{yt_url[:40]}".encode()),
                    Button.inline("🎵 Audio Only", data=f"pl:audio:{yt_url[:40]}".encode()),
                ],
                [Button.inline("❌ Cancel", data=b"cancel:pl")],
            ]
            video_cache[yt_url[:40]] = info
            await loading_msg.edit(
                f"📋 **YouTube Playlist Detected!**\n\n"
                f"🎬 **Title:** {pl_title}\n"
                f"🔢 **Total Videos:** {pl_count}\n\n"
                f"Select default quality to enqueue entire playlist:",
                buttons=buttons,
            )
            return

        # Single video / short
        vid_id = info["id"]
        title = info["title"]
        uploader = info["uploader"]
        duration_str = info["duration_str"]
        thumbnail_url = info.get("thumbnail")
        qualities = info.get("qualities", {})

        video_cache[vid_id] = info

        # Build inline buttons
        buttons = []
        row = []
        for q_key, q_data in qualities.items():
            lbl = q_data["label"]
            mb = q_data["size_mb"]
            size_tag = f" (~{mb:.1f} MB)" if mb > 0 else ""
            btn_text = f"📹 {lbl}{size_tag}" if q_key != "audio" else f"🎵 {lbl}{size_tag}"
            row.append(Button.inline(btn_text, data=f"dl:{vid_id}:{q_key}".encode()))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([Button.inline("❌ Cancel", data=f"cancel:{vid_id}".encode())])

        caption = (
            f"🎬 **{title}**\n\n"
            f"👤 **Channel:** {uploader}\n"
            f"⏱️ **Duration:** `{duration_str}`\n\n"
            f"👇 **Select download quality below:**"
        )

        # Download thumbnail to local temp file to ensure clean Telegram photo sending
        thumb_temp_path = None
        if thumbnail_url:
            try:
                os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                thumb_temp_path = DOWNLOADS_DIR / f"thumb_{vid_id}.jpg"
                req = urllib.request.Request(thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp, open(thumb_temp_path, "wb") as f:
                    f.write(resp.read())
            except Exception as te:
                logger.debug("Could not fetch thumbnail directly: %s", te)
                thumb_temp_path = None

        await loading_msg.delete()

        try:
            if thumb_temp_path and os.path.exists(thumb_temp_path) and os.path.getsize(thumb_temp_path) > 0:
                await bot.send_file(
                    event.chat_id,
                    file=str(thumb_temp_path),
                    caption=caption,
                    buttons=buttons,
                )
            else:
                await bot.send_message(
                    event.chat_id,
                    message=caption,
                    buttons=buttons,
                )
        finally:
            if thumb_temp_path and os.path.exists(thumb_temp_path):
                try:
                    os.remove(thumb_temp_path)
                except OSError:
                    pass


# -------------------------------------------------------------
# Callback Query Handler (Inline Button Clicks)
# -------------------------------------------------------------
@bot.on(events.CallbackQuery)
async def handle_callback_query(event: events.CallbackQuery.Event) -> None:
    if event.sender_id != ALLOWED_USER_ID:
        await event.answer("⚠️ Unauthorized", alert=True)
        return

    raw_data = event.data.decode("utf-8", errors="ignore")

    # Cancel action
    if raw_data.startswith("cancel:"):
        await event.answer("Operation cancelled.")
        await event.edit("❌ **Cancelled by user.**", buttons=None)
        return

    # Playlist enqueue via buttons
    if raw_data.startswith("pl:"):
        parts = raw_data.split(":", 2)
        if len(parts) == 3:
            quality = parts[1]
            pl_key = parts[2]
            info = video_cache.get(pl_key)
            if not info:
                await event.answer("Session expired. Please send the link again.", alert=True)
                return

            url = info["url"]
            await event.answer(f"Enqueuing playlist with {quality}...")
            await event.edit(f"⏳ **Enqueuing playlist at {quality}...**", buttons=None)

            try:
                from pipeline import discover_and_enqueue_url
                loop = asyncio.get_running_loop()
                title, new_cnt, tot_cnt = await loop.run_in_executor(
                    None,
                    lambda: discover_and_enqueue_url(url=url, state=state, quality=quality),
                )
                await event.edit(
                    f"📋 **Playlist Enqueued!**\n\n"
                    f"• **Title:** {title}\n"
                    f"• **New Videos:** {new_cnt}\n"
                    f"• **Total Detected:** {tot_cnt}\n"
                    f"• **Quality:** {quality}\n\n"
                    f"🚀 Sequential processing started in background!",
                    buttons=None,
                )
                worker.trigger()
            except Exception as e:
                logger.error("Error enqueuing playlist via button: %s", e)
                await event.edit(f"❌ **Failed to enqueue playlist:** {e}", buttons=None)
        return

    # Single video download
    if raw_data.startswith("dl:"):
        parts = raw_data.split(":", 2)
        if len(parts) != 3:
            await event.answer("Invalid request.", alert=True)
            return

        vid_id = parts[1]
        quality_key = parts[2]

        info = video_cache.get(vid_id)
        if not info:
            await event.answer("Video metadata expired. Please send link again.", alert=True)
            return

        if vid_id in active_single_downloads:
            await event.answer("This video is already currently being downloaded!", alert=True)
            return

        active_single_downloads[vid_id] = True
        await event.answer(f"Selected {quality_key}. Starting download...")

        # Convert photo caption or message into Live Status Card
        status_card = await event.edit(
            f"🎬 **{info.get('title', 'Video')}**\n"
            f"⚙️ **Quality:** `{quality_key}`\n\n"
            f"📥 **Stage:** Initializing download...\n"
            f"📊 **Progress:** `[░░░░░░░░░░]` 0.0%\n"
            f"🚀 **Speed:** `0.00 MB/s` | ⏳ **ETA:** `--:--`",
            buttons=None,
        )

        asyncio.create_task(
            process_single_video_interactive(
                chat_id=event.chat_id,
                status_msg=status_card,
                video_id=vid_id,
                quality_key=quality_key,
                video_info=info,
            )
        )


# -------------------------------------------------------------
# Main Startup
# -------------------------------------------------------------
def main() -> None:
    """Launches the Telegram Bot listener."""
    check_required_tools(TOOLS_DIR)
    logger.info("=" * 60)
    logger.info("ytdl-telegram: Telegram Bot Controller (Online)")
    logger.info("Environment        : %s", "Windows" if IS_WINDOWS else "Linux / Google Colab")
    logger.info("Authorized User ID : %s", ALLOWED_USER_ID)
    logger.info("Upload Mode        : %s", UPLOAD_MODE.upper())
    logger.info("cryptg status      : %s", CRYPTG_STATUS)
    logger.info("Parallel Workers   : %s connections", os.getenv("UPLOAD_CONNECTIONS", "4"))
    logger.info("Cookies File       : %s", "PRESENT (cookies.txt)" if COOKIES_PATH.exists() else "NOT SET")
    logger.info("Rotating Log File  : %s", log_file_path)
    logger.info("Bot is listening for incoming YouTube links & commands...")
    logger.info("=" * 60)

    bot.start(bot_token=BOT_TOKEN)
    bot.run_until_disconnected()


if __name__ == "__main__":
    main()

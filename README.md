# ytdl-telegram

A high-performance YouTube downloader and Telegram uploader bot with interactive video preview, live speed cards, in-chat cookie management, and full Google Colab cloud support.

---

## 🏗️ Architecture & Key Features

* **Interactive Link Inspector**: Send any YouTube link to the bot. It automatically fetches video metadata (Title, Channel, Duration, Thumbnail) and sends interactive buttons showing each available resolution with its estimated file size in MB (`1080p`, `720p`, `480p`, `360p`, `MP3 Audio`).
* **Live Speed & ETA Card**: Live updating status card for both download and upload:
  - 📥 **Download**: Real-time Download Speed (`MB/s`), Transferred MB, Progress Bar, and ETA.
  - 📤 **Upload**: Real-time Fast Upload Speed (`MB/s`), Transferred MB, Progress Bar, and ETA.
* **In-Chat Cookies Setup**: Upload `cookies.txt` directly as an attachment into the Telegram chat! The bot automatically saves it for downloading age-restricted and private videos. Commands: `/cookies`, `/clearcookies`.
* **Google Colab Ready (`ytdl_colab.ipynb`)**: 1-click cloud execution on Google Colab with 1 Gbps+ high-speed connection. See [COLAB_GUIDE.md](COLAB_GUIDE.md).
* **Sequential Playlist Worker**: Downloads **one video at a time**, uploads immediately, and cleans up local storage. Hard drive never fills up.
* **FastTelethon Parallel Uploading (`uploader_v4.py`)**: Multi-connection pipelined streaming (`UPLOAD_CONNECTIONS=4`) with native `cryptg` C-acceleration. Upload speeds reach full line capacity (**5+ to 30+ MB/s**).
* **Persistent SQLite Queue (`state_v2.py` / `jobs.db`)**: Tracks video states (`queued`, `downloading`, `downloaded`, `uploading`, `uploaded`, `failed`). Resumes automatically after restarts or power outages.
* **Dual Upload Modes (`bot` or `user`)**: Send files as your bot or directly as your personal Telegram user account.
* **Owner-Only Security**: Only your numeric Telegram User ID (`ALLOWED_USER_ID`) can control the bot. Unauthorized messages are silently ignored.
* **Auto-Restart Supervisor (`start_bot_v2.bat`)**: Automatically restarts the bot if it crashes or disconnects.
* **Rotating File Logging**: Writes logs to `logs/bot.log` (5 MB max size with 3 rolling backups).

---

## 🛠️ 1. Portable Tools Setup (`tools/` folder)

This project is **100% portable** and does not require system-wide PATH installation of external binaries.

Place the following three executables directly into the `tools/` folder (`ytdl-telegram\tools\`):

| Executable | Purpose |
| :--- | :--- |
| **`ffmpeg.exe`** | Merges video + audio streams, handles video splitting (>1.95 GB), generates thumbnails |
| **`ffprobe.exe`** | Extracts width, height, and duration so Telegram plays videos natively |
| **`deno.exe`** | Modern JavaScript runtime required by yt-dlp for YouTube format extraction |

---

## 🚀 2. Installation & Configuration

### Step A: Install Python Dependencies
Open PowerShell in the project directory:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Step B: Configure `.env`
Copy `.env.example` to `.env` (or edit existing `.env`):
```env
# Storage & local cleanup
DOWNLOAD_DIR=downloads
KEEP_LOCAL=false

# Number of parallel upload connections (default: 4 for high-speed 5+ MB/s uploads)
UPLOAD_CONNECTIONS=4

# Telegram Bot Credentials (see SETUP_GUIDE.md)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHANNEL_ID=-100xxxxxxxxxx

# Your numeric Telegram User ID (only you can control the bot)
# Send any message to @userinfobot on Telegram to get your ID
ALLOWED_USER_ID=your_numeric_user_id

# Upload Mode: 'bot' (default) or 'user' (uploads as your Telegram account)
UPLOAD_MODE=bot

# Telegram user phone (required only if UPLOAD_MODE=user for initial login)
# TELEGRAM_USER_PHONE=+1234567890
```

---

## 👤 3. Upload Modes: Bot Mode vs User Session Mode (`UPLOAD_MODE=bot|user`)

`ytdl-telegram` supports two upload modes configured via `UPLOAD_MODE` in `.env`:

1. **`UPLOAD_MODE=bot` (Default)**:
   * Uploads videos to your Telegram channel using your Telegram Bot (`TELEGRAM_BOT_TOKEN`).
   * No phone number or code verification required.

2. **`UPLOAD_MODE=user` (User Session Mode)**:
   * Uploads videos to your channel using your **personal Telegram user account** (`TELEGRAM_USER_PHONE`).
   * Videos appear in the channel as sent by you directly.
   * The Telegram Bot client continues running simultaneously to accept commands (`/single`, `/playlist`, `/status`) and update live progress in chat.
   * **Prerequisite**: Your Telegram user account must already be a member or administrator of `TELEGRAM_CHANNEL_ID`.

### 🔑 One-Time Interactive Login for User Mode

When using `UPLOAD_MODE=user`, you must perform a one-time interactive login:

#### Option A: One-Click Helper (Easiest)
Double-click **`login_user.bat`** in the project folder.

#### Option B: Terminal Command
1. Open Command Prompt or PowerShell, navigate to the project directory, and activate your environment:
   ```cmd
   cd /d "C:\Users\debna\.gemini\antigravity\scratch\ytdl-telegram"
   if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
   ```
2. Run the authentication helper:
   ```cmd
   python uploader_v4.py --login --mode user
   ```
3. When prompted:
   * **Phone number**: Enter your phone number with country code (e.g. `+1234567890`) if not pre-configured in `TELEGRAM_USER_PHONE`.
   * **Login code**: Enter the verification code received inside your Telegram app (or SMS).
   * **2FA Password**: If your account has Two-Step Verification enabled, enter your cloud password (characters will be hidden).
4. Upon successful authentication, your session is saved to:
   ```
   sessions/ytdl_user_session.session
   ```
5. All future runs will automatically authenticate using this session file without prompting.

---

> [!CAUTION]
> **CRITICAL SECURITY WARNING: Keep the `sessions/` folder strictly private!**
> 
> * The `sessions/` directory contains active Telegram login credentials (`.session` files).
> * **Never** share, commit, or send files from the `sessions/` folder to anyone. Anyone possessing your `.session` file can access your Telegram account without needing your password or phone code.
> * `sessions/` is already included in `.gitignore` to prevent accidental git commits.

---

## 🎮 4. How to Run

### Method 1: Using the Auto-Restart Watchdog (Recommended)
Double-click **`start_bot_v2.bat`** or run it in your terminal:
```cmd
start_bot_v2.bat
```
* Automatically activates your virtual environment (`.venv` or `venv`).
* Supervises `bot_v2.py` and auto-restarts it in 5 seconds if an unexpected error occurs.


### Method 2: Manual Python Launch
```powershell
python bot_v2.py
```

### Method 3: Command-Line Pipeline (Without Telegram Chat)
If you prefer running directly from your terminal:
```powershell
python pipeline.py "https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID"
```

---

## 💬 5. Telegram Commands Reference

Send these commands to your bot in Telegram:

| Command | Description | Example |
| :--- | :--- | :--- |
| **`/start`** or **`/help`** | Displays the command menu | `/help` |
| **`/playlist <url> [quality] [items]`** | Enqueues a playlist and begins processing | `/playlist https://... 1080`<br>`/playlist https://... 720 1-10`<br>`/playlist https://... audio` |
| **`/single <url> [quality]`** | Enqueues and downloads a single video/audio | `/single https://youtu.be/... 1080` |
| **`/status`** | Shows active video, queue counts, and worker state | `/status` |
| **`/pause`** | Pauses the worker after current video finishes | `/pause` |
| **`/resume`** | Resumes processing a paused queue | `/resume` |
| **`/retry_failed`** | Resets failed jobs and resumes (skips download if file is already on disk) | `/retry_failed` |
| **`/cancel`** | Stops active task and clears pending queued jobs | `/cancel` |
| **`/folder`** | Displays download folder path, free disk space, and tools health | `/folder` |

---

## 🔧 6. Troubleshooting Guide

### A. Updating `yt-dlp` (YouTube Layout Changes)
YouTube frequently updates its internal API. If downloads suddenly fail with extractor errors, update yt-dlp:
```powershell
pip install --upgrade yt-dlp
```

### B. YouTube Cookies (`cookies.txt` or Browser)
For age-restricted, private, or member-only videos:
1. Export your YouTube cookies using a browser extension (such as *Get cookies.txt locally*) into a file named **`cookies.txt`**.
2. Place `cookies.txt` in the `ytdl-telegram/` root directory.
3. The downloader will automatically detect and use it.

### C. Deno or FFmpeg Missing
If you see an error:
```
[ERROR] Missing required portable tool(s) in tools folder!
```
* Verify that `deno.exe`, `ffmpeg.exe`, and `ffprobe.exe` are placed directly in `ytdl-telegram\tools\`.
* Send `/folder` in Telegram to inspect tool status.

### D. Telegram Errors & Solutions

| Error | Cause | Solution |
| :--- | :--- | :--- |
| **Bot does not respond to my commands** | `ALLOWED_USER_ID` mismatch | Send any message to `@userinfobot` on Telegram. Copy the numeric ID into `ALLOWED_USER_ID` in `.env`. Check `logs/bot.log` to see ignored sender IDs. |
| **`ChatAdminRequiredError`** | Bot is not admin in target channel | Go to your Channel Settings $\rightarrow$ **Administrators** $\rightarrow$ Add your Bot as Admin and enable **"Post Messages"**. |
| **`ChannelIdInvalidError`** | Channel ID missing `-100` prefix | Telegram private channel IDs must begin with `-100` (e.g. `-1001234567890`). See `SETUP_GUIDE.md`. |
| **`FloodWaitError`** | Telegram rate-limiting | The bot automatically detects FloodWait and sleeps for the exact number of seconds required before resuming. |

---

## 📜 7. Logs & Auditing

Logs are written to:
```
logs/bot.log
```
* **Auto-rotation**: When `bot.log` reaches 5 MB, it rotates and creates `bot.log.1`, `bot.log.2` (up to 3 backups).
* Contains detailed timestamps, video IDs, upload status, and unauthorized command attempts.

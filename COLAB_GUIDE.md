# 🚀 Google Colab Setup Guide (ytdl-telegram)

Is guide ki madad se aap apne `ytdl-telegram` bot ko **Google Colab** par free mein 24/7 ya jab chahein high-speed cloud connection par chala sakte hain.

---

## ⚡ Method 1: GitHub Se Direct Clone Karna (Recommended - No File Uploads!)

Agar aapne files GitHub par daal di hain:
1. Google Colab ([colab.research.google.com](https://colab.research.google.com/)) par New Notebook kholein.
2. Cell 1 mein run karein:
   ```python
   !git clone https://github.com/<YOUR-USERNAME>/ytdl-telegram.git
   %cd ytdl-telegram
   !apt-get update -qq && !apt-get install -y ffmpeg curl -qq
   !curl -fsSL https://deno.land/install.sh | sh
   !ln -sf /root/.deno/bin/deno /usr/local/bin/deno
   import os; os.environ["PATH"] = f"/root/.deno/bin:{os.environ.get('PATH', '')}"
   !pip install --upgrade yt-dlp -q
   !pip install -r requirements.txt -q
   ```
3. Cell 2 mein apna `.env` banayein aur Cell 3 mein `!python bot_v2.py` run kar dein!

---

## 📋 Method 2: ZIP File Upload Karke Run Karna

### Step 1: Poore Project Folder ko ZIP Banayein
1. Apne computer par `ytdl-telegram` folder par right-click karein.
2. **Send to $\rightarrow$ Compressed (zipped) folder** (ya WinRAR/7-Zip se `.zip` banayein).
   - *(Note: `tools/` folder ke `.exe` files ko zip mein daalna zaroori nahi hai kyunki Colab Linux par chalta hai aur wahan tools automatically install ho jayenge).*

---

### Step 2: Google Colab Kholein
1. Browser mein **[Google Colab](https://colab.research.google.com/)** open karein.
2. **Upload** tab par click karein aur project mein maujood **`ytdl_colab.ipynb`** file ko select karke upload kar dein.

---

### Step 3: Files Upload Karein
1. Colab ke left sidebar mein **Files (Folder icon 📁)** par click karein.
2. Apna banaya hua `ytdl-telegram.zip` drag-and-drop karke upload kar dein.
3. Colab mein ek new code cell banakar unzip kar lein:
   ```python
   !unzip -q ytdl-telegram.zip
   %cd ytdl-telegram
   ```

---

### Step 4: Cells Run Karein

Notebook mein sirf 3 simple steps hain:

1. **Step 1: Install System Tools & Python Packages (▶)**
   - Yeh cell `ffmpeg`, `deno`, `yt-dlp`, `telethon`, aur `cryptg` install kar dega.
2. **Step 2: Enter Telegram Credentials (▶)**
   - Yahan form mein apna `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_BOT_TOKEN`, aur `ALLOWED_USER_ID` daal kar run karein. Yeh `.env` file bana dega.
3. **Step 3: Run Bot (▶)**
   - Bot start ho jayega aur terminal par dikhayega:
     ```
     Bot is listening for incoming YouTube links & commands...
     ```

---

## 🎮 Telegram Par Bot Kaise Use Karein?

1. **Single Video Download:**
   - Bot ko koi bhi YouTube link (Watch URL ya Shorts) send karein.
   - Bot video ka **Thumbnail**, **Title**, **Channel**, aur **Duration** fetch karke bhejega.
   - Neeche **Quality buttons** aayenge jisme **file size (MB)** bhi likha hoga:
     - `📹 1080p (~122 MB)`
     - `📹 720p (~35 MB)`
     - `📹 480p (~25 MB)`
     - `🎵 MP3 Audio (~3 MB)`
   - Kisi bhi quality par click karein:
     - Bot real-time **Download Speed (MB/s)**, progress bar aur ETA dikhayega.
     - Phir real-time **Upload Speed (MB/s)** aur ETA dikhayega.
     - Finish hone par video directly chat mein deliver ho jayegi!

2. **YouTube Cookies Set Karna:**
   - Agar video age-restricted ya member-only ho:
     - Apne browser se export ki hui **`cookies.txt`** file ko Telegram chat mein bot ko send kar dein.
     - Bot use save kar lega aur automatic confirmation dega.
     - Status check karne ke liye: `/cookies`
     - Cookies delete karne ke liye: `/clearcookies`

3. **Playlists:**
   - Playlist link send karein ya `/playlist <url>` command use karein.

---

## ⚡ Colab Ko Disconnect Hone Se Rokne Ka Tip
Agar aap lambi playlist download kar rahe hain aur Colab tab idle hokar disconnect ho jaye:
1. Browser mein `F12` daba kar **Console** tab kholein.
2. Yeh code paste karke Enter daba dein:
   ```javascript
   function ClickConnect(){
     console.log("Working"); 
     document.querySelector("colab-connect-button")?.shadowRoot?.querySelector("#connect")?.click()
   }
   setInterval(ClickConnect, 60000)
   ```
   Yeh har 1 minute mein connection refresh karta rahega.

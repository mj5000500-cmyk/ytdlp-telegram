# 🚀 GitHub to Google Colab Deployment Guide

Yeh guide aapko batayegi ki is folder ko **GitHub par kaise upload karna hai** aur phir **Google Colab par direct clone karke kaise run karna hai**.

---

## 📌 STEP 1: GitHub Par New Repository Banayein

1. Apne browser mein [https://github.com/new](https://github.com/new) kholein.
2. **Repository name** daalein: `ytdl-telegram` (ya koi bhi naam jo aap chahein).
3. Repository ko **Public** ya **Private** select karein (Private safe rehta hai).
4. **"Add a README file"** ko **UNCHECK** rakhein (tick mat lagana).
5. **Create repository** button par click karein.
6. Aapko repository ka URL milega, jaise:
   `https://github.com/<YOUR-USERNAME>/ytdl-telegram.git`

---

## 📌 STEP 2: Is Folder ko GitHub par Push Karein

Apne computer par Command Prompt ya PowerShell kholein aur yeh commands run karein:

```bash
# 1. Is folder me jayein
cd C:\Users\Dell\Desktop\ytdl-telegram-github

# 2. Git initialize karein
git init

# 3. Sabhi important files add karein
git add .

# 4. Commit karein
git commit -m "Initial commit: ytdl-telegram bot"

# 5. Branch ka naam main karein
git branch -M main

# 6. Apni GitHub repo ka URL link karein (Apna username aur repo name replace karein)
git remote add origin https://github.com/<YOUR-USERNAME>/ytdl-telegram.git

# 7. Code push karein
git push -u origin main
```

*(Agar GitHub login maange, toh apna GitHub username aur Personal Access Token enter karein).*

---

## 📌 STEP 3: Google Colab Par 1-Click Clone & Run Karein

Ab aapko Colab par zip file upload karne ki **koi zaroorat nahi hai**!

Google Colab [https://colab.research.google.com/](https://colab.research.google.com/) par New Notebook kholein aur yeh 3 cells banakar run karein:

### **Cell 1: GitHub se Clone & Tools Install Karna (▶)**
```python
# 1. GitHub se clone karein
!git clone https://github.com/<YOUR-USERNAME>/ytdl-telegram.git
%cd ytdl-telegram

# 2. System tools (ffmpeg & Deno) install karein
!apt-get update -qq && apt-get install -y ffmpeg curl -qq
!curl -fsSL https://deno.land/install.sh | sh
!ln -sf /root/.deno/bin/deno /usr/local/bin/deno

import os
os.environ["PATH"] = f"/root/.deno/bin:{os.environ.get('PATH', '')}"

# 3. Python packages install karein
!pip install --upgrade yt-dlp -q
!pip install -r requirements.txt -q

print("\n✅ All Tools and Packages Installed Successfully!")
```

---

### **Cell 2: Telegram Credentials (.env) Setup (▶)**
```python
# Yahan apni Telegram details fill karein:
API_ID = "YOUR_API_ID"              # e.g. 1234567
API_HASH = "YOUR_API_HASH"          # e.g. "abcdef123456"
BOT_TOKEN = "YOUR_BOT_TOKEN"        # e.g. "123456:ABC-DEF"
ALLOWED_USER_ID = "YOUR_USER_ID"    # e.g. 6884772962
CHANNEL_ID = "YOUR_CHANNEL_ID"      # Optional: -100xxxxxxxxxx

env_content = f"""DOWNLOAD_DIR=downloads
KEEP_LOCAL=false
UPLOAD_CONNECTIONS=6
UPLOAD_MODE=bot
TELEGRAM_API_ID={API_ID}
TELEGRAM_API_HASH={API_HASH}
TELEGRAM_BOT_TOKEN={BOT_TOKEN}
ALLOWED_USER_ID={ALLOWED_USER_ID}
TELEGRAM_CHANNEL_ID={CHANNEL_ID}
"""

with open(".env", "w", encoding="utf-8") as f:
    f.write(env_content)

print("✅ Configuration saved to .env!")
```

---

### **Cell 3: Bot Start Karna (▶)**
```python
!python bot_v2.py
```

Jab output mein yeh line aa jaye:
```text
Bot is listening for incoming YouTube links & commands...
```
Aapka bot live ho chuka hai! Telegram par koi bhi YouTube link bhej kar check karein.

---

## 🔒 Security Best Practice
- Aapki personal `.env` file aur Telegram session files `.gitignore` ke through protected hain, isliye yeh GitHub par kabhi upload nahi hongi.
- Apni credentials sirf Google Colab ke Cell 2 mein daalein.

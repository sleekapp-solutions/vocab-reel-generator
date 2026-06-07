# VocabReelGenerator

Turns a list of Arabic/English word pairs into a YouTube Short MP4 — automatically.

**What it generates:**
- A 1080×1920 vocabulary card (gradient background, Arabic right, English left)
- An MP3 voiceover (Arabic spoken first, then English, with pauses)
- A combined MP4 ready to upload
- Optional: auto-uploads to YouTube as a Short

---

## Folder structure

```
VocabReelGenerator/
├── generate_reel.py       ← the main script
├── requirements.txt       ← Python package list
├── client_secrets.json    ← you download this from Google (Step 5)
├── token.json             ← auto-created after first YouTube login
├── assets/
│   └── fonts/
│       ├── Amiri-Regular.ttf      ← Arabic font (Step 3)
│       ├── Roboto-Regular.ttf     ← English font (Step 3)
│       └── Roboto-Bold.ttf        ← Bold font (Step 3)
└── output/
    ├── vocab_image.png    ← generated card
    ├── vocab_audio.mp3    ← generated voiceover
    └── vocab_reel.mp4     ← final video
```

---

## Step-by-step setup (Mac)

### Step 1 — Check Python is installed

Open **Terminal** (press `⌘ Space`, type "Terminal", press Enter) and run:

```bash
python3 --version
```

You should see something like `Python 3.11.x`. If you get "command not found", download Python from [python.org](https://www.python.org/downloads/).

---

### Step 2 — Check FFmpeg is installed

```bash
ffmpeg -version
```

You should see version info. If not, install it with Homebrew:

```bash
brew install ffmpeg
```

If you don't have Homebrew yet:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

---

### Step 3 — Download the fonts

The script needs two free fonts. Download them and place them in `assets/fonts/`.

**Amiri** (Arabic):
1. Go to [fonts.google.com/specimen/Amiri](https://fonts.google.com/specimen/Amiri)
2. Click **Download family** (top right)
3. Unzip the file
4. Copy `Amiri-Regular.ttf` into `assets/fonts/`

**Roboto** (English):
1. Go to [fonts.google.com/specimen/Roboto](https://fonts.google.com/specimen/Roboto)
2. Click **Download family**
3. Unzip the file
4. Copy `Roboto-Regular.ttf` and `Roboto-Bold.ttf` into `assets/fonts/`

Your `assets/fonts/` folder should contain exactly these three files:
```
Amiri-Regular.ttf
Roboto-Regular.ttf
Roboto-Bold.ttf
```

> **Note:** If the fonts are missing, the script still runs — it just uses a plain
> fallback font. The image will look less polished.

---

### Step 4 — Install Python packages

In Terminal, navigate to the project folder:

```bash
cd ~/Desktop/VocabReelGenerator
```

Create a virtual environment (keeps your packages isolated — good practice):

```bash
python3 -m venv venv
source venv/bin/activate
```

Your prompt will change to show `(venv)`. Now install all packages:

```bash
pip install -r requirements.txt
```

This takes about 1–2 minutes. You should see packages downloading.

> Every time you open a new Terminal to run the script, activate the environment first:
> ```bash
> cd ~/Desktop/VocabReelGenerator && source venv/bin/activate
> ```

---

### Step 5 — Set up the YouTube API

This is the most involved step. Do it once and you're done.

#### 5a — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Sign in with your Google account (the one that owns your YouTube channel)
3. At the top, click the project dropdown (it may say "My First Project") → **New Project**
4. Name it anything (e.g. `VocabReel`) → **Create**
5. Make sure your new project is selected in the dropdown

#### 5b — Enable the YouTube Data API

1. In the left sidebar, click **APIs & Services** → **Library**
2. Search for **YouTube Data API v3**
3. Click the result → **Enable**

#### 5c — Create OAuth 2.0 credentials

1. In the left sidebar, click **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth client ID**
3. If prompted to configure a consent screen first:
   - Click **Configure Consent Screen**
   - Choose **External** → **Create**
   - Fill in "App name" (e.g. `VocabReel`) and your email for both fields → **Save and Continue**
   - On the Scopes screen → **Save and Continue**
   - On the Test Users screen, click **+ Add Users**, enter your Google email → **Save and Continue**
   - Click **Back to Dashboard**
   - Then return to **Credentials** → **+ Create Credentials** → **OAuth client ID**
4. For "Application type" choose **Desktop app**
5. Name it anything → **Create**
6. A dialog appears with your client ID and secret — click **Download JSON**
7. Rename the downloaded file to exactly `client_secrets.json`
8. Move it into your `VocabReelGenerator` folder (next to `generate_reel.py`)

---

### Step 6 — Edit the word list

Open `generate_reel.py` in VS Code. Near the top, find the `WORD_PAIRS` section and replace the example words with your own:

```python
WORD_PAIRS = [
    ("مُسْتَدَام",  "Sustainable"),
    ("إِبْدَاع",    "Creativity"),
    # add more pairs here...
]
```

Also update `VIDEO_TITLE`, `VIDEO_DESCRIPTION`, and `VIDEO_TAGS` to match your content.

---

### Step 7 — Run the script

```bash
cd ~/Desktop/VocabReelGenerator
source venv/bin/activate
python3 generate_reel.py
```

**What happens on first run:**
1. The script generates the image and audio
2. A browser tab opens asking you to sign in to Google and authorise the app
3. Click **Allow** (you may see a "Google hasn't verified this app" warning — click **Advanced** → **Go to VocabReel (unsafe)** — this is normal for personal apps)
4. The browser shows "The authentication flow has completed" — you can close it
5. The video uploads to YouTube

**Subsequent runs:** No browser needed — the token is saved in `token.json`.

---

### Step 8 — Check your video on YouTube

1. Go to [studio.youtube.com](https://studio.youtube.com)
2. Click **Content** in the left sidebar
3. Your video will appear with the privacy you set (default: **Private**)
4. Review it, then click the pencil icon → change privacy to **Public** when ready

---

## Customisation

| What to change | Where in `generate_reel.py` |
|---|---|
| Word pairs | `WORD_PAIRS` list at the top |
| Video title / description / tags | `VIDEO_TITLE`, `VIDEO_DESCRIPTION`, `VIDEO_TAGS` |
| Privacy (private/unlisted/public) | `PRIVACY_STATUS` |
| Skip YouTube upload | Set `UPLOAD_TO_YOUTUBE = False` |
| Pause lengths in audio | `PAUSE_AFTER_ARABIC`, `PAUSE_AFTER_ENGLISH` |
| Output folder | `OUTPUT_DIR` |

---

## Troubleshooting

**"FFmpeg not found"**
→ Run `brew install ffmpeg`

**"Missing package 'PIL'"** or similar
→ Make sure you activated the virtual environment: `source venv/bin/activate`, then run `pip install -r requirements.txt`

**"client_secrets.json not found"**
→ Make sure the file is in the `VocabReelGenerator` folder (same level as `generate_reel.py`) and named exactly `client_secrets.json`

**Browser says "Access blocked: this app's request is invalid"**
→ In Google Cloud Console, check that the OAuth consent screen has your email listed under **Test Users**

**Arabic text looks scrambled or backwards**
→ Make sure `arabic-reshaper` and `python-bidi` installed correctly: `pip install arabic-reshaper python-bidi`

**"gTTS failed" or audio step hangs**
→ Check your internet connection. gTTS calls Google's servers for every word.

**Video uploads but isn't showing as a Short**
→ Make sure `#Shorts` is in the title or description (it's included in the default `VIDEO_DESCRIPTION`). YouTube can take a few hours to reclassify a video as a Short.

**"quota exceeded" from YouTube API**
→ The YouTube Data API v3 has a daily quota of 10,000 units. One upload costs ~1,600 units, so you can upload ~6 videos per day on the free tier. Quota resets at midnight Pacific time.

---

## How it works (brief overview)

```
WORD_PAIRS
    │
    ├─→ Pillow (create_image)
    │       Gradient background + Arabic/English layout → vocab_image.png
    │
    ├─→ gTTS + pydub (create_audio)
    │       One TTS clip per word, concatenated with silences → vocab_audio.mp3
    │
    ├─→ FFmpeg (create_video)
    │       Static image looped over audio → vocab_reel.mp4
    │
    └─→ YouTube API (upload_to_youtube)
            OAuth2 login → resumable upload → YouTube Short URL
```
